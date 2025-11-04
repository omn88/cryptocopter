"""HP Manager V2 Executor - Integrates HpStrategyV2 with AsyncApp architecture.

Follows the same pattern as BuyDipExecutor for consistency:
- Subscribes to market data streams (ticker, klines, user stream)
- Routes events to HpStrategyV2 state machine
- Manages async lifecycle (thread-safe event loop)
- Sends UI updates
- Handles position recovery after crashes
"""

import asyncio
import logging
import queue
import threading
from typing import Dict, Optional

from src.broker import BrokerSpot
from src.common.client import BinanceClient
from src.common.identifiers import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPSellConfig,
    PositionLifecycleState,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    TickerUpdate,
)
from src.common.symbol import Symbol
from src.database import Database
from src.portfolio.portfolio_event_helper import PortfolioEventHelper
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.strategies.hp_manager_v2.hp_manager_v2 import HpStrategyV2

logger = logging.getLogger("HpExecutorV2")


class HpExecutorV2:
    """Executor for HP Strategy V2 - integrates with AsyncApp architecture.

    Responsibilities:
    - Subscribe to ticker/execution streams for position symbol
    - Route market events to HpStrategyV2 state machine
    - Handle UI updates
    - Manage async lifecycle (thread-safe)
    - Position recovery from database
    """

    def __init__(
        self,
        db: Database,
        broker: BrokerSpot,
        client: BinanceClient,
        ui_queue: queue.Queue,
        symbols: Dict[str, Symbol],
        price_resolver: UsdPriceResolver,
        balance: float,
        portfolio_ui_queue: Optional[queue.Queue],
        buy_config: Optional[HPBuyConfig] = None,
        sell_config: Optional[HPSellConfig] = None,
        config_queue: Optional[queue.Queue] = None,
        initial_state: PositionLifecycleState = PositionLifecycleState.IDLE,
    ):
        """Initialize HP Executor V2.

        Args:
            db: Database instance
            broker: Broker for subscriptions
            client: BinanceClient for order placement
            ui_queue: Queue for UI updates
            portfolio_ui_queue: Queue for portfolio updates
            buy_config: Optional buy configuration (can be set later via set_configs)
            sell_config: Optional sell configuration (can be set later via set_configs)
            symbols: Available trading symbols
            price_resolver: Price resolver for cross-rates
            balance: Available balance
            config_queue: Optional queue for runtime config updates
            initial_state: Initial lifecycle state (for recovery)
        """
        self.db = db
        self.broker = broker
        self.client = client
        self.ui_queue = ui_queue
        self.portfolio_ui_queue = portfolio_ui_queue
        self.buy_config = buy_config
        self.sell_config = sell_config
        self.symbols = symbols
        self.price_resolver = price_resolver
        self.balance = balance
        self.config_queue = config_queue
        self.initial_state = initial_state

        # Worker queue for async event processing
        self.worker_queue: queue.Queue = queue.Queue()

        # Portfolio event helper
        self.portfolio_event_helper = PortfolioEventHelper(
            portfolio_event_callback=self._send_portfolio_event
        )

        # Create strategy instance (may start with no configs)
        self.strategy: Optional[HpStrategyV2] = None
        if buy_config and sell_config:
            self.strategy = HpStrategyV2(
                client=client,
                balance=balance,
                ui_queue=ui_queue,
                portfolio_ui_queue=portfolio_ui_queue,
                worker_queue=self.worker_queue,
                config_queue=config_queue or queue.Queue(),
                db=db,
                buy_config=buy_config,
                sell_config=sell_config,
                symbols=symbols,
                broker=broker,
                price_resolver=price_resolver,
                portfolio_event_helper=self.portfolio_event_helper,
                initial_state=initial_state,
            )

        # HP ID for subscriptions
        self.hp_id = buy_config.hp_id if buy_config else None

        # Async loop management
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.stop_event = threading.Event()
        self.worker_task: Optional[asyncio.Task] = None
        self.thread = threading.Thread(target=self._start_loop)

        logger.info(
            f"HpExecutorV2 initialized for HP {self.hp_id}, "
            f"symbol: {buy_config.symbol.name if buy_config else 'None'}, state: {initial_state}"
        )

    def set_configs(
        self, buy_config: HPBuyConfig, sell_config: Optional[HPSellConfig] = None
    ) -> None:
        """Set buy/sell configs and initialize strategy.

        Args:
            buy_config: Buy configuration
            sell_config: Sell configuration
        """
        self.buy_config = buy_config
        self.sell_config = sell_config if sell_config is not None else None
        self.hp_id = buy_config.hp_id

        # Create strategy if not already created
        if not self.strategy:
            self.strategy = HpStrategyV2(
                client=self.client,
                balance=self.balance,
                ui_queue=self.ui_queue,
                portfolio_ui_queue=self.portfolio_ui_queue,
                worker_queue=self.worker_queue,
                config_queue=self.config_queue or queue.Queue(),
                db=self.db,
                buy_config=buy_config,
                sell_config=sell_config if sell_config is not None else None,
                symbols=self.symbols,
                broker=self.broker,
                price_resolver=self.price_resolver,
                portfolio_event_helper=self.portfolio_event_helper,
                initial_state=self.initial_state,
            )
            logger.info(
                f"HpExecutorV2 strategy created for HP {self.hp_id}, symbol: {buy_config.symbol.name}"
            )

    def start(self) -> None:
        """Start the executor (launch worker thread/loop)."""
        if not self.strategy:
            raise RuntimeError(
                "Cannot start executor without configs. Call set_configs() first."
            )
        self.thread.start()
        logger.info(f"HpExecutorV2 started for HP {self.hp_id}")

    def stop(self) -> None:
        """Stop the executor gracefully."""
        logger.info(f"HpExecutorV2 stop requested for HP {self.hp_id}")
        self.stop_event.set()

        # Signal strategy to stop if it exists
        if self.strategy:
            self.strategy.stop_event.set()

        # Cancel worker task
        if self.loop and self.worker_task:
            self.loop.call_soon_threadsafe(self.worker_task.cancel)

    def _start_loop(self) -> None:
        """Start asyncio loop in worker thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run())
        finally:
            # Clean up any pending tasks
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            # Wait for all tasks to finish cancellation
            if pending:
                self.loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            # Close the loop
            self.loop.close()
            logger.info(f"HpExecutorV2 event loop closed for HP {self.hp_id}")

    async def _run(self) -> None:
        """Main async entry point."""
        logger.info(f"HpExecutorV2 async loop started for HP {self.hp_id}")

        # Only subscribe if we have configs
        if self.buy_config:
            # Subscribe to ticker for the trading symbol
            ticker_subscription = SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=self.buy_config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=self.worker_queue,
            )

            self.broker.subscribe(
                system_id=f"{self.hp_id}_ticker",
                subscription_info=ticker_subscription,
            )

            logger.info(
                f"Subscribed to ticker for {self.buy_config.symbol.name} (HP {self.hp_id})"
            )

        # Subscribe to user data stream for order updates
        user_stream_sub = SubscriptionInfo(
            data_type=SubscriptionType.USER,
            symbol="ALL",  # User stream covers all symbols
            target=SubscriptionTarget.BACKEND,
            queue=self.worker_queue,
        )

        self.broker.subscribe(
            system_id=f"{self.hp_id}_user",
            subscription_info=user_stream_sub,
        )

        logger.info(f"Subscribed to user data stream (HP {self.hp_id})")

        # Start worker loop
        self.worker_task = asyncio.create_task(self._worker_loop())

        try:
            await self.worker_task
        except asyncio.CancelledError:
            logger.info(f"HpExecutorV2 worker task cancelled (HP {self.hp_id})")
        except Exception as e:
            logger.error(f"HpExecutorV2 worker task error (HP {self.hp_id}): {e}")
        finally:
            # Close database connection before event loop closes
            await self.db.close()

    async def _worker_loop(self) -> None:
        """Process events from worker queue."""
        logger.info(f"HpExecutorV2 worker loop started for HP {self.hp_id}")

        while not self.stop_event.is_set():
            try:
                # Check for config updates
                if self.config_queue:
                    try:
                        config_update = self.config_queue.get_nowait()
                        await self._handle_config_update(config_update)
                    except queue.Empty:
                        pass

                # Process worker queue events
                try:
                    event = self.worker_queue.get_nowait()
                    await self._process_event(event)
                except queue.Empty:
                    await asyncio.sleep(0.1)  # Small delay to avoid busy loop

            except Exception as e:
                logger.error(
                    f"Error in worker loop (HP {self.hp_id}): {e}", exc_info=True
                )
                await asyncio.sleep(1)  # Back off on error

        logger.info(f"HpExecutorV2 worker loop stopped for HP {self.hp_id}")

    async def _process_event(self, event) -> None:
        """Process an event from the worker queue.

        Routes events to HpStrategyV2 state machine:
        - TICKER events → process_ticker() trigger
        - EXECUTION_REPORT events → process_execution_report() trigger

        Args:
            event: Event from queue (Event object or raw dict)
        """
        # Handle Event objects (from broker message handlers)
        if isinstance(event, Event):
            if event.name == EventName.TICKER:
                # Ticker update - check if we should buy/sell/cancel
                if not isinstance(event.content, TickerUpdate):
                    logger.warning(f"Expected TickerUpdate, got {type(event.content)}")
                    return

                ticker_update = event.content
                if self.strategy:
                    self.strategy.ticker_update = ticker_update
                    self.strategy.ticker_price = ticker_update.last_price

                    # Trigger state machine transitions via ticker
                    await self.strategy.process_ticker(ticker=ticker_update)

            elif event.name == EventName.EXECUTION_REPORT:
                # Order execution update (fill, partial fill, cancel)
                if not isinstance(event.content, ExecutionReport):
                    logger.warning(
                        f"Expected ExecutionReport, got {type(event.content)}"
                    )
                    return

                from binance.enums import ORDER_STATUS_CANCELED

                execution_report = event.content
                if self.strategy:
                    self.strategy.execution_report = execution_report

                    # Handle the execution report first (updates execution_state)
                    # This must happen BEFORE triggering state machine, because
                    # transition conditions check execution_state
                    await self.strategy.buy.handle_execution_report(execution_report)

                    # Also handle sell execution reports BEFORE state machine check
                    if self.strategy.sell_strategy:
                        await self.strategy.sell_strategy.handle_execution_report(
                            execution_report
                        )

                    # Special case: Cancel report with partial inventory
                    # If we're in IDLE after cancelling a partially filled order,
                    # we should stay in IDLE so we can continue buying or sell the inventory
                    # V2 4-state model: IDLE = no active orders (may have inventory)
                    if (
                        execution_report.current_order_status == ORDER_STATUS_CANCELED
                        and self.strategy.lifecycle_state == PositionLifecycleState.IDLE
                        and self.strategy.buy.buy_order is not None
                        and self.strategy.buy.buy_order.realized_quantity > 0
                    ):
                        logger.info(
                            f"[{self.strategy.buy_config.hp_id}] Cancel report with partial inventory, "
                            f"staying in IDLE with inventory: {self.strategy.buy.buy_order.realized_quantity}"
                        )
                        # Initialize sell strategy if we have sell config
                        self.strategy._initialize_sell_strategy()

                        await self.strategy.db.upsert_buy_price_level(
                            data=self.strategy.buy.data,
                            strategy_state=self.strategy.lifecycle_state,
                        )
                        # Don't trigger state machine - we've handled it manually
                        return

                    # Now trigger state machine transitions via execution report
                    # All states can receive execution reports in 4-state model
                    await self.strategy.process_execution_report(
                        report=execution_report
                    )

            elif event.name == EventName.ACCOUNT_POSITION:
                # Account position updates - currently not used
                logger.debug("Received account position update")

            else:
                logger.debug(f"Unhandled Event type: {event.name}")

            return

        # Handle raw dict events (from WebSocket - backwards compatibility)
        if not isinstance(event, dict):
            return

        event_type = event.get("e")

        # Handle execution reports (order fills, cancellations)
        if event_type == EventName.EXECUTION_REPORT.value:
            # Convert to Event object for consistency
            execution_report = ExecutionReport(
                symbol=event.get("s", ""),
                order_id=int(event.get("i", 0)),
                client_order_id=event.get("c", ""),
                side=event.get("S", ""),
                order_type=event.get("o", ""),
                current_order_status=event.get("X", ""),
                cumulative_filled_quantity=float(event.get("z", 0)),
                last_executed_price=float(event.get("L", 0)),
            )

            if self.strategy:
                self.strategy.execution_report = execution_report

                # Trigger state machine directly with execution report
                await self.strategy.process_execution_report(report=execution_report)

    async def _handle_config_update(self, config_update: dict) -> None:
        """Handle runtime configuration update from UI.

        Args:
            config_update: Dict with configuration changes
        """
        update_type = config_update.get("type")
        logger.info(f"[CONFIG HP {self.hp_id}] Received config update: {config_update}")

        if update_type == "close_position":
            # User requested position closure
            logger.info(f"Closing position HP {self.hp_id} via config update")
            if self.strategy:
                self.strategy.stop_event.set()

        elif update_type == "update_sell_price":
            # Update sell price level
            new_sell_price = config_update.get("sell_price")
            if new_sell_price and self.strategy and self.strategy.sell_config:
                self.strategy.sell_config.sell_price = new_sell_price
                logger.info(f"Updated sell price to {new_sell_price}")

    def _send_portfolio_event(self, event_name: EventName, event_data: dict) -> None:
        """Send event to portfolio UI queue.

        Args:
            event_name: The event name (type)
            event_data: Portfolio event data
        """
        if self.portfolio_ui_queue:
            self.portfolio_ui_queue.put(event_data)
            logger.debug(f"Sent portfolio event: {event_name}")

    def get_state(self) -> PositionLifecycleState:
        """Get current lifecycle state."""
        if self.strategy:
            return self.strategy.lifecycle_state
        return PositionLifecycleState.IDLE

    def get_hp_id(self) -> Optional[str]:
        """Get HP ID."""
        return self.hp_id
