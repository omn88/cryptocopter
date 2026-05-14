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
import time
from decimal import Decimal
from typing import Dict, Optional, Any

from src.broker import BrokerSpot
from src.common.client import BinanceClient
from src.domain.enums import EventName, SubscriptionTarget, SubscriptionType
from src.domain.orders import Event, TickerUpdate
from src.domain.subscriptions import SubscriptionInfo
from src.common.symbol import Symbol
from src.database import Database
from src.strategies.buy_dip.broker_adapter import BuyDipBrokerAdapter
from src.strategies.buy_dip.budget_manager import BudgetManager
from src.strategies.buy_dip.config import BuyDipConfig
from src.strategies.buy_dip.strategy import BuyDipStrategy
from src.strategies.buy_dip.ui_messenger import UIMessenger

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
        symbols_dict: Dict[str, Any],  # Symbol name -> Symbol object mapping
        config_queue: Optional[queue.Queue] = None,
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
            symbols_dict: Symbol objects with precision rules (from fetch_symbols)
            config_queue: Optional queue for runtime configuration updates
        """
        self.db = db
        self.broker = broker
        self.client = client
        self.ui_queue = ui_queue
        self.config = config
        self.symbols = symbols
        self.symbols_dict = symbols_dict
        self.config_queue = config_queue

        # Worker queue for async event processing
        self.worker_queue: queue.Queue = queue.Queue()

        # Price tracking for invalidation checks (throttled to 5 seconds)
        self._last_price_check: Dict[str, float] = {}  # symbol -> timestamp
        self._current_prices: Dict[str, float] = {}  # symbol -> price

        # Broker adapters per symbol (create first)
        self.broker_adapters: Dict[str, BuyDipBrokerAdapter] = {}

        # For now, use single adapter for primary symbol (future: multi-symbol support)
        primary_symbol = symbols[0] if symbols else "BTCUSDC"

        # Get Symbol object from symbols_dict
        symbol_obj = symbols_dict.get(primary_symbol)
        if not symbol_obj:
            logger.warning(
                f"Symbol {primary_symbol} not found in symbols_dict, using defaults"
            )
            symbol_obj = Symbol(
                name=primary_symbol,
                precision=8,
                price_precision=2,
                min_notional=10.0,
                lot_size=0.00000001,
                price_filter=0.01,
            )

        primary_adapter = BuyDipBrokerAdapter(client=client, symbol=symbol_obj)

        # Create strategy instance with broker adapter
        self.strategy = BuyDipStrategy(
            config=config,
            total_budget=total_budget,
            order_budget_pct=order_budget_pct,
            broker=None,  # Will use broker adapter instead
            broker_adapter=primary_adapter,
            on_position_update=self._on_position_update,  # UI callback
        )

        # Create UI messenger for budget and position updates
        self._ui_messenger = UIMessenger(strategy=self.strategy, ui_queue=ui_queue)

        # Set up adapter callbacks
        primary_adapter.set_order_filled_callback(self._on_order_filled)
        primary_adapter.set_order_cancelled_callback(self._on_order_cancelled)
        self.broker_adapters[primary_symbol] = primary_adapter

        # Add symbols to strategy
        for symbol in symbols:
            self.strategy.add_symbol(symbol)

        # Async lifecycle management
        self.stop_event = asyncio.Event()
        self.worker_task: Optional[asyncio.Task] = None
        self._task: Optional[asyncio.Task] = None

        logger.info(
            f"BuyDipExecutor initialized for symbols: {symbols}, "
            f"budget: ${total_budget}, order: {order_budget_pct}%"
        )

    def start(self) -> None:
        """
        Start the executor as an asyncio task on the running event loop.
        """
        self._task = asyncio.create_task(self._run())
        logger.info("BuyDipExecutor started")

    def stop(self) -> None:
        """
        Stop the executor gracefully.
        """
        self.stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("BuyDipExecutor stop requested")

    async def _run(self) -> None:
        """
        Main async entry point.
        """
        logger.info("BuyDipExecutor async loop started")

        # Subscribe to kline streams for each symbol (15m candles)
        for symbol in self.symbols:
            kline_subscription = SubscriptionInfo(
                data_type=SubscriptionType.KLINE,
                symbol=symbol,
                target=SubscriptionTarget.BACKEND,
                queue=self.worker_queue,
            )

            self.broker.subscribe(
                system_id=f"buy_dip_{symbol}_kline",
                subscription_info=kline_subscription,
            )

            logger.info(f"Subscribed to {symbol} 15m kline stream")

            # Subscribe to real-time price updates for invalidation checks
            price_subscription = SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=symbol,
                target=SubscriptionTarget.BACKEND,
                queue=self.worker_queue,
            )

            self.broker.subscribe(
                system_id=f"buy_dip_{symbol}_price",
                subscription_info=price_subscription,
            )

            logger.info(f"Subscribed to {symbol} real-time price stream")

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
            logger.error("BuyDipExecutor worker task error: %s", e)
            raise

    async def _worker_loop(self) -> None:
        """
        Process events from worker queue.
        """
        logger.info("BuyDipExecutor worker loop started")

        while not self.stop_event.is_set():
            try:
                # Check for config updates
                if self.config_queue:
                    try:
                        config_update = self.config_queue.get_nowait()
                        self._handle_config_update(config_update)
                    except queue.Empty:
                        pass

                # Process worker queue events
                try:
                    event = self.worker_queue.get_nowait()
                    await self._process_event(event)
                except queue.Empty:
                    await asyncio.sleep(0.1)  # Small delay to avoid busy loop

            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)  # Back off on error

        logger.info("BuyDipExecutor worker loop stopped")

    async def _process_event(self, event: Any) -> None:
        """
        Process an event from the worker queue.

        Handles both Event objects (from broker message handlers) and raw dict events.

        Args:
            event: Event from queue (Event object or raw dict for WebSocket events)
        """
        # Handle Event objects (from broker SubscriptionType.PRICE, etc.)
        if isinstance(event, Event):
            # Handle ticker updates for dynamic sell order management
            if event.name == EventName.TICKER:
                # Type narrow the content to TickerUpdate
                if not isinstance(event.content, TickerUpdate):
                    logger.warning(f"Expected TickerUpdate, got {type(event.content)}")
                    return

                ticker_update = event.content
                symbol = ticker_update.symbol
                current_price = ticker_update.last_price

                # Update current price cache
                self._current_prices[symbol] = current_price

                # Process ticker for sell order management (active positions)
                await self.strategy.process_ticker(symbol, current_price)

                # Also check for invalidation (throttled)
                current_time = time.time()
                last_check = self._last_price_check.get(symbol, 0)
                if current_time - last_check >= 5.0:  # 5 seconds
                    self._last_price_check[symbol] = current_time
                    self.strategy.check_for_invalidation(symbol, current_price)

                return

            # Handle account position updates (balance changes, etc.)
            elif event.name == EventName.ACCOUNT_POSITION:
                # Account position updates - currently not used by Buy Dip
                # but available for future use (e.g., tracking available balance)
                logger.debug("Received account position update")
                return

            # Handle other Event types
            else:
                logger.debug(f"Unhandled Event type: {event.name}")
                return

        # Handle raw dict events (from WebSocket)
        if not isinstance(event, dict):
            return

        event_type = event.get("e")

        # Handle kline (candlestick) events
        if event_type == EventName.KLINE.value:
            kline_data = event.get("k", {})
            is_closed = kline_data.get("x", False)  # x = is closed candle

            # Only process closed candles
            if is_closed:
                symbol_value = event.get("s")
                if not symbol_value or not isinstance(symbol_value, str):
                    logger.warning("Kline event without valid symbol")
                    return

                # symbol_value is now narrowed to str by the isinstance check

                # Create candle dict for strategy
                candle = {
                    "open_time": kline_data.get("t"),
                    "close_time": kline_data.get("T"),
                    "symbol": symbol_value,
                    "open": float(kline_data.get("o", 0)),
                    "high": float(kline_data.get("h", 0)),
                    "low": float(kline_data.get("l", 0)),
                    "close": float(kline_data.get("c", 0)),
                    "volume": float(kline_data.get("v", 0)),
                }

                # Send to strategy (async)
                await self.strategy.process_candle(symbol_value, candle)
                logger.debug(
                    f"Processed closed {symbol_value} candle: {candle['close']}"
                )

        # Handle execution reports (order fills, cancellations)
        elif event_type == EventName.EXECUTION_REPORT.value:
            # Order update from user stream
            exec_symbol = event.get("s")
            if not isinstance(exec_symbol, str):
                logger.warning("Execution report without valid symbol")
                return

            # exec_symbol is now narrowed to str by the isinstance check

            if exec_symbol in self.broker_adapters:
                self.broker_adapters[exec_symbol].handle_user_stream_update(event)
            elif exec_symbol:  # Try to find adapter for this symbol
                # Get adapter for primary symbol as fallback
                for adapter_symbol, adapter in self.broker_adapters.items():
                    if adapter_symbol in exec_symbol:
                        adapter.handle_user_stream_update(event)
                        break

        # Handle account position updates (raw WebSocket format)
        elif event_type == EventName.ACCOUNT_POSITION.value:
            # Account position updates - currently not used by Buy Dip
            logger.debug("Received account position update (raw)")

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

    def _on_position_update(self, position_id: str, event_type: str) -> None:
        """
        Callback from strategy when position is created/updated/completed.

        Args:
            position_id: Position that changed
            event_type: Type of event (position_created, position_updated, position_completed)
        """
        # Send position update to UI
        self._send_position_update(position_id, event_type)
        # Also update budget when position changes
        self._send_budget_update()

    def _handle_config_update(self, config_update: Dict) -> None:
        """
        Handle runtime configuration update from UI.

        Args:
            config_update: Dict with configuration changes
        """
        update_type = config_update.get("type")
        logger.info(f"[CONFIG] Received config update: {config_update}")

        if update_type == "update_config":
            new_budget = config_update.get("total_budget")
            new_order_pct = config_update.get("order_budget_pct")
            new_symbol = config_update.get("symbol")

            logger.info(
                f"Applying config update: budget={new_budget}, "
                f"order_pct={new_order_pct}%, symbol={new_symbol}"
            )

            # Update budget manager
            if new_budget is not None and new_order_pct is not None:
                old_available = self.strategy._budget_manager.get_available_budget()
                old_locked = self.strategy._budget_manager.get_locked_budget()

                # Calculate new available = new_total - currently_locked
                new_total = float(new_budget)
                new_available = new_total - old_locked

                # Create new budget manager with updated values
                # Initialize with new_available, then lock the previously locked amount
                new_budget_mgr = BudgetManager(
                    initial_budget=new_available,
                    order_size_percentage=float(new_order_pct),
                )

                # Re-lock the previously locked funds
                if old_locked > 0:
                    new_budget_mgr._available_budget = new_available
                    new_budget_mgr._locked_budget = old_locked

                # Replace the budget manager
                self.strategy._budget_manager = new_budget_mgr

                logger.info(
                    f"Budget updated: available ${old_available:.2f} -> ${new_available:.2f}, "
                    f"locked ${old_locked:.2f}, order size: {new_order_pct}%"
                )

                # Send updated budget to UI
                self._send_budget_update()

                # Create placeholder WATCHING position for the new/updated config
                if new_symbol:
                    logger.info(
                        f"Creating placeholder position for symbol: {new_symbol}"
                    )
                    # Ensure symbol is being tracked first
                    self.strategy.add_symbol(new_symbol)
                    logger.info(f"Symbol {new_symbol} added to tracking")
                    # Now create placeholder position
                    self.strategy._create_placeholder_watching_position(new_symbol)
                    logger.info(
                        f"Placeholder position creation requested for {new_symbol}"
                    )

            # Symbol change requires restart (not supported at runtime yet)
            if new_symbol and new_symbol != self.symbols[0]:
                logger.warning(
                    f"Symbol change from {self.symbols[0]} to {new_symbol} "
                    "requires restart (not yet implemented)"
                )

    def _send_budget_update(self) -> None:
        """Send budget status to UI - delegate to UI messenger."""
        self._ui_messenger.send_budget_update()

    def _send_position_update(
        self, position_id: str, update_type: str = "position_updated"
    ) -> None:
        """Send position details to UI - delegate to UI messenger.

        Args:
            position_id: Position to send update for
            update_type: Type of update (position_created, position_updated, position_completed)
        """
        self._ui_messenger.send_position_update(position_id, update_type)

    def _send_all_positions_update(self) -> None:
        """Send updates for all positions to UI - delegate to UI messenger."""
        self._ui_messenger.send_all_positions_update()
