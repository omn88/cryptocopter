import asyncio
import logging
import os
import queue
import threading
from typing import Dict, List, Optional
from decouple import Config, RepositoryEnv
from binance.enums import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
)
from src.common.helpers import determine_sell_strategy, generate_hp_id
from src.database import Database
from src.identifiers import (
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
    UiState,
    BinanceClient,
    PositionSide,
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
from src.strategies.hp_manager.position_buy import HPPositionBuy
from src.strategies.hp_manager.position_sell import HPPositionSell
from src.strategies.hp_manager.hp_manager import HpStrategy
from src.broker import BrokerSpot
from src.recovery import RecoveryService
from src.database.exceptions import RecoveryError
from src.portfolio_event_helper import PortfolioEventHelper

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
        self.client: Optional[BinanceClient] = None
        self.recovery_service: Optional[RecoveryService] = None

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

        # Create client if not in test mode and not already set
        if not self.test_mode and self.client is None:
            self.client = BinanceClient(
                api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
            )

        self.recovery_service = RecoveryService(
            symbols=self.price_resolver.symbols,
            database=self.db,
            broker=self.broker,
        )
        await self.recover_positions_from_crash()

        while not self.stop_event.is_set():
            try:
                strategy_data = self.config_queue.get_nowait()
                logger.info("New config for strategy executor: %s", strategy_data)

                if isinstance(strategy_data, HPBuy):
                    await self._handle_buy_config(strategy_data)
                elif isinstance(strategy_data, HPSell):
                    await self._handle_sell_config(strategy_data)
                elif isinstance(strategy_data, RemoveRecord):
                    await self.remove_record(
                        hp_id=strategy_data.hp_id, side=strategy_data.side
                    )
                elif isinstance(strategy_data, HPClose):
                    await self.close_position(close_data=strategy_data)

            except queue.Empty:
                await asyncio.sleep(0.1)

    def stop(self) -> None:
        logger.info("Stopping strategy executor, stop event SET.")
        self.stop_event.set()

        # Close client connection if it exists
        if self.client:
            try:
                asyncio.run(self.client.close_connection())
            except Exception as e:
                logger.error("Error closing client connection: %s", e)

        logger.info("Strategy executor stopped.")
        self.thread.join()
        logger.info("Strategy executor thread finished")

    async def close_position(self, close_data: HPClose) -> None:
        self.broker.unsubscribe(system_id=close_data.config.hp_id)
        strategy = self.strategies.get(close_data.config.hp_id)

        if not strategy:
            logger.warning("Strategy not found for HP ID: %s", close_data.config.hp_id)
            return

        # Check if this is a successful completion vs an actual cancellation
        is_successful_completion = (
            close_data.state_info.completeness >= 1.0
            and close_data.state_info.state == State.SOLD
        )

        try:
            # Handle sell position events
            if (
                hasattr(strategy, "sell")
                and strategy.sell.current_position.sell_order.quantity > 0
            ):
                if is_successful_completion:
                    PortfolioEventHelper.handle_sell_completion(strategy, close_data)
                else:
                    PortfolioEventHelper.handle_sell_cancellation(strategy, close_data)
            # Handle buy position cancellation
            elif hasattr(strategy, "buy") and strategy.buy.orders:
                PortfolioEventHelper.handle_buy_cancellation(strategy, close_data)
        except Exception as e:
            logger.error(
                "Failed to send HP event for %s: %s", close_data.config.hp_id, e
            )

        strategy.stop_event.set()

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

        self.broker.setup_subscriptions(
            hp_id=str(new_hp.config.hp_id),
            symbol=new_hp.config.symbol.name,
            additional_symbols=None,
            worker_queue=worker_queue,
        )

        await self.db.upsert_buy_price_level(
            data=strategy.buy.data, strategy_state=strategy.state
        )

        PortfolioEventHelper.send_buy_creation_event(
            strategy=strategy,
            hp_id=str(new_hp.config.hp_id),
            coin=new_hp.config.coin,
            budget=new_hp.config.budget,
            price_low=new_hp.config.price_low,
            price_high=new_hp.config.price_high,
        )

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

        # Setup broker subscriptions (main symbol + additional symbols for multihop)
        additional_symbols = (
            [s.name for s in sell_strategy[1:]] if len(sell_strategy) > 1 else None
        )
        self.broker.setup_subscriptions(
            hp_id=str(parent_hp_id),
            symbol=config.symbol.name,
            additional_symbols=additional_symbols,
            worker_queue=worker_queue,
        )

        await self.db.upsert_sell_price_level(
            data=strategy.sell.current_position, strategy_state=strategy.state
        )

        # For two-hop scenarios, save all sell positions to database
        await self._persist_multihop_sell_positions(strategy, strategy.state)

        PortfolioEventHelper.send_sell_creation_event(
            strategy=strategy,
            hp_id=parent_hp_id,
            coin=config.coin,
            quantity=config.quantity,
            buy_price=config.buy_price,
            sell_price=config.sell_price,
            end_currency=config.end_currency,
        )

        strategy.worker_task = asyncio.create_task(strategy.worker())
        logger.info("System with ID %s initialized.", parent_hp_id)

    async def remove_record(self, hp_id: str, side: PositionSide) -> None:
        logger.info("Entering remove record, id: %s", hp_id)

        # Extract base HP ID using first 4 digits (universal approach for all HP ID patterns)
        base_hp_id = hp_id[:4]

        if base_hp_id not in self.strategies:
            logger.info("HP %s (base: %s) NOT in running strategies", hp_id, base_hp_id)
            return

        strategy: HpStrategy = self.strategies[base_hp_id]
        logger.info("Found strategy %s, removing side: %s", base_hp_id, side)
        buy = strategy.buy
        sell = strategy.sell

        # Handle removal of NEW buy positions (both buy and sell are NEW)
        if (
            side == PositionSide.LONG
            and sell.current_position.state_info.state == State.NEW
            and buy.data.state_info.state == State.NEW
        ):
            logger.info("Removing NEW trading system: %s", hp_id)

            # Send cancellation event if orders were sent to exchange
            if buy.orders and strategy.state != State.NEW:
                budget_amount = strategy.get_remaining_quantity_buy()
                PortfolioEventHelper.send_cancellation_event(
                    strategy, hp_id, "USDC", budget_amount, "BUY"
                )

            self.broker.unsubscribe(system_id=hp_id)
            strategy.state = State.CLOSED
            await self._close_buy_position(strategy, hp_id, side)
            logger.info("Removed strategy %s.", hp_id)
            return

        # Handle removal of PARTIALLY_BOUGHT positions
        if (
            side == PositionSide.LONG
            and buy.data.state_info.state == State.PARTIALLY_BOUGHT
        ):
            logger.info("Removing PARTIALLY_BOUGHT position: %s", hp_id)

            if strategy.state == State.BUYING:
                budget_amount = strategy.get_remaining_quantity_buy()
                PortfolioEventHelper.send_cancellation_event(
                    strategy, hp_id, "USDC", budget_amount, "BUY"
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

            buy.data.state_info.completeness = sum(
                order.realized_quantity for order in buy.orders
            ) / sum(order.quantity for order in buy.orders)

            await self._close_buy_position(strategy, hp_id, side, cancel_orders=False)

        # Handle removal of BOUGHT positions
        if side == PositionSide.LONG and buy.data.state_info.state == State.BOUGHT:
            logger.info("Cancelling fully bought position: %s", hp_id)

            budget_amount = strategy.get_remaining_quantity_buy()
            PortfolioEventHelper.send_cancellation_event(
                strategy, hp_id, "USDC", budget_amount, "BUY"
            )

            strategy.state = State.CLOSED
            await self._close_buy_position(strategy, hp_id, side, cancel_orders=False)
            logger.info("Cancelled fully bought position %s.", hp_id)
            return

        # Handle SHORT side (sell position) removal
        if side == PositionSide.SHORT:
            logger.info(
                "Processing SHORT side cancellation for %s. Strategy state: %s",
                hp_id,
                strategy.state,
            )

            # Handle NEW sell positions
            if (
                sell.current_position
                and sell.current_position.state_info.state == State.NEW
            ):
                logger.info("Cancelling NEW sell position: %s", hp_id)

                # Check for multihop sell
                if hasattr(sell, "sell_positions") and len(sell.sell_positions) > 1:
                    await self._cancel_multihop_sell(strategy, hp_id, base_hp_id)
                else:
                    # Single sell position cancellation
                    PortfolioEventHelper.send_cancellation_event(
                        strategy,
                        hp_id,
                        sell.current_position.config.coin,
                        sell.current_position.sell_order.quantity,
                        "SELL",
                    )
                    await self._close_sell_position(sell.current_position, State.CLOSED)
                    logger.info("Successfully cancelled NEW sell position: %s", hp_id)

                return

            # Handle SELLING state
            if strategy.state != State.SELLING:
                logger.warning(
                    "Sell position %s in unexpected state: %s", hp_id, strategy.state
                )
                return

            sell_rlzd_qty = sell.current_position.sell_order.realized_quantity
            sell_order_qty = sell.current_position.sell_order.quantity

            PortfolioEventHelper.send_cancellation_event(
                strategy,
                hp_id,
                sell.current_position.config.coin,
                sell_order_qty,
                "SELL",
            )

            # Cancel the sell order and determine final state
            await sell.cancel_remaining_order()

            final_state = self._calculate_sell_cancellation_state(
                strategy, sell_rlzd_qty, sell_order_qty
            )
            strategy.state = final_state

            # Send completion event if fully sold
            if final_state == State.SOLD:
                PortfolioEventHelper.send_sell_completion_event(
                    strategy=strategy,
                    hp_id=hp_id,
                    coin=sell.current_position.config.coin,
                    quantity_sold=sell.current_position.sell_order.realized_quantity,
                    buy_price=sell.current_position.config.buy_price,
                    sell_price=sell.current_position.config.sell_price,
                    end_currency=sell.current_position.config.end_currency,
                )

            # Update positions and database
            sell.current_position.config.sell_price = 0.0
            sell.current_position.state_info.ui_state = UiState.CLOSED
            sell.current_position.state_info.get_completeness(
                sell.current_position.sell_order
            )

            if sell.current_position.config.is_child:
                sell.original_position.config.sell_price = 0.0
                self.send_sell_position_to_ui(
                    config=sell.original_position.config,
                    state_info=sell.original_position.state_info,
                    state=strategy.state,
                )

            self.send_sell_position_to_ui(
                config=sell.current_position.config,
                state_info=sell.current_position.state_info,
                state=strategy.state,
            )
            await self.db.upsert_sell_price_level(
                data=sell.current_position, strategy_state=strategy.state
            )

    async def recover_positions_from_crash(self) -> None:
        """Recover all active trading positions from database after system crash/restart."""
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

            # Restore buy positions
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

            # Restore sell positions
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

    async def _close_buy_position(
        self,
        strategy: HpStrategy,
        hp_id: str,
        side: PositionSide,
        cancel_orders: bool = True,
    ) -> None:
        """Close buy position and update database/UI."""
        buy = strategy.buy

        if cancel_orders and buy.orders:
            buy.orders = await buy.cancel_remaining_limit_orders(
                symbol=buy.data.config.symbol.name,
                orders=buy.orders,
            )
            for order in buy.orders:
                if order.status == ORDER_STATUS_CANCELED:
                    await self.db.upsert_order(order=order, hp_id=hp_id, side=side)
            buy.data.state_info.get_completeness(buy.orders)

        buy.data.state_info.state = State.CLOSED
        buy.data.state_info.ui_state = UiState.CLOSED

        await self.db.upsert_buy_price_level(data=buy.data)

        self.send_buy_position_to_ui(
            config=buy.data.config,
            state_info=buy.data.state_info,
            state=strategy.state,
            buy_orders=buy.orders,
        )

    async def _close_sell_position(
        self, sell_position: SellPosition, strategy_state: State
    ) -> None:
        """Close sell position and update database/UI."""
        sell_position.state_info.state = State.CLOSED
        sell_position.state_info.ui_state = UiState.CLOSED

        await self.db.upsert_sell_price_level(
            data=sell_position, strategy_state=strategy_state
        )

        self.send_sell_position_to_ui(
            config=sell_position.config,
            state_info=sell_position.state_info,
            state=strategy_state,
        )

    def _calculate_sell_cancellation_state(
        self, strategy: HpStrategy, sell_realized_qty: float, sell_order_qty: float
    ) -> State:
        """Calculate strategy state after sell cancellation."""
        fully_bought = all(
            order.status == ORDER_STATUS_FILLED for order in strategy.buy.orders
        )

        if not fully_bought:
            if sell_realized_qty != sell_order_qty and sell_order_qty > 0:
                return State.PART_SOLD_PART_BOUGHT
            return State.PARTIALLY_BOUGHT

        # Fully bought cases
        if not sell_realized_qty:
            return State.BOUGHT

        if sell_order_qty and sell_realized_qty != sell_order_qty:
            return State.PARTIALLY_SOLD

        return State.SOLD

    async def _cancel_multihop_sell(
        self, strategy: HpStrategy, hp_id: str, base_hp_id: str
    ) -> None:
        """Cancel all positions in a multihop sell."""
        sell = strategy.sell
        logger.info(
            "Cancelling multihop sell with %d positions", len(sell.sell_positions)
        )

        # Cancel each position in the multihop sell
        for position in sell.sell_positions:
            original_current = sell.current_position
            sell.current_position = position

            await sell.cancel_position()

            PortfolioEventHelper.send_cancellation_event(
                strategy,
                position.config.hp_id,
                position.config.coin,
                position.sell_order.quantity,
                "SELL",
            )

            await self.db.upsert_sell_price_level(
                data=position, strategy_state=State.CLOSED
            )

            logger.info("Cancelled multihop sell position: %s", position.config.hp_id)

            sell.current_position = original_current

        # Close parent position and strategy
        strategy.state = State.CLOSED
        sell.original_position.state_info.state = State.CLOSED
        sell.original_position.state_info.ui_state = UiState.CLOSED

        await self.db.upsert_sell_price_level(
            data=sell.original_position, strategy_state=State.CLOSED
        )

        # Remove from active strategies
        if base_hp_id in self.strategies:
            del self.strategies[base_hp_id]

        logger.info("Successfully cancelled all multihop sell positions for: %s", hp_id)

    async def _handle_buy_config(self, strategy_data: HPBuy) -> None:
        """Handle incoming buy position configuration."""
        asyncio.create_task(self.setup_buy_position(new_hp=strategy_data))

    async def _handle_sell_config(self, strategy_data: HPSell) -> None:
        """Handle incoming sell position configuration."""
        sell_strategy = determine_sell_strategy(
            config=strategy_data.config, symbols=self.price_resolver.symbols
        )
        logger.info("Sell strategy determined: %s", sell_strategy)

        # Patch: Set symbol if convert-only or USDC
        if sell_strategy[0].is_convert_only or sell_strategy[0].name.endswith("USDC"):
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

    async def _persist_multihop_sell_positions(
        self, strategy: HpStrategy, strategy_state: State
    ) -> None:
        """Persist all multihop sell positions to database."""
        if len(strategy.sell.sell_positions) > 1:
            for position in strategy.sell.sell_positions:
                if position != strategy.sell.current_position:
                    logger.info(
                        "[MULTIHOP DEBUG] Saving additional position to DB: %s",
                        position.config.hp_id,
                    )
                    await self.db.upsert_sell_price_level(
                        data=position, strategy_state=strategy_state
                    )
