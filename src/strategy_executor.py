import asyncio
import logging
import os
import queue
import threading
import time  # Add time import for WebSocket error handling
from typing import Any, Dict, List, Optional, Union
from decouple import Config, RepositoryEnv
from binance.enums import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
)
from src.common.helpers import determine_sell_strategy, generate_hp_id
from src.database import Database
from src.identifiers import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuy,
    HPSellConfig,
    HPSell,
    InventoryItem,
    Order,
    RemoveRecord,
    SellPosition,
    SellType,
    State,
    StateInfo,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
    BinanceClient,
    PositionSide,
    HPSellPositionCreated,
    HPBuyPositionCreated,
    HPSellPositionCompleted,
    HPPositionCancelled,
)
from src.common.symbol import Symbol
from src.gui.identifiers import (
    HPClose,
    HPGuiDataBuy,
    HPGuiDataSell,
    HPUpdate,
)
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.portfolio.inventory_manager import InventoryManager
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell
from src.strategies.hp_manager import HpStrategy
from src.broker import BrokerSpot
from src.database.recovery_service import RecoveryService
from src.database.exceptions import RecoveryError


# Specify the path to the .env file
DOTENV_FILE = "config/.env"
if os.path.exists(DOTENV_FILE):
    config_env = Config(RepositoryEnv(DOTENV_FILE))
else:
    print("Warning: .env file not found! Using default values.")
    config_env = {
        "API_KEY": "key",
        "API_SECRET": "secret",
    }


logger = logging.getLogger("strategy_executor")


