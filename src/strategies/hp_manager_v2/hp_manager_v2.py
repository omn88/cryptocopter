"""HP Manager V2 - Clean rewrite with 5-state lifecycle and strategy pattern.

Key improvements over V1:
- 5 lifecycle states instead of 12 (IDLE → BUYING → BOUGHT → SELLING → CLOSED)
- Strategy pattern for sell scenarios (direct, convert, multihop)
- Separate order execution states from position lifecycle
- 40% less code, much easier to reason about
"""

import asyncio
import logging
import queue
from typing import Dict, Optional, TYPE_CHECKING

from transitions.extensions.asyncio import AsyncMachine

from src.broker import BrokerSpot
from src.common.client import BinanceClient
from src.common.identifiers import (
    AccountPosition,
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPSellConfig,
    LIFECYCLE_TO_V1_STATE,
    OrderExecutionState,
    PositionLifecycleState,
    SignalUpdate,
    State,
    TickerUpdate,
    V1_STATE_TO_LIFECYCLE,
)
from src.common.symbol import Symbol
from src.database import Database
from src.portfolio.portfolio_event_helper import PortfolioEventHelper
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.strategies.hp_manager_v2.position_buy_v2 import HPPositionBuyV2
from src.strategies.hp_manager_v2.sell_strategies.base import SellExecutionStrategy
from src.strategies.hp_manager_v2.sell_strategies.factory import SellStrategyFactory

# Disable transitions library debug logging to prevent test spam
logging.getLogger("transitions").setLevel(logging.WARNING)

logger = logging.getLogger("HpStrategyV2")


