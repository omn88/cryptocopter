"""
Buy Dip Strategy Executor

Wraps BuyDipStrategy for integration with AsyncApp and StrategyExecutor pattern.
Handles:
- Market data routing (klines from WebSocket)
- Order placement/cancellation via broker adapter
- Position lifecycle management
- UI updates
"""

import asyncio
import logging
import queue
import threading
from decimal import Decimal
from typing import Dict, Optional

from src.common.client import BinanceClient
from src.database import Database
from src.common.identifiers import (
    SubscriptionInfo,
    SubscriptionType,
    SubscriptionTarget,
)
from src.broker import BrokerSpot
from src.strategies.buy_dip.strategy import BuyDipStrategy
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.broker_adapter import BuyDipBrokerAdapter

logger = logging.getLogger(__name__)


class BuyDipExecutor:
    """
    Executor for Buy Dip strategy - integrates with AsyncApp architecture.

    Responsibilities:
    - Subscribe to kline streams for configured symbols
    - Route candles to BuyDipStrategy
    - Handle order placement/fills via broker adapter
    - Send UI updates
    - Manage async lifecycle
    """

    def __init__(
        self,
        db: Database,
        broker: BrokerSpot,
        client: BinanceClient,
        ui_queue: queue.Queue,
        config: BuyDipConfig,
        total_budget: Decimal,
        order_budget_pct: Decimal,
        symbols: list[str],
    ):
        """
        Initialize Buy Dip executor.

        Args:
            db: Database instance
            broker: Broker instance for subscriptions
            client: BinanceClient for order placement
            ui_queue: Queue for UI updates
            config: Strategy configuration
            total_budget: Total budget in USDC
            order_budget_pct: Order size as % of total budget
            symbols: List of symbols to trade (e.g., ["BTCUSDC"])
        """
        self.db = db
        self.broker = broker
        self.client = client
        self.ui_queue = ui_queue
        self.config = config
        self.symbols = symbols

        # Worker queue for async event processing
        self.worker_queue: queue.Queue = queue.Queue()

        # Broker adapters per symbol (create first)
        self.broker_adapters: Dict[str, BuyDipBrokerAdapter] = {}

        # For now, use single adapter for primary symbol (future: multi-symbol support)
        primary_symbol = symbols[0] if symbols else "BTCUSDC"
        primary_adapter = BuyDipBrokerAdapter(client=client, symbol=primary_symbol)

        # Create strategy instance with broker adapter
        self.strategy = BuyDipStrategy(
            config=config,
            total_budget=total_budget,
            order_budget_pct=order_budget_pct,
            broker=None,  # Will use broker adapter instead
            broker_adapter=primary_adapter,
        )

        # Set up adapter callbacks
        primary_adapter.set_order_filled_callback(self._on_order_filled)
        primary_adapter.set_order_cancelled_callback(self._on_order_cancelled)
        self.broker_adapters[primary_symbol] = primary_adapter

        # Add symbols to strategy
        for symbol in symbols:
            self.strategy.add_symbol(symbol)

        # Async loop management
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.stop_event = threading.Event()
        self.worker_task: Optional[asyncio.Task] = None
        self.thread = threading.Thread(target=self._start_loop)

        logger.info(
            f"BuyDipExecutor initialized for symbols: {symbols}, "
            f"budget: ${total_budget}, order: {order_budget_pct}%"
        )

    def start(self) -> None:
        """
        Start the executor (launch worker thread/loop).
        """
        self.thread.start()
        logger.info("BuyDipExecutor started")

    def stop(self) -> None:
        """
        Stop the executor gracefully.
        """
        self.stop_event.set()
        if self.loop and self.worker_task:
            self.loop.call_soon_threadsafe(self.worker_task.cancel)
        logger.info("BuyDipExecutor stop requested")

    def _start_loop(self) -> None:
        """
        Start asyncio loop in worker thread.
        """
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._run())

    async def _run(self) -> None:
        """
        Main async entry point.
        """
        logger.info("BuyDipExecutor async loop started")

        # Subscribe to price streams for each symbol (will receive ticker/price updates)
        for symbol in self.symbols:
            subscription_info = SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=symbol,
                target=SubscriptionTarget.BACKEND,
                queue=self.worker_queue,
            )

            self.broker.subscribe(
                system_id=f"buy_dip_{symbol}",
                subscription_info=subscription_info,
            )

            logger.info(f"Subscribed to {symbol} price updates")

        # Subscribe to user data stream for order updates
        user_stream_sub = SubscriptionInfo(
            data_type=SubscriptionType.USER,
            symbol="ALL",  # User stream covers all symbols
            target=SubscriptionTarget.BACKEND,
            queue=self.worker_queue,
        )

        self.broker.subscribe(
            system_id="buy_dip_user",
            subscription_info=user_stream_sub,
        )

        logger.info("Subscribed to user data stream")

        # Start worker loop
        self.worker_task = asyncio.create_task(self._worker_loop())

        try:
            await self.worker_task
        except asyncio.CancelledError:
            logger.info("BuyDipExecutor worker task cancelled")
        except Exception as e:
            logger.error(f"BuyDipExecutor worker task error: {e}")

    async def _worker_loop(self) -> None:
        """
        Process events from worker queue.
        """
        logger.info("BuyDipExecutor worker loop started")

        while not self.stop_event.is_set():
            try:
                # Non-blocking queue check
                try:
                    event = self.worker_queue.get_nowait()
                    await self._process_event(event)
                except queue.Empty:
                    await asyncio.sleep(0.1)  # Small delay to avoid busy loop

            except Exception as e:
                logger.error(f"Error in worker loop: {e}")
                await asyncio.sleep(1)  # Back off on error

        logger.info("BuyDipExecutor worker loop stopped")

    async def _process_event(self, event: Dict) -> None:
        """
        Process an event from the worker queue.

        Args:
            event: Event dictionary (price update, user stream update, etc.)
        """
        event_type = event.get("e")

        # For now, we're using price stream which provides ticker updates
        # TODO: Subscribe to dedicated kline stream for proper 15m candles
        # Currently this is a placeholder - real kline subscription needed

        if event_type == "executionReport":
            # Order update from user stream
            symbol = event.get("s")
            if symbol in self.broker_adapters:
                self.broker_adapters[symbol].handle_user_stream_update(event)
            elif symbol:  # Try to find adapter for this symbol
                # Get adapter for primary symbol as fallback
                for adapter_symbol, adapter in self.broker_adapters.items():
                    if adapter_symbol in symbol:
                        adapter.handle_user_stream_update(event)
                        break

    def _on_order_filled(self, order_id: str, fill_price: float) -> None:
        """
        Callback for order fills.

        Args:
            order_id: Order that was filled
            fill_price: Fill price
        """
        # Determine if buy or sell
        if "_sell" in order_id:
            # Sell order filled
            self.strategy.handle_sell_fill(order_id, fill_price)
        else:
            # Buy order filled - use quantity from strategy's pending order
            # For simplicity, use 1.0 as placeholder (actual quantity tracked in strategy)
            self.strategy.handle_order_fill(order_id, fill_price, 1.0)

        # Send UI update
        self.ui_queue.put(
            {
                "type": "order_filled",
                "order_id": order_id,
                "price": fill_price,
            }
        )

        self._send_budget_update()

    def _on_order_cancelled(self, order_id: str) -> None:
        """
        Callback for order cancellations.

        Args:
            order_id: Order that was cancelled
        """
        logger.info(f"Order cancelled: {order_id}")
        # Strategy already handles cancellation internally
        self._send_budget_update()

    def _send_budget_update(self) -> None:
        """
        Send budget status to UI.
        """
        available = self.strategy._budget_manager.get_available_budget()
        locked = self.strategy._budget_manager.get_locked_budget()
        total = available + locked

        self.ui_queue.put(
            {
                "type": "budget",
                "total": total,
                "available": available,
                "locked": locked,
            }
        )

        # Count positions
        active_count = sum(
            1
            for pos in self.strategy._positions.values()
            if pos.state.name in ["POTENTIAL_TOP", "ACTIVE"]
        )

        self.ui_queue.put(
            {
                "type": "positions",
                "active": active_count,
                "total": len(self.strategy._positions),
            }
        )