class StrategyExecutor:
    def __init__(
        self,
        db: Database,
        broker: BrokerSpot,
        ui_queue: queue.Queue,
        inventory: List[InventoryItem],
        price_resolver: UsdPriceResolver,
        portfolio_ui_queue: Optional[queue.Queue] = None,
        test_mode: bool = False,
    ):
        self.client: Optional[BinanceClient] = None
        self.db = db
        self.broker = broker
        self.ui_queue = ui_queue
        self.portfolio_ui_queue = portfolio_ui_queue
        self.config_queue: queue.Queue = queue.Queue()
        self.strategies: Dict[str, HpStrategy] = {}
        self.inventory_manager = InventoryManager(inventory)  # Create inventory manager
        self.supported_quotes = ["USDC", "PLN", "BTC", "BNB", "USDT"]
        self.test_mode = test_mode  # Add a test_mode parameter
        self.price_resolver = price_resolver
        self.recovery_service: Optional[RecoveryService] = None

        # WebSocket error handling attributes
        self._websocket_error_count = 0
        self._last_websocket_error_time = 0.0
        self._websocket_error_suppression_time = 600  # 10 minutes

        # BinanceClient restart tracking for circuit breaker pattern
        self._restart_count = 0
        self._last_restart_time = 0.0
        self._restart_base_delay = 60  # Start with 1 minute delay
        self._max_restart_delay = 3600  # Maximum 1 hour delay

        # Ticker timeout monitoring for backup circuit breaker
        self._max_ticker_silence_duration = 300  # 5 minutes max silence before restart
        self._ticker_timeout_check_interval = 60  # Check every minute
        self._ticker_timeout_task: Optional[asyncio.Task[None]] = None

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()

    def start_loop(self) -> None:
        """Starts the asyncio loop in a new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self) -> None:
        logger.info("Strategy executor ready to retrieve the first config")
        if not self.test_mode:
            self.client = BinanceClient(
                api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
            )
            self._ticker_timeout_task = asyncio.create_task(
                self._monitor_ticker_timeout()
            )

        self.recovery_service = RecoveryService(
            symbols=self.price_resolver.symbols,
            database=self.db,
            broker=self.broker,
        )
        await self.recover_positions_from_crash()

        # Set up WebSocket error handling (for both test and real mode)
        if hasattr(self.broker, "set_error_handler"):
            self.broker.set_error_handler(self._handle_websocket_error)

        while not self.stop_event.is_set():
            try:
                strategy_data = self.config_queue.get_nowait()
                logger.info("New config for strategy executor: %s", strategy_data)
                if isinstance(strategy_data, HPBuy):
                    asyncio.create_task(self.setup_buy_position(new_hp=strategy_data))
                if isinstance(strategy_data, HPSell):
                    sell_strategy = determine_sell_strategy(
                        config=strategy_data.config, symbols=self.price_resolver.symbols
                    )
                    logger.info("Sell strategy determined: %s", sell_strategy)
                    # Patch: Set symbol if convert-only or USDC
                    if sell_strategy[0].is_convert_only or sell_strategy[
                        0
                    ].name.endswith("USDC"):
                        strategy_data.config.symbol = sell_strategy[0]
                    sell_position = SellPosition(
                        sell_order=Order(quantity=0),
                        config=strategy_data.config,
                        state_info=strategy_data.state_info,
                    )
                    if not strategy_data.config.hp_id:
                        await self.setup_sell_position_with_new_hp(
                            strategy_data=sell_position, sell_strategy=sell_strategy
                        )
                        await self.db.upsert_sell_price_level(
                            data=sell_position, strategy_state=State.BOUGHT
                        )
                    else:
                        await self.setup_sell_position(
                            strategy_data=sell_position, sell_strategy=sell_strategy
                        )

                if isinstance(strategy_data, RemoveRecord):
                    await self.remove_record(
                        hp_id=strategy_data.hp_id, side=strategy_data.side
                    )
                if isinstance(strategy_data, HPClose):
                    await self.close_position(close_data=strategy_data)

            except queue.Empty:
                await asyncio.sleep(0.1)

    def stop(self) -> None:
        logger.info("Stopping strategy executor, stop event SET.")
        self.stop_event.set()

        # Cancel ticker timeout monitoring task if it exists
        if self._ticker_timeout_task and not self._ticker_timeout_task.done():
            self._ticker_timeout_task.cancel()
            logger.info("Cancelled ticker timeout monitoring task")

        if self.client:
            try:
                asyncio.run(self.client.close_connection())
            except RuntimeError:
                logger.warning("No running event loop, skipping async close.")

        logger.info("Client connection closed.")
        self.thread.join()
        logger.info("Strategy executor thread finished")

    async def close_position(self, close_data: HPClose) -> None:
        self.broker.unsubscribe(system_id=close_data.config.hp_id)
        strategy = self.strategies.get(close_data.config.hp_id)

        if strategy:
            # Check if this is a successful completion vs an actual cancellation
            is_successful_completion = (
                close_data.state_info.completeness >= 1.0
                and close_data.state_info.state == State.SOLD
            )

            try:
                if (
                    hasattr(strategy, "sell")
                    and strategy.sell.current_position.sell_order.quantity > 0
                ):
                    if is_successful_completion:
                        # This is a successful sell completion - remove consumed quantities
                        hp_completed = HPSellPositionCompleted(
                            hp_id=close_data.config.hp_id,
                            coin=close_data.config.coin,
                            quantity_sold=close_data.config.quantity,
                            buy_price=close_data.config.buy_price,
                            sell_price=close_data.config.sell_price,
                            end_currency=close_data.config.end_currency,
                        )
                        strategy._send_portfolio_event(
                            EventName.HP_SELL_POSITION_COMPLETED, hp_completed
                        )
                        logger.info(
                            "Sent HP sell completion event for parent position: %s",
                            close_data.config.hp_id,
                        )
                    else:
                        # This is a sell position cancellation - unlock the locked quantities
                        hp_cancelled = HPPositionCancelled(
                            hp_id=close_data.config.hp_id,
                            coin=close_data.config.coin,
                            quantity=strategy.sell.current_position.sell_order.quantity,
                            position_type="SELL",
                        )
                        strategy._send_portfolio_event(
                            EventName.HP_POSITION_CANCELLED, hp_cancelled
                        )
                        logger.info(
                            "Sent manual HP cancellation event for sell position: %s",
                            close_data.config.hp_id,
                        )
                elif hasattr(strategy, "buy") and strategy.buy.orders:
                    # This is a buy position cancellation (buy positions don't have
                    # successful completion via close_position)
                    # Only unlock budget if orders were actually sent to exchange (state != NEW)

                    if strategy.state != State.NEW:
                        # For buy positions, we need to unlock the USDC budget amount,
                        # not the coin quantity
                        budget_amount = strategy.get_remaining_quantity_buy()
                        hp_cancelled = HPPositionCancelled(
                            hp_id=close_data.config.hp_id,
                            coin="USDC",  # The currency being unlocked (budget currency)
                            quantity=budget_amount,  # Amount of USDC budget to unlock
                            position_type="BUY",
                        )
                        strategy._send_portfolio_event(
                            EventName.HP_POSITION_CANCELLED, hp_cancelled
                        )
                        logger.info(
                            "Sent manual HP cancellation event for buy position: %s - "
                            "budget unlocked",
                            close_data.config.hp_id,
                        )
                    else:
                        logger.info(
                            "Skipped budget unlock for buy position %s - "
                            "orders never sent to exchange",
                            close_data.config.hp_id,
                        )
            except Exception as e:
                logger.error(
                    "Failed to send HP event for %s: %s", close_data.config.hp_id, e
                )

            strategy.stop_event.set()
        else:
            logger.warning("Strategy not found for HP ID: %s", close_data.config.hp_id)

    async def setup_buy_position(
        self,
        new_hp: HPBuy,
    ) -> None:

        logger.info("Setting up new position with config: %s", new_hp.config)

        new_hp.config.hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
        new_hp.state_info.generate_open_time()
        worker_queue: queue.Queue = queue.Queue()
        assert self.client is not None

        logger.info("Creating HpStrategy for HP %s", new_hp.config.hp_id)
        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            balance=self.inventory_manager["USDC"]["total_quantity"],
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
            portfolio_ui_queue=self.portfolio_ui_queue,
            buy_position=HPPositionBuy(
                client=self.client,
                data=new_hp,
                db=self.db,
            ),
            sell_position=HPPositionSell(
                client=self.client,
                original_position=SellPosition(
                    config=HPSellConfig(
                        hp_id=new_hp.config.hp_id,
                        symbol=new_hp.config.symbol,
                        coin=new_hp.config.coin,
                    ),
                    state_info=StateInfo(side=PositionSide.SHORT),
                    sell_order=Order(quantity=0.0),
                ),
                db=self.db,
                sell_strategy=[],
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=worker_queue,
            ),
        )

        assert isinstance(strategy.buy.data.config, HPBuyConfig)
        logger.info("HpStrategy created successfully for HP %s", new_hp.config.hp_id)

        # Create new orders for normal setup
        strategy.buy.prepare_orders()
        strategy.buy.data.state_info.generate_open_time()

        self.strategies[new_hp.config.hp_id] = strategy

        self.send_buy_position_to_ui(
            config=new_hp.config,
            state_info=new_hp.state_info,
            state=strategy.state,
            buy_orders=strategy.buy.orders,
        )
        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=new_hp.config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=new_hp.config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

        await self.db.upsert_buy_price_level(
            data=strategy.buy.data, strategy_state=strategy.state
        )

        hp_buy_created = HPBuyPositionCreated(
            hp_id=str(new_hp.config.hp_id),
            coin=new_hp.config.coin,
            budget=new_hp.config.budget,
            price_low=new_hp.config.price_low,
            price_high=new_hp.config.price_high,
            end_currency="USDC",  # Default to USDC for budget locking
        )
        if self.portfolio_ui_queue is not None:
            event = Event(
                name=EventName.HP_BUY_POSITION_CREATED, content=hp_buy_created
            )
            self.portfolio_ui_queue.put_nowait(event)

        strategy.worker_task = asyncio.create_task(strategy.worker())
        logger.info("System with ID %s initialized.", new_hp.config.hp_id)

    def send_buy_position_to_ui(
        self,
        config: HPBuyConfig,
        state_info: StateInfo,
        state: State,
        buy_orders: List[Order],
    ) -> None:
        total_quant = sum(order.realized_quantity for order in buy_orders)
        orders_total_quantity = sum(order.quantity for order in buy_orders)
        # Calculate expected quantity from budget and price configuration
        # For DCA mode, this is the total across all orders
        expected_qty = 0.0
        if config.budget > 0:
            if config.mode.value == "DCA":
                # DCA calculation: sum of quantities across all price levels
                num_orders = 3
                min_budget_for_max_orders = num_orders * config.symbol.min_notional

                if config.budget >= min_budget_for_max_orders:
                    order_quantity_stable = config.budget / num_orders
                else:
                    order_quantity_stable = config.symbol.min_notional
                    num_orders = int(config.budget / config.symbol.min_notional)
                    num_orders = num_orders if num_orders % 2 == 1 else num_orders - 1

                if num_orders == 1:
                    # Single order fallback
                    expected_qty = (
                        config.budget / config.price_high
                        if config.price_high > 0
                        else 0.0
                    )
                else:
                    # Calculate total expected quantity across all DCA orders
                    price_increment = (config.price_high - config.price_low) / (
                        num_orders - 1
                    )
                    for i in range(num_orders):
                        order_price = config.price_high - i * price_increment
                        if order_price > 0:
                            expected_qty += order_quantity_stable / order_price

                    # Round to symbol precision for consistent formatting
                    if hasattr(config.symbol, "precision"):
                        expected_qty = round(expected_qty, config.symbol.precision)
            else:
                # SINGLE mode: budget / price_high
                expected_qty = (
                    config.budget / config.price_high if config.price_high > 0 else 0.0
                )

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuy(config=config, state_info=state_info),
                hp_update=HPUpdate(
                    hp_id=config.hp_id,
                    coin=config.coin,
                    symbol=config.symbol,
                    state=state,
                    buy_price=config.price_high,
                    quantity=float(total_quant) if total_quant else None,
                    expected_quantity=expected_qty,
                    orders_total_quantity=orders_total_quantity,
                    side="BUY",  # Set side to BUY for buy positions
                ),
            )
        )

    def send_sell_position_to_ui(
        self, config: HPSellConfig, state_info: StateInfo, state: State
    ) -> None:
        # Get the correct buy_price - if sell config has 0.0, look up from existing buy position
        buy_price = config.buy_price
        if buy_price == 0.0 and config.hp_id in self.strategies:
            strategy = self.strategies[config.hp_id]
            if (
                hasattr(strategy, "buy")
                and hasattr(strategy.buy, "data")
                and hasattr(strategy.buy.data, "config")
            ):
                buy_price = strategy.buy.data.config.price_high
                logger.info(
                    "Using buy config price_high %s instead of sell config buy_price %s",
                    buy_price,
                    config.buy_price,
                )
            else:
                logger.warning(
                    "Could not find buy config for HP %s, using sell config buy_price",
                    config.hp_id,
                )

        expected_return = None
        if buy_price is not None and config.sell_price is not None:
            expected_return = config.symbol.adjust_price(
                (config.sell_price - buy_price) * config.quantity
            )
        quantity_usd = config.symbol.adjust_price(config.quantity * buy_price)
        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSell(config=config, state_info=state_info),
                hp_update=HPUpdate(
                    hp_id=config.hp_id,
                    buy_price=buy_price,
                    sell_price=config.sell_price,
                    coin=config.coin,
                    symbol=config.symbol,
                    state=state,
                    quantity=config.quantity,
                    quantity_usd=quantity_usd,
                    expected_return=expected_return,
                    side="SELL",  # Set side to SELL for sell positions
                ),
            )
        )

    async def setup_sell_position(
        self, strategy_data: SellPosition, sell_strategy: List[Symbol]
    ) -> None:
        logger.info(
            "Setting up sell position for existing HP: %s", strategy_data.config.hp_id
        )
        strategy: HpStrategy = self.strategies[strategy_data.config.hp_id]
        assert self.client
        if strategy_data.state_info.state == State.NEW:
            strategy.sell = HPPositionSell(
                client=self.client,
                original_position=SellPosition(
                    config=strategy_data.config,
                    state_info=strategy_data.state_info,
                    sell_order=Order(quantity=strategy_data.config.quantity),
                ),
                db=self.db,
                sell_strategy=sell_strategy,
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=strategy.worker_queue,
            )
            logger.info(
                "Current position in standard setup sell: %s",
                strategy.sell.current_position,
            )
        if strategy_data.state_info.state == State.CLOSED:
            logger.info("Closing sell position")
            if strategy.state == State.SELLING:
                await strategy.sell.cancel_position()
            strategy.sell.current_position.config.sell_price = (
                strategy_data.config.sell_price
            )
            strategy.sell.current_position.state_info.ui_state = UiState.CLOSED

        await self.db.upsert_sell_price_level(
            data=strategy.sell.current_position, strategy_state=strategy.state
        )
        self.send_sell_position_to_ui(
            config=strategy.sell.current_position.config,
            state_info=strategy.sell.current_position.state_info,
            state=strategy.state,
        )

    async def setup_sell_position_with_new_hp(
        self,
        strategy_data: SellPosition,
        sell_strategy: List[Symbol],
    ) -> None:
        # For restoration, preserve existing HP ID; for new positions, generate new one
        parent_hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
        strategy_data.config.hp_id = parent_hp_id
        logger.info(
            "Setting up NEW SELL position with config: %s", strategy_data.config
        )

        assert self.client is not None
        assert self.recovery_service is not None
        worker_queue: queue.Queue = queue.Queue()

        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            buy_position=HPPositionBuy(
                client=self.client,
                data=HPBuy(
                    config=HPBuyConfig(
                        hp_id=parent_hp_id,
                        symbol=strategy_data.config.symbol,
                        coin=strategy_data.config.coin,
                    ),
                    state_info=StateInfo(ui_state=UiState.CLOSED, state=State.BOUGHT),
                ),
                db=self.db,
            ),
            sell_position=HPPositionSell(
                client=self.client,
                original_position=SellPosition(
                    config=strategy_data.config,
                    state_info=strategy_data.state_info,
                    sell_order=Order(quantity=strategy_data.config.quantity),
                    sell_type=(
                        SellType.TWOHOPS
                        if len(sell_strategy) == 2
                        else (
                            SellType.CONVERT
                            if sell_strategy[0].is_convert_only
                            else SellType.DIRECT
                        )
                    ),
                ),
                db=self.db,
                sell_strategy=sell_strategy,
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=worker_queue,
            ),
            balance=self.inventory_manager["USDC"]["total_quantity"],
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
            initial_state=State.BOUGHT,
            portfolio_ui_queue=self.portfolio_ui_queue,
        )

        config = strategy.sell.current_position.config

        strategy.sell.current_position.state_info.generate_open_time()

        logger.info("Current position: %s", strategy.sell.current_position)

        self.strategies[parent_hp_id] = strategy

        assert config.symbol.name.endswith(
            tuple(self.supported_quotes)
        ), f"Symbol must end with one of {self.supported_quotes}"
        self.send_sell_position_to_ui(
            config=strategy.sell.original_position.config,
            state_info=strategy.sell.original_position.state_info,
            state=strategy.state,
        )

        for position in strategy.sell.sell_positions:

            self.send_sell_position_to_ui(
                config=position.config,
                state_info=position.state_info,
                state=strategy.state,
            )
        self.broker.subscribe(
            system_id=str(parent_hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        for symbol in sell_strategy:
            self.broker.subscribe(
                system_id=str(parent_hp_id),
                subscription_info=SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol=symbol.name,
                    target=SubscriptionTarget.BACKEND,
                    queue=worker_queue,
                ),
            )

        await self.db.upsert_sell_price_level(
            data=strategy.sell.current_position, strategy_state=strategy.state
        )

        # For two-hop scenarios, save all sell positions to database (not just current position)
        if len(strategy.sell.sell_positions) > 1:
            for position in strategy.sell.sell_positions:
                if (
                    position != strategy.sell.current_position
                ):  # Don't duplicate the current position
                    logger.info(
                        "[MULTIHOP DEBUG] Saving additional position to DB: %s",
                        position.config.hp_id,
                    )
                    await self.db.upsert_sell_price_level(
                        data=position, strategy_state=strategy.state
                    )

        hp_sell_created = HPSellPositionCreated(
            hp_id=parent_hp_id,
            coin=config.coin,
            quantity=config.quantity,
            buy_price=config.buy_price,  # Use buy price from config
            sell_price=config.sell_price,  # Use sell price from config
            end_currency=config.end_currency,  # Use end currency from config
        )
        strategy.send_hp_event_to_portfolio(
            EventName.HP_SELL_POSITION_CREATED, hp_sell_created
        )
        logger.info(
            "Sent HP_SELL_POSITION_CREATED event for new position %s to lock %s %s",
            parent_hp_id,
            config.quantity,
            config.coin,
        )

        strategy.worker_task = asyncio.create_task(strategy.worker())
        logger.info("System with ID %s initialized.", parent_hp_id)

    async def remove_record(self, hp_id: str, side: PositionSide) -> None:
        logger.info(
            "Entering remove record, id: %s to system: %s", hp_id, self.strategies
        )

        # Extract base HP ID using first 4 digits (universal approach for all HP ID patterns)
        base_hp_id = hp_id[:4] if len(hp_id) >= 4 else hp_id
        if base_hp_id != hp_id:
            logger.info(
                "Child position detected. Using base HP ID: %s (from %s)",
                base_hp_id,
                hp_id,
            )

        if base_hp_id not in self.strategies:
            logger.info("HP %s (base: %s) NOT in running strategies", hp_id, base_hp_id)
            return

        strategy: HpStrategy = self.strategies[base_hp_id]
        logger.info(
            "Found strategy with base hp id: %s, original id: %s, side to remove: %s",
            base_hp_id,
            hp_id,
            side,
        )
        buy = strategy.buy
        sell = strategy.sell

        if (
            side == PositionSide.LONG
            and sell.current_position.state_info.state == State.NEW
            and buy.data.state_info.state == State.NEW
        ):
            logger.info("Entered trading system removal!")

            # Send HP buy position cancelled event to portfolio before closing
            if buy.orders and strategy.state != State.NEW:
                # Only unlock budget if orders were actually sent to exchange (state != NEW)
                budget_amount = strategy.get_remaining_quantity_buy()
                hp_cancelled = HPPositionCancelled(
                    hp_id=hp_id,
                    coin="USDC",  # The currency being unlocked (budget currency)
                    quantity=budget_amount,  # Amount of USDC budget to unlock
                    position_type="BUY",
                )
                strategy.send_hp_event_to_portfolio(
                    EventName.HP_POSITION_CANCELLED, hp_cancelled
                )
                logger.info(
                    "Sent manual HP buy cancellation event for position: %s - budget unlocked",
                    hp_id,
                )
            elif buy.orders:
                logger.info(
                    "Skipped budget unlock for buy position %s - orders never sent to exchange",
                    hp_id,
                )

            self.broker.unsubscribe(system_id=hp_id)
            strategy.state = State.CLOSED
            buy.data.state_info.state = State.CLOSED
            if buy.orders:
                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.data.config.symbol.name,
                    orders=buy.orders,
                )
                for order in buy.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        await self.db.upsert_order(
                            order=order,
                            hp_id=hp_id,
                            side=side,
                        )
                buy.data.state_info.get_completeness(buy.orders)

            await self.db.upsert_buy_price_level(data=buy.data)

            buy.data.state_info.ui_state = UiState.CLOSED

            self.send_buy_position_to_ui(
                config=strategy.buy.data.config,
                state_info=strategy.buy.data.state_info,
                state=strategy.state,
                buy_orders=strategy.buy.orders,
            )

            logger.info("Removed strategy %s.", hp_id)
            return

        if (
            side == PositionSide.LONG
            and buy.data.state_info.state == State.PARTIALLY_BOUGHT
        ):
            if strategy.state == State.BUYING:
                # Send HP buy position cancelled event to portfolio for unfilled orders
                # For partial buy cancellations, we need to unlock the remaining USDC budget
                budget_amount = strategy.get_remaining_quantity_buy()
                if budget_amount > 0:
                    hp_cancelled = HPPositionCancelled(
                        hp_id=hp_id,
                        coin="USDC",  # The currency being unlocked (budget currency)
                        quantity=budget_amount,  # Amount of USDC budget to unlock
                        position_type="BUY",
                    )
                    strategy.send_hp_event_to_portfolio(
                        EventName.HP_POSITION_CANCELLED, hp_cancelled
                    )
                    logger.info(
                        "Sent manual HP partial buy cancellation event for position: %s",
                        hp_id,
                    )

                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.data.config.symbol.name,
                    orders=buy.orders,
                )
                strategy.state = buy.data.state_info.state
                for order in buy.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        await self.db.upsert_order(
                            order=order, hp_id=buy.data.config.hp_id, side=side
                        )
            buy.data.state_info.state = State.CLOSED
            buy.data.state_info.ui_state = UiState.CLOSED
            buy.data.state_info.completeness = sum(
                order.realized_quantity for order in buy.orders
            ) / sum(order.quantity for order in buy.orders)
            self.send_buy_position_to_ui(
                config=strategy.buy.data.config,
                state_info=strategy.buy.data.state_info,
                state=strategy.state,
                buy_orders=strategy.buy.orders,
            )

            await self.db.upsert_buy_price_level(data=buy.data)

        if side == PositionSide.LONG and buy.data.state_info.state == State.BOUGHT:
            logger.info("Cancelling fully bought position: %s", hp_id)

            # Send HP buy position cancelled event to portfolio
            # For fully bought position cancellations, we need to unlock any remaining USDC budget
            budget_amount = strategy.get_remaining_quantity_buy()
            hp_cancelled = HPPositionCancelled(
                hp_id=hp_id,
                coin="USDC",  # The currency being unlocked (budget currency)
                quantity=budget_amount,  # Amount of USDC budget to unlock
                position_type="BUY",
            )
            strategy.send_hp_event_to_portfolio(
                EventName.HP_POSITION_CANCELLED, hp_cancelled
            )
            logger.info(
                "Sent manual HP bought position cancellation event for position: %s",
                hp_id,
            )

            # Close the position
            strategy.state = State.CLOSED
            buy.data.state_info.state = State.CLOSED
            buy.data.state_info.ui_state = UiState.CLOSED

            # Update buy orders and database
            await self.db.upsert_buy_price_level(data=buy.data)

            # Send UI update
            self.send_buy_position_to_ui(
                config=strategy.buy.data.config,
                state_info=strategy.buy.data.state_info,
                state=strategy.state,
                buy_orders=strategy.buy.orders,
            )

            logger.info("Cancelled fully bought position %s.", hp_id)
            return

        if side == PositionSide.SHORT:
            logger.info(
                "Processing SHORT side cancellation for %s. Strategy state: %s",
                hp_id,
                strategy.state,
            )
            logger.info(
                "Sell state: %s",
                (
                    sell.current_position.state_info.state
                    if sell.current_position
                    else "No sell position"
                ),
            )

            # Initialize variables for all sell cancellation types
            sell_rlzd_qty = 0.0
            sell_order_qty = 0.0

            if strategy.state == State.SELLING:
                sell_rlzd_qty = (
                    strategy.sell.current_position.sell_order.realized_quantity
                )
                sell_order_qty = strategy.sell.current_position.sell_order.quantity

                # Send HP sell position cancelled event to portfolio before cancelling
                if sell_order_qty > 0:
                    hp_cancelled = HPPositionCancelled(
                        hp_id=hp_id,
                        coin=sell.current_position.config.coin,
                        quantity=sell_order_qty,
                        position_type="SELL",
                    )
                    strategy.send_hp_event_to_portfolio(
                        EventName.HP_POSITION_CANCELLED, hp_cancelled
                    )
                    logger.info(
                        "Sent manual HP sell cancellation event for position: %s", hp_id
                    )
            elif (
                sell.current_position
                and sell.current_position.state_info.state == State.NEW
            ):
                # Handle sell positions that are in NEW state (just created, not actively selling yet)
                logger.info("Cancelling NEW sell position: %s", hp_id)

                # Check if this is a multihop sell (multiple sell_positions)
                if hasattr(sell, "sell_positions") and len(sell.sell_positions) > 1:
                    logger.info(
                        "Detected multihop sell with %d positions",
                        len(sell.sell_positions),
                    )

                    # Cancel ALL positions in the multihop sell by iterating through each position
                    for position in sell.sell_positions:
                        # Set this position as current position temporarily for cancellation
                        original_current = sell.current_position
                        sell.current_position = position

                        # Cancel position using position_sell logic
                        await sell.cancel_position()

                        # Send HP sell position cancelled event to portfolio for each position
                        hp_cancelled = HPPositionCancelled(
                            hp_id=position.config.hp_id,
                            coin=position.config.coin,
                            quantity=position.sell_order.quantity,
                            position_type="SELL",
                        )
                        strategy.send_hp_event_to_portfolio(
                            EventName.HP_POSITION_CANCELLED, hp_cancelled
                        )
                        logger.info(
                            "Sent manual HP sell cancellation event for multihop position: %s",
                            position.config.hp_id,
                        )

                        # Update database for each position
                        await self.db.upsert_sell_price_level(
                            data=position, strategy_state=State.CLOSED
                        )

                        logger.info(
                            "Successfully cancelled multihop sell position: %s",
                            position.config.hp_id,
                        )

                    # Restore original current position
                    sell.current_position = original_current

                    # Now close the parent position (original_position) and strategy
                    strategy.state = State.CLOSED
                    sell.original_position.state_info.state = State.CLOSED
                    sell.original_position.state_info.ui_state = UiState.CLOSED

                    # Update parent position in database - use original_position which is the actual parent (1000)
                    await self.db.upsert_sell_price_level(
                        data=sell.original_position, strategy_state=State.CLOSED
                    )

                    # Remove strategy from active strategies to prevent recovery
                    if base_hp_id in self.strategies:
                        del self.strategies[base_hp_id]

                    logger.info(
                        "Successfully cancelled all multihop sell positions and closed parent strategy: %s",
                        hp_id,
                    )
                else:
                    # Single sell position cancellation
                    sell_order_qty = sell.current_position.sell_order.quantity

                    # Send HP sell position cancelled event to portfolio
                    hp_cancelled = HPPositionCancelled(
                        hp_id=hp_id,
                        coin=sell.current_position.config.coin,
                        quantity=sell_order_qty,
                        position_type="SELL",
                    )
                    strategy.send_hp_event_to_portfolio(
                        EventName.HP_POSITION_CANCELLED, hp_cancelled
                    )
                    logger.info(
                        "Sent manual HP sell cancellation event for NEW position: %s",
                        hp_id,
                    )

                    # Close the sell position
                    sell.current_position.state_info.state = State.CLOSED
                    sell.current_position.state_info.ui_state = UiState.CLOSED

                    # Update database
                    await self.db.upsert_sell_price_level(
                        data=sell.current_position, strategy_state=State.CLOSED
                    )

                    # Send UI update
                    self.send_sell_position_to_ui(
                        config=sell.current_position.config,
                        state_info=sell.current_position.state_info,
                        state=sell.current_position.state_info.state,
                    )

                    logger.info("Successfully cancelled NEW sell position: %s", hp_id)

                return
            else:
                logger.warning(
                    "Sell position %s is in unexpected state. Strategy state: %s",
                    hp_id,
                    strategy.state,
                )
                logger.warning(
                    "Sell position state: %s",
                    (
                        sell.current_position.state_info.state
                        if sell.current_position
                        else "None"
                    ),
                )
                return

            # Common logic for all sell cancellation types (SELLING state)
            fully_bought = all(
                order.status == ORDER_STATUS_FILLED for order in strategy.buy.orders
            )
            await sell.cancel_remaining_order()
            strategy.state = (
                State.PARTIALLY_BOUGHT
                if not fully_bought
                else (
                    State.BOUGHT
                    if fully_bought and not sell_rlzd_qty
                    else (
                        State.PARTIALLY_SOLD
                        if (
                            fully_bought
                            and sell_order_qty
                            and sell_rlzd_qty != sell_order_qty
                        )
                        else (
                            State.PART_SOLD_PART_BOUGHT
                            if (
                                not fully_bought
                                and sell_order_qty
                                and sell_rlzd_qty != sell_order_qty
                            )
                            else State.SOLD
                        )
                    )
                )
            )

            # Send HP sell position completed event to portfolio when fully sold
            if strategy.state == State.SOLD:
                # Calculate the end currency received (typically USDC for the amount received)

                hp_sell_completed = HPSellPositionCompleted(
                    hp_id=hp_id,
                    coin=sell.current_position.config.coin,
                    quantity_sold=sell.current_position.sell_order.realized_quantity,
                    buy_price=sell.current_position.config.buy_price,  # Add missing buy price
                    sell_price=sell.current_position.config.sell_price,  # Add missing sell price
                    end_currency=sell.current_position.config.end_currency,  # Use actual end_currency from config
                )
                logger.info(
                    "Sending HP sell position completed event as part of REMOVE RECORD: %s",
                    hp_sell_completed,
                )
                strategy.send_hp_event_to_portfolio(
                    EventName.HP_SELL_POSITION_COMPLETED, hp_sell_completed
                )

            sell.current_position.config.sell_price = 0.0
            if sell.current_position.config.is_child:
                sell.original_position.config.sell_price = 0.0
                self.send_sell_position_to_ui(
                    config=strategy.sell.original_position.config,
                    state_info=strategy.sell.original_position.state_info,
                    state=strategy.state,
                )
            sell.current_position.state_info.ui_state = UiState.CLOSED
            sell.current_position.state_info.get_completeness(
                sell.current_position.sell_order
            )
            self.send_sell_position_to_ui(
                config=strategy.sell.current_position.config,
                state_info=strategy.sell.current_position.state_info,
                state=strategy.state,
            )
            await self.db.upsert_sell_price_level(
                data=sell.current_position, strategy_state=strategy.state
            )

    async def recover_positions_from_crash(self) -> None:
        """
        Recover all active trading positions from database after system crash/restart.

        This is the main crash recovery method that:
        1. Uses Database to get active positions
        2. Verifies them with the exchange via RecoveryService
        3. Calls setup_buy_position and setup_sell_position_with_new_hp to restore them
        """
        logger.info("Starting crash recovery process...")

        try:
            assert self.recovery_service is not None
            assert self.client is not None

            (
                buy_positions,
                sell_positions,
            ) = await self.recovery_service.recover_all_positions(client=self.client)

            logger.info(
                "Crash recovery found %d buy positions and %d sell positions",
                len(buy_positions),
                len(sell_positions),
            )

            # Restore buy positions using dedicated restore method (preserves HP IDs and state)
            for i, buy_data in enumerate(buy_positions):
                logger.info(
                    "Restoring buy position %d/%d: %s",
                    i + 1,
                    len(buy_positions),
                    buy_data.config.hp_id,
                )
                strategy = await self.recovery_service.restore_buy_position(
                    buy_data=buy_data,
                    client=self.client,
                    ui_queue=self.ui_queue,
                    balance=self.inventory_manager["USDC"]["total_quantity"],
                    config_queue=self.config_queue,
                    price_resolver=self.price_resolver,
                    portfolio_ui_queue=self.portfolio_ui_queue,
                )
                # Strategy management
                self.strategies[buy_data.config.hp_id] = strategy
                self.send_buy_position_to_ui(
                    config=buy_data.config,
                    state_info=buy_data.state_info,
                    state=strategy.state,
                    buy_orders=strategy.buy.orders,
                )
                logger.info(
                    "Successfully restored buy position %s", buy_data.config.hp_id
                )

            # Restore sell positions using dedicated restore method (preserves HP IDs and state)
            for i, sell_data in enumerate(sell_positions):
                logger.info(
                    "Restoring sell position %d/%d: %s",
                    i + 1,
                    len(sell_positions),
                    sell_data.config.hp_id,
                )
                strategy = await self.recovery_service.restore_sell_position(
                    sell_data=sell_data,
                    client=self.client,
                    ui_queue=self.ui_queue,
                    balance=self.inventory_manager["USDC"]["total_quantity"],
                    config_queue=self.config_queue,
                    price_resolver=self.price_resolver,
                    portfolio_ui_queue=self.portfolio_ui_queue,
                )

                # For convert-only positions, use parent HP ID as strategy key
                full_hp_id = sell_data.config.hp_id
                if "_CONVERT" in full_hp_id:
                    strategy_key = full_hp_id.split("_CONVERT")[0]
                elif "_SELL" in full_hp_id:
                    strategy_key = full_hp_id.split("_SELL")[0]
                else:
                    strategy_key = full_hp_id

                self.strategies[strategy_key] = strategy

                self.send_sell_position_to_ui(
                    config=strategy.sell.original_position.config,
                    state_info=strategy.sell.original_position.state_info,
                    state=strategy.state,
                )

                for position in strategy.sell.sell_positions:

                    self.send_sell_position_to_ui(
                        config=position.config,
                        state_info=position.state_info,
                        state=strategy.state,
                    )
                logger.info(
                    "Successfully restored sell position %s", sell_data.config.hp_id
                )

            logger.info(
                "Crash recovery completed successfully. Total strategies now: %d",
                len(self.strategies),
            )

        except RecoveryError as e:
            logger.error("Crash recovery failed: %s", e)
            # Don't raise - let the system continue with empty state
        except Exception as e:
            logger.error("Unexpected error during crash recovery: %s", e, exc_info=True)
            # Don't raise - let the system continue with empty state

    async def _handle_websocket_error(
        self, error_msg: Union[str, Dict[str, Any]]
    ) -> None:
        """Handle WebSocket errors, especially keepalive timeouts and
        unrecoverable failures."""
        current_time = time.time()

        # Check for unrecoverable errors
        unrecoverable_types = [
            "BinanceWebsocketUnableToConnect",
            "BinanceWebsocketClosed",
            "ConnectionClosedError",
            "ConnectionClosedOK",  # Server-initiated disconnections (e.g., "going away")
            "ConnectionClosed",  # Generic connection closed errors
            "TickerTimeoutError",  # Backup circuit breaker for silent ticker streams
        ]
        unrecoverable_msgs = [
            "Max reconnections",
            "timed out during opening handshake",
            "Cannot connect to host",
            "Temporary failure in name resolution",
            "getaddrinfo failed",
            "going away",  # WebSocket close code 1001
            "abnormal closure",  # WebSocket close code 1006
            "received 1001",  # Explicit check for going away code
            "received 1006",  # Explicit check for abnormal closure
        ]

        is_unrecoverable = False
        if isinstance(error_msg, dict):
            error_type = error_msg.get("type", "")
            error_message = error_msg.get("m", "")

            # Check direct error type and message first
            if any(t in error_type for t in unrecoverable_types) or any(
                m in error_message for m in unrecoverable_msgs
            ):
                is_unrecoverable = True

            # Check for nested error messages (common with TickerStreamError)
            if not is_unrecoverable and error_type == "TickerStreamError":
                try:

                    # Handle malfoqrmed JSON by extracting key info
                    if "'e': 'error'" in error_message and "'type':" in error_message:
                        # Extract nested error type using string parsing
                        start_idx = error_message.find("'type': '") + 9
                        if start_idx > 8:  # Found the pattern
                            end_idx = error_message.find("'", start_idx)
                            if end_idx > start_idx:
                                nested_error_type = error_message[start_idx:end_idx]
                                if any(
                                    t in nested_error_type for t in unrecoverable_types
                                ):
                                    logger.warning(
                                        "Detected unrecoverable error in nested "
                                        "TickerStreamError: %s",
                                        nested_error_type,
                                    )
                                    is_unrecoverable = True
                except Exception as e:
                    logger.debug("Error parsing nested error message: %s", e)

        # If unrecoverable, restart websocket client with circuit breaker pattern
        if is_unrecoverable:
            # Calculate delay using circuit breaker pattern
            self._restart_count += 1
            time_since_last_restart = current_time - self._last_restart_time

            # If it's been more than 10 minutes since last restart, reset counter
            if time_since_last_restart > 600:
                self._restart_count = 1

            # Calculate progressive delay: base_delay * (restart_count ^ 1.5), capped at max
            restart_delay = min(
                self._restart_base_delay * (self._restart_count**1.5),
                self._max_restart_delay,
            )

            logger.error(
                "Unrecoverable websocket error detected: %s. Restart #%d. "
                "Waiting %.1f seconds before restarting to allow network to stabilize...",
                error_msg,
                self._restart_count,
                restart_delay,
            )

            # Wait before attempting restart to let network stabilize
            await asyncio.sleep(restart_delay)
            self._last_restart_time = time.time()  # Update after the delay

            retry_count = 0
            while True:
                try:
                    # Stop current client if exists
                    logger.info(
                        "Attempting to restart BinanceClient (restart #%d)...",
                        self._restart_count,
                    )
                    if self.client:
                        try:
                            await self.client.close_connection()
                        except Exception as e:
                            logger.warning("Error closing client: %s", e)
                        self.client = None
                    # Recreate client
                    logger.info("Recreating BinanceClient...")
                    if self.test_mode:
                        logger.info(
                            "Test mode - using injected client, crash recovery will be "
                            "triggered manually when client is assigned"
                        )
                    else:
                        self.client = BinanceClient(
                            api_key=config_env("API_KEY"),
                            api_secret=config_env("API_SECRET"),
                        )
                    logger.info("BinanceClient restarted successfully.")
                    # Resubscribe all strategies
                    await self._resubscribe_all_strategies()
                    logger.info("Resubscription after restart complete.")

                    # Reset restart count on successful restart
                    if retry_count == 0:  # Only reset if first attempt succeeded
                        logger.info(
                            "WebSocket client restart successful. Circuit breaker reset."
                        )
                        # Don't reset _restart_count here - keep it for progressive delay
                    break
                except Exception as e:
                    retry_count += 1
                    restart_retry_delay = min(30, 2**retry_count)
                    logger.error(
                        "Websocket restart attempt #%d failed: %s. Retrying in %d seconds...",
                        retry_count,
                        e,
                        restart_retry_delay,
                    )
                    await asyncio.sleep(restart_retry_delay)
            return

        # Check if this is a keepalive timeout error (legacy logic)
        if isinstance(error_msg, dict):
            error_type = error_msg.get("type", "")
            error_message = error_msg.get("m", "")
            if (
                "keepalive ping timeout" in error_message
                or "ConnectionClosedError" in error_type
            ):
                # Suppress frequent logging of the same error
                if (
                    current_time - self._last_websocket_error_time
                    > self._websocket_error_suppression_time
                ):
                    logger.warning(
                        "WebSocket keepalive timeout detected. This is a known issue with "
                        "python-binance + Python 3.12. Connection will auto-reconnect."
                    )
                    self._last_websocket_error_time = current_time
                    self._websocket_error_count = 1
                else:
                    self._websocket_error_count += 1
                if self._websocket_error_count > 20:
                    logger.warning(
                        "Excessive WebSocket reconnections detected (%d errors), "
                        "will resubscribe all streams",
                        self._websocket_error_count,
                    )
                    await self._resubscribe_all_strategies()
                    self._websocket_error_count = 0
                return

        # Handle other WebSocket errors normally
        logger.error("WebSocket error: %s", error_msg)

    async def _monitor_ticker_timeout(self) -> None:
        """Monitor for ticker timeout and trigger circuit breaker if no
        ticker data for too long."""
        logger.info(
            "Starting ticker timeout monitoring (max silence: %d seconds)",
            self._max_ticker_silence_duration,
        )

        while not self.stop_event.is_set():
            try:
                await asyncio.sleep(self._ticker_timeout_check_interval)

                if self.stop_event.is_set():
                    break

                # Check if broker reports ticker timeout
                if hasattr(self.broker, "_last_ticker_time") and hasattr(
                    self.broker, "_ticker_timeout_threshold"
                ):
                    time_since_ticker = time.time() - self.broker._last_ticker_time
                    if time_since_ticker > self._max_ticker_silence_duration:
                        logger.error(
                            "Backup circuit breaker triggered: ticker silent for %.1f seconds "
                            "(max: %d seconds). Forcing WebSocket restart...",
                            time_since_ticker,
                            self._max_ticker_silence_duration,
                        )

                        # Trigger circuit breaker by simulating an unrecoverable error
                        timeout_error = {
                            "type": "TickerTimeoutError",
                            "m": (
                                f"Ticker silent for {time_since_ticker:.1f} seconds - "
                                "backup circuit breaker activated"
                            ),
                        }
                        await self._handle_websocket_error(timeout_error)
                        return  # Exit monitoring after triggering restart

            except asyncio.CancelledError:
                logger.info("Ticker timeout monitoring task cancelled")
                break
            except Exception as e:
                logger.error("Error in ticker timeout monitoring: %s", e)
                await asyncio.sleep(10)  # Wait before retrying

        logger.info("Ticker timeout monitoring stopped")

    async def _resubscribe_all_strategies(self) -> None:
        """Resubscribe all active strategies after excessive reconnections"""
        logger.info("Resubscribing all active strategy WebSocket streams...")

        for strategy_id, strategy in self.strategies.items():
            try:
                worker_queue = strategy.worker_queue

                # Unsubscribe first
                self.broker.unsubscribe(system_id=str(strategy_id))

                # Wait a bit
                await asyncio.sleep(1)

                # Resubscribe to user data stream
                self.broker.subscribe(
                    system_id=str(strategy_id),
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.USER,
                        symbol=strategy.buy.data.config.symbol.name,
                        target=SubscriptionTarget.BACKEND,
                        queue=worker_queue,
                    ),
                )

                # Resubscribe to price stream
                self.broker.subscribe(
                    system_id=str(strategy_id),
                    subscription_info=SubscriptionInfo(
                        data_type=SubscriptionType.PRICE,
                        symbol=strategy.buy.data.config.symbol.name,
                        target=SubscriptionTarget.BACKEND,
                        queue=worker_queue,
                    ),
                )

            except Exception as e:
                logger.error("Failed to resubscribe strategy %s: %s", strategy_id, e)

        logger.info("Finished resubscribing all strategies")