class HpStrategyV2:
    """HP Strategy V2 - Clean 5-state machine with strategy pattern for sells.

    State flow:
    IDLE → BUYING → BOUGHT → SELLING → CLOSED
      ↑                          ↓
      └───────── (cancel) ───────┘

    This is dramatically simpler than V1's 12-state machine!
    """

    def __init__(
        self,
        client: BinanceClient,
        balance: float,
        ui_queue: queue.Queue,
        portfolio_ui_queue: Optional[queue.Queue],
        worker_queue: queue.Queue,
        config_queue: queue.Queue,
        db: Database,
        buy_config: HPBuyConfig,
        sell_config: Optional[HPSellConfig],
        symbols: Dict[str, Symbol],
        broker: BrokerSpot,
        price_resolver: UsdPriceResolver,
        portfolio_event_helper: PortfolioEventHelper,
        initial_state: PositionLifecycleState = PositionLifecycleState.IDLE,
    ):
        """Initialize HP Strategy V2.

        Args:
            client: Binance API client
            balance: Available balance
            ui_queue: Queue for UI updates
            portfolio_ui_queue: Queue for portfolio UI updates
            worker_queue: Queue for portfolio events
            config_queue: Queue for config updates
            db: Database for persistence
            buy_config: Buy configuration
            sell_config: Sell configuration
            symbols: Available trading symbols
            broker: Broker for order execution
            price_resolver: Price resolver for cross-rates
            portfolio_event_helper: Portfolio event helper
            initial_state: Initial lifecycle state (for recovery)
        """
        self.client = client
        self.balance = balance
        self.ui_queue = ui_queue
        self.portfolio_ui_queue = portfolio_ui_queue
        self.worker_queue = worker_queue
        self.config_queue = config_queue
        self.db = db
        self.buy_config = buy_config
        self.sell_config = sell_config
        self.symbols = symbols
        self.broker = broker
        self.price_resolver = price_resolver
        self.portfolio_event_helper = portfolio_event_helper

        # Stop event for graceful shutdown
        self.stop_event: asyncio.Event = asyncio.Event()

        # Current lifecycle state (high-level)
        self.lifecycle_state = initial_state

        # Buy handler (tracks own execution state)
        self.buy = HPPositionBuyV2(
            client=client,
            config=buy_config,
            db=db,
            worker_queue=worker_queue,
        )
        self.buy.prepare_buy_order()

        # Sell strategy (determined by routing logic)
        self.sell_strategy: Optional[SellExecutionStrategy] = None
        if initial_state in [
            PositionLifecycleState.BOUGHT,
            PositionLifecycleState.SELLING,
        ]:
            # Recovery: position already bought, prepare sell strategy
            self._initialize_sell_strategy()

        # Event tracking
        self.ticker_price: Optional[float] = None
        self.signal_update: SignalUpdate = SignalUpdate()
        self.execution_report: ExecutionReport = ExecutionReport()
        self.ticker_update: TickerUpdate = TickerUpdate()
        self.account_position: AccountPosition = AccountPosition()

        # Initialize clean 5-state machine
        self.state_machine = AsyncMachine(
            model=self,
            states=[
                PositionLifecycleState.IDLE,
                PositionLifecycleState.BUYING,
                PositionLifecycleState.BOUGHT,
                PositionLifecycleState.SELLING,
                PositionLifecycleState.CLOSED,
            ],
            transitions=self._get_clean_transitions(),
            initial=initial_state,
            send_event=True,
            model_attribute="lifecycle_state",  # Use lifecycle_state instead of 'state'
        )

    # Type hints for AsyncMachine-generated trigger methods (for mypy only)
    if TYPE_CHECKING:

        async def process_ticker(self, **kwargs) -> None: ...
        async def process_execution_report(self, **kwargs) -> None: ...

    def _get_clean_transitions(self) -> list[dict]:
        """Define clean 5-state transitions.

        Much simpler than V1's 30+ transitions!

        Key insight: All transitions use just 2 triggers (process_ticker, process_execution_report).
        When a trigger is called, AsyncMachine automatically checks ALL transitions with that
        trigger name and executes the first one whose source state and conditions match.
        This is the V1 pattern - automatic evaluation without manual state checking!
        """
        return [
            # IDLE → BUYING: Start buying when price trigger hit
            {
                "trigger": "process_ticker",
                "source": PositionLifecycleState.IDLE,
                "dest": PositionLifecycleState.BUYING,
                "before": "_update_ticker_price",
                "conditions": "can_start_buying",
                "after": "on_buying_started",
            },
            # BUYING → IDLE: Cancel buy when price moves against us
            {
                "trigger": "process_ticker",
                "source": PositionLifecycleState.BUYING,
                "dest": PositionLifecycleState.IDLE,
                "before": "_update_ticker_price",
                "conditions": "should_cancel_buy",
                "after": "on_buy_cancelled",
            },
            # BUYING → BOUGHT: Buy complete (triggered by execution report)
            {
                "trigger": "process_execution_report",
                "source": PositionLifecycleState.BUYING,
                "dest": PositionLifecycleState.BOUGHT,
                "before": "_handle_execution_report",
                "conditions": "buy_is_filled",
                "after": "on_buy_completed",
            },
            # BOUGHT → SELLING: Start selling when price trigger hit
            {
                "trigger": "process_ticker",
                "source": PositionLifecycleState.BOUGHT,
                "dest": PositionLifecycleState.SELLING,
                "before": "_update_ticker_price",
                "conditions": "can_start_selling",
                "after": "on_selling_started",
            },
            # SELLING → BOUGHT: Cancel sell when price moves against us
            {
                "trigger": "process_ticker",
                "source": PositionLifecycleState.SELLING,
                "dest": PositionLifecycleState.BOUGHT,
                "before": "_update_ticker_price",
                "conditions": "should_cancel_sell",
                "after": "on_sell_cancelled",
            },
            # SELLING → CLOSED: Sell complete (triggered by execution report)
            {
                "trigger": "process_execution_report",
                "source": PositionLifecycleState.SELLING,
                "dest": PositionLifecycleState.CLOSED,
                "before": "_handle_execution_report",
                "conditions": "sell_is_filled",
                "after": "on_sell_completed",
            },
        ]

    def _initialize_sell_strategy(self) -> None:
        """Initialize sell strategy based on routing logic."""
        if not self.sell_config:
            logger.warning("Cannot initialize sell strategy: sell_config is None")
            return

        logger.info(f"[{self.sell_config.hp_id}] Initializing sell strategy")

        self.sell_strategy = SellStrategyFactory.create(
            config=self.sell_config,
            symbols=self.symbols,
            client=self.client,
            db=self.db,
            worker_queue=self.worker_queue,
            broker=self.broker,
            price_resolver=self.price_resolver,
            buy_position=self.buy,
        )

    # ========== Condition Methods (Simplified!) ==========

    def can_start_buying(self, event) -> bool:
        """Check if we can start buying.

        HP Manager Strategy: Buy when price DROPS to trigger level.
        Example: buy_price=50000, trigger_price=50500 (1% above buy_price)
        When market price drops from 54000 → 50500, send limit buy at 50000.
        """
        result = (
            self.lifecycle_state == PositionLifecycleState.IDLE
            and self.ticker_price is not None
            and self.ticker_price <= self.buy.trigger_price
            and self.balance >= self.buy_config.budget
        )

        logger.info(
            f"[{self.buy_config.hp_id}] can_start_buying check: "
            f"state={self.lifecycle_state}, ticker={self.ticker_price}, "
            f"trigger={self.buy.trigger_price}, balance={self.balance}, "
            f"budget={self.buy_config.budget} → result={result}"
        )

        return result

    def buy_is_filled(self, event) -> bool:
        """Check if buy is fully filled."""
        return self.buy.is_filled()

    def should_cancel_buy(self, event) -> bool:
        """Check if buy should be cancelled."""
        return (
            self.ticker_price is not None and self.ticker_price >= self.buy.cancel_price
        )

    def can_start_selling(self, event) -> bool:
        """Check if we can start selling."""
        if not self.sell_strategy:
            return False
        return (
            self.lifecycle_state == PositionLifecycleState.BOUGHT
            and self.ticker_price is not None
            and self.sell_strategy.should_send_sell(self.ticker_price)
        )

    def sell_is_filled(self, event) -> bool:
        """Check if sell is fully complete."""
        if not self.sell_strategy:
            return False
        return self.sell_strategy.is_complete()

    def should_cancel_sell(self, event) -> bool:
        """Check if sell should be cancelled."""
        if not self.sell_strategy:
            return False
        return self.ticker_price is not None and self.sell_strategy.should_cancel_sell(
            self.ticker_price
        )

    # ========== Callback Methods ==========

    async def on_buying_started(self, event) -> None:
        """Execute buy orders."""
        logger.info(f"[{self.buy_config.hp_id}] Starting buy")
        await self.buy.execute_buy()
        self.lifecycle_state = PositionLifecycleState.BUYING

        # Update database
        await self.db.upsert_buy_price_level(
            data=self.buy.data,
            strategy_state=self.lifecycle_state,
        )

    async def on_buy_completed(self, event) -> None:
        """Handle buy completion."""
        logger.info(f"[{self.buy_config.hp_id}] Buy complete")
        self.lifecycle_state = PositionLifecycleState.BOUGHT

        # Initialize sell strategy now that we have inventory
        self._initialize_sell_strategy()

        # Update database
        await self.db.upsert_buy_price_level(
            data=self.buy.data,
            strategy_state=self.lifecycle_state,
        )

    async def on_buy_cancelled(self, event) -> None:
        """Handle buy cancellation.
        
        If order has partial inventory, transition to BOUGHT (not IDLE)
        so we can sell the acquired inventory.
        """
        logger.info(f"[{self.buy_config.hp_id}] Cancelling buy")
        await self.buy.cancel_buy()
        
        # Check if we have partial inventory
        has_inventory = (
            self.buy.buy_order is not None 
            and self.buy.buy_order.realized_quantity > 0
        )
        
        if has_inventory:
            # Transition to BOUGHT with partial inventory
            self.lifecycle_state = PositionLifecycleState.BOUGHT
            
            # Initialize sell strategy for the partial inventory
            self._initialize_sell_strategy()
            
            logger.info(
                f"[{self.buy_config.hp_id}] Buy cancelled with partial inventory: "
                f"{self.buy.buy_order.realized_quantity}, transitioning to BOUGHT"
            )
        else:
            # No inventory, back to IDLE
            self.lifecycle_state = PositionLifecycleState.IDLE

        # Update database
        await self.db.upsert_buy_price_level(
            data=self.buy.data,
            strategy_state=self.lifecycle_state,
        )

    async def on_selling_started(self, event) -> None:
        """Execute sell orders."""
        hp_id = self.sell_config.hp_id if self.sell_config else self.buy_config.hp_id
        logger.info(f"[{hp_id}] Starting sell")
        if self.sell_strategy:
            await self.sell_strategy.execute_sell()
        self.lifecycle_state = PositionLifecycleState.SELLING

        # Update database
        await self.db.upsert_buy_price_level(
            data=self.buy.data,
            strategy_state=self.lifecycle_state,
        )

    async def on_sell_completed(self, event) -> None:
        """Handle sell completion."""
        hp_id = self.sell_config.hp_id if self.sell_config else self.buy_config.hp_id
        logger.info(f"[{hp_id}] Sell complete")
        self.lifecycle_state = PositionLifecycleState.CLOSED

        # Update database
        await self.db.upsert_buy_price_level(
            data=self.buy.data,
            strategy_state=self.lifecycle_state,
        )

        # Signal strategy completion
        self.stop_event.set()

    async def on_sell_cancelled(self, event) -> None:
        """Handle sell cancellation."""
        hp_id = self.sell_config.hp_id if self.sell_config else self.buy_config.hp_id
        logger.info(f"[{hp_id}] Cancelling sell")
        if self.sell_strategy:
            await self.sell_strategy.cancel_sell()
        self.lifecycle_state = PositionLifecycleState.BOUGHT

        # Update database
        await self.db.upsert_buy_price_level(
            data=self.buy.data,
            strategy_state=self.lifecycle_state,
        )

    # ========== Event Handlers (V1 Pattern - Callbacks, Not Custom Methods) ==========

    async def _update_ticker_price(self, event) -> None:
        """Update ticker price before transition (called by state machine).

        This is a 'before' callback, not a trigger!
        AsyncMachine creates process_ticker() automatically.
        """
        ticker = event.kwargs.get("ticker")
        if ticker and ticker.symbol == self.buy_config.symbol.name:
            self.ticker_price = ticker.last_price
            logger.info(
                f"[{self.buy_config.hp_id}] Ticker updated: price={self.ticker_price:.2f}, "
                f"state={self.lifecycle_state}, trigger={self.buy.trigger_price:.2f}"
            )

        if self.sell_strategy and ticker:
            await self.sell_strategy.handle_ticker_update(ticker)

    async def _handle_execution_report(self, event) -> None:
        """Handle execution report before transition (called by state machine).

        This is a 'before' callback, not a trigger!
        AsyncMachine creates process_execution_report() automatically.

        NOTE: The executor already calls buy.handle_execution_report() before
        triggering the state machine, so execution_state is already updated.
        This callback can be used for additional transition-specific logic.
        """
        report = event.kwargs.get("report")
        if not report:
            return

        if self.sell_strategy:
            await self.sell_strategy.handle_execution_report(report)

    # NOTE: process_ticker() and process_execution_report() are AUTO-GENERATED by AsyncMachine!
    # Don't define them here - let AsyncMachine create them as triggers.
    # When you call await self.process_ticker(ticker=...), AsyncMachine:
    # 1. Calls _update_ticker_price (before callback)
    # 2. Evaluates conditions for ALL transitions with trigger="process_ticker"
    # 3. Executes first matching transition
    # 4. Calls after callbacks (on_buying_started, etc.)

    async def run(self) -> None:
        """Main event loop."""
        logger.info(
            f"[{self.buy_config.hp_id}] HP Strategy V2 starting "
            f"(state: {self.lifecycle_state})"
        )

        while not self.stop_event.is_set():
            try:
                # Get event from queue (non-blocking with timeout)
                # Increased timeout to reduce CPU usage and logging spam
                event: Event = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, self.config_queue.get
                    ),
                    timeout=1.0,  # 1 second timeout instead of 0.1
                )

                # Route event to appropriate handler
                if event.name == EventName.TICKER and isinstance(
                    event.content, TickerUpdate
                ):
                    await self.process_ticker(ticker=event.content)
                elif event.name == EventName.EXECUTION_REPORT and isinstance(
                    event.content, ExecutionReport
                ):
                    await self.process_execution_report(report=event.content)
                elif event.name == EventName.SENTINEL:
                    logger.info("Received SENTINEL, stopping strategy")
                    break

            except asyncio.CancelledError:
                # Task cancelled during shutdown - exit gracefully
                logger.info(f"[{self.buy_config.hp_id}] Strategy loop cancelled")
                break
            except asyncio.TimeoutError:
                # No event, continue loop
                continue
            except Exception as e:
                logger.error(f"Error in run loop: {e}", exc_info=True)
                continue

        logger.info(f"[{self.buy_config.hp_id}] HP Strategy V2 stopped")

    def get_state_for_persistence(self) -> str:
        """Get V1-compatible state string for database."""
        return LIFECYCLE_TO_V1_STATE[self.lifecycle_state]

    @property
    def state(self) -> State:
        """V1 compatibility: Map V2 lifecycle state to V1 State enum.

        Tests expect strategy.state to be a State enum value.
        We map our clean lifecycle states to V1's granular states based on
        both lifecycle state and execution state.
        """
        # Map lifecycle state to V1 state
        v1_state_str = LIFECYCLE_TO_V1_STATE[self.lifecycle_state]

        # Add granularity based on buy execution state
        if self.lifecycle_state == PositionLifecycleState.BUYING:
            # Check buy order execution state for partial fills
            if self.buy.execution_state == OrderExecutionState.PARTIALLY_FILLED:
                return State.PARTIALLY_BOUGHT
            return State.BUYING

        # For other states, use direct mapping
        return State[v1_state_str]
