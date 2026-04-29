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
from src.common.helpers import generate_hp_id
from src.strategies.hp_manager.sell_strategies.factory import SellStrategyFactory
from src.database import Database
from src.common.client import BinanceClient
from src.common.identifiers import (
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
from src.portfolio.portfolio_event_helper import PortfolioEventHelper

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


logger = logging.getLogger(__name__)


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
                    strategy.portfolio_event_helper.handle_sell_completion(close_data)
                else:
                    sell_quantity = strategy.sell.current_position.sell_order.quantity
                    strategy.portfolio_event_helper.handle_sell_cancellation(
                        close_data, sell_quantity
                    )
            # Handle buy position cancellation
            elif hasattr(strategy, "buy") and strategy.buy.buy_order:
                remaining_budget = strategy.get_remaining_quantity_buy()
                strategy.portfolio_event_helper.handle_buy_cancellation(
                    close_data, strategy.state, remaining_budget
                )
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
        if self.client is None:
            raise RuntimeError("BinanceClient not initialized")

        # Create temporary portfolio event helper (will be updated after strategy creation)
        portfolio_event_helper = PortfolioEventHelper(None)

        logger.info("Creating HpStrategy for HP %s", new_hp.config.hp_id)
        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            balance=self.inventory_manager["USDC"]["total_quantity"],
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
            portfolio_ui_queue=self.portfolio_ui_queue,
            portfolio_event_helper=portfolio_event_helper,
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
                sell_strategy=None,  # No strategy for buy-only positions
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=worker_queue,
            ),
        )

        if not isinstance(strategy.buy.data.config, HPBuyConfig):
            raise TypeError(
                f"Expected HPBuyConfig, got {type(strategy.buy.data.config).__name__}"
            )
        logger.info("HpStrategy created successfully for HP %s", new_hp.config.hp_id)

        # Update portfolio event helper with the strategy's callback
        if self.portfolio_ui_queue is not None:
            portfolio_event_helper._callback = strategy.send_hp_event_to_portfolio

        # Create new orders for normal setup
        strategy.buy.prepare_order()
        strategy.buy.data.state_info.generate_open_time()

        self.strategies[new_hp.config.hp_id] = strategy

        self.send_buy_position_to_ui(
            config=new_hp.config,
            state_info=new_hp.state_info,
            state=strategy.state,
            buy_orders=[strategy.buy.buy_order] if strategy.buy.buy_order else [],
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

        strategy.portfolio_event_helper.send_buy_creation_event(
            hp_id=str(new_hp.config.hp_id),
            coin=new_hp.config.coin,
            budget=new_hp.config.budget,
            buy_price=new_hp.config.buy_price,
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
        # Calculate expected quantity from budget and buy price
        expected_qty = 0.0
        if config.budget > 0 and config.buy_price > 0:
            expected_qty = config.budget / config.buy_price

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuy(config=config, state_info=state_info),
                hp_update=HPUpdate(
                    hp_id=config.hp_id,
                    coin=config.coin,
                    symbol=config.symbol,
                    state=state,
                    buy_price=config.buy_price,
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
                buy_price = strategy.buy.data.config.buy_price
                logger.info(
                    "Using buy config buy_price %s instead of sell config buy_price %s",
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
        self, strategy_data: SellPosition, sell_strategy  # BaseSellStrategy object
    ) -> None:
        logger.info(
            "Setting up sell position for existing HP: %s", strategy_data.config.hp_id
        )
        strategy: HpStrategy = self.strategies[strategy_data.config.hp_id]
        if not self.client:
            raise RuntimeError("BinanceClient not initialized")
        if strategy_data.state_info.state == State.NEW:
            strategy.sell = HPPositionSell(
                client=self.client,
                original_position=SellPosition(
                    config=strategy_data.config,
                    state_info=strategy_data.state_info,
                    sell_order=Order(quantity=strategy_data.config.quantity),
                ),
                db=self.db,
                sell_strategy=sell_strategy,  # Now BaseSellStrategy object
                price_resolver=self.price_resolver,
                broker=self.broker,
                worker_queue=strategy.worker_queue,
            )
            logger.info(
                "Current position in standard setup sell: %s",
                strategy.sell.current_position,
            )

            strategy.portfolio_event_helper.send_sell_creation_event(
                hp_id=strategy_data.config.hp_id,
                coin=strategy_data.config.coin,
                quantity=strategy_data.config.quantity,
                buy_price=strategy_data.config.buy_price,
                sell_price=strategy_data.config.sell_price,
                end_currency=strategy_data.config.end_currency,
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
        sell_strategy,  # BaseSellStrategy object
    ) -> None:
        # For restoration, preserve existing HP ID; for new positions, generate new one
        parent_hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
        strategy_data.config.hp_id = parent_hp_id
        logger.info("[EXECUTOR] === Setting up NEW SELL position ===")
        logger.info("[EXECUTOR] HP ID: %s", parent_hp_id)
        logger.info("[EXECUTOR] Coin: %s", strategy_data.config.coin)
        logger.info("[EXECUTOR] Symbol: %s", strategy_data.config.symbol.name)
        logger.info("[EXECUTOR] Quantity: %.8f", strategy_data.config.quantity)
        logger.info("[EXECUTOR] Sell price: %.8f", strategy_data.config.sell_price)
        logger.info("[EXECUTOR] Strategy type: %s", type(sell_strategy).__name__)

        if self.client is None:
            raise RuntimeError("BinanceClient not initialized")
        if self.recovery_service is None:
            raise RuntimeError("RecoveryService not initialized")
        worker_queue: queue.Queue = queue.Queue()

        # Create temporary portfolio event helper (will be updated after strategy creation)
        portfolio_event_helper = PortfolioEventHelper(None)

        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            portfolio_event_helper=portfolio_event_helper,
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
                    # sell_type will be set by strategy.build_positions()
                ),
                db=self.db,
                sell_strategy=sell_strategy,  # Now BaseSellStrategy object
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

        # Update portfolio event helper with the strategy's callback
        if self.portfolio_ui_queue is not None:
            portfolio_event_helper._callback = strategy.send_hp_event_to_portfolio

        logger.info("Current position: %s", strategy.sell.current_position)

        self.strategies[parent_hp_id] = strategy

        if not config.symbol.name.endswith(tuple(self.supported_quotes)):
            raise ValueError(
                f"Symbol '{config.symbol.name}' must end with one of {self.supported_quotes}"
            )
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
            [s.name for s in sell_strategy.sell_path[1:]]
            if len(sell_strategy.sell_path) > 1
            else None
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

        strategy.portfolio_event_helper.send_sell_creation_event(
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

            # Send cancellation event if order was sent to exchange
            if buy.buy_order and strategy.state != State.NEW:
                budget_amount = strategy.get_remaining_quantity_buy()
                strategy.portfolio_event_helper.send_cancellation_event(
                    hp_id, "USDC", budget_amount, "BUY"
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
                strategy.portfolio_event_helper.send_cancellation_event(
                    hp_id, "USDC", budget_amount, "BUY"
                )

                # Cancel the buy order
                await buy.cancel_position()
                strategy.state = buy.data.state_info.state

                if buy.buy_order and buy.buy_order.status == ORDER_STATUS_CANCELED:
                    await self.db.upsert_order(
                        order=buy.buy_order, hp_id=buy.data.config.hp_id, side=side
                    )

            if buy.buy_order:
                buy.data.state_info.completeness = (
                    buy.buy_order.realized_quantity / buy.buy_order.quantity
                )

            await self._close_buy_position(strategy, hp_id, side, cancel_orders=False)

        # Handle removal of BOUGHT positions
        if side == PositionSide.LONG and buy.data.state_info.state == State.BOUGHT:
            logger.info("Cancelling fully bought position: %s", hp_id)

            budget_amount = strategy.get_remaining_quantity_buy()
            strategy.portfolio_event_helper.send_cancellation_event(
                hp_id, "USDC", budget_amount, "BUY"
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
                    # Single sell position cancellation - cancel exchange order first
                    await sell.cancel_remaining_order()

                    strategy.portfolio_event_helper.send_cancellation_event(
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

            strategy.portfolio_event_helper.send_cancellation_event(
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
                strategy.portfolio_event_helper.send_sell_completion_event(
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
            if self.recovery_service is None:
                raise RuntimeError("RecoveryService not initialized")
            if self.client is None:
                raise RuntimeError("BinanceClient not initialized")

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
                    buy_orders=(
                        [strategy.buy.buy_order] if strategy.buy.buy_order else []
                    ),
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

        if cancel_orders and buy.buy_order:
            # Cancel the buy order
            await buy.cancel_position()
            if buy.buy_order and buy.buy_order.status == ORDER_STATUS_CANCELED:
                await self.db.upsert_order(order=buy.buy_order, hp_id=hp_id, side=side)
            if buy.buy_order:
                buy.data.state_info.get_completeness(buy.buy_order)

        buy.data.state_info.state = State.CLOSED
        buy.data.state_info.ui_state = UiState.CLOSED

        await self.db.upsert_buy_price_level(data=buy.data)

        self.send_buy_position_to_ui(
            config=buy.data.config,
            state_info=buy.data.state_info,
            state=strategy.state,
            buy_orders=[buy.buy_order] if buy.buy_order else [],
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
        fully_bought = (
            strategy.buy.buy_order
            and strategy.buy.buy_order.status == ORDER_STATUS_FILLED
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

            strategy.portfolio_event_helper.send_cancellation_event(
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

        # Send parent position update to UI
        self.send_sell_position_to_ui(
            config=sell.original_position.config,
            state_info=sell.original_position.state_info,
            state=State.CLOSED,
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
        # Create sell position first (needed for SellStrategyFactory)
        sell_position = SellPosition(
            sell_order=Order(quantity=0),
            config=strategy_data.config,
            state_info=strategy_data.state_info,
        )

        # Determine sell strategy and create strategy object
        sell_strategy = SellStrategyFactory.create_from_config(
            config=strategy_data.config,
            symbols=self.price_resolver.symbols,
            original_position=sell_position,
            price_resolver=self.price_resolver,
        )
        logger.info("Sell strategy determined: %s", sell_strategy.__class__.__name__)

        # Patch: Set symbol from strategy's sell path
        first_symbol = sell_strategy.sell_path[0]
        if first_symbol.is_convert_only or first_symbol.name.endswith("USDC"):
            strategy_data.config.symbol = first_symbol

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
