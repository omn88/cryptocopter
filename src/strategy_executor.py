import asyncio
import logging
import os
import queue
import threading
from typing import Dict, List, Optional, Tuple
from decouple import Config, RepositoryEnv
from binance.enums import ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED
from logging_config import StrategyLogger
from src.common.common import generate_hp_id
from src.database import Database
from src.identifiers.common import BinanceClient, Mode, PositionSide
from src.identifiers.spot import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyPosition,
    HPSellPosition,
    Order,
    RemoveRecord,
    State,
    StateInfo,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import HPUpdate, PositionData
from src.position_handler import PositionHandler
from src.strategies.hp_manager import HpStrategy
from src.broker import BrokerSpot


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
        strategy_logger: StrategyLogger,
        db: Database,
        broker: BrokerSpot,
        symbols_info: Dict[str, SymbolInfo],
        ui_queue: queue.Queue,
        balances: Dict[str, float],
        test_mode: bool = False,
    ):
        self.client: Optional[BinanceClient] = None
        self.logger = strategy_logger
        self.db = db
        self.broker = broker
        self.ui_queue = ui_queue
        self.config_queue: queue.Queue = queue.Queue()
        self.strategies: Dict[str, HpStrategy] = {}
        self.symbols_info = symbols_info
        self.balances = balances
        self.test_mode = test_mode  # Add a test_mode parameter

        self.loop = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()

    def start_loop(self):
        """Starts the asyncio loop in a new thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self) -> None:
        self.logger.info("Strategy executor ready to retrieve the first config")
        if not self.test_mode:
            self.client = BinanceClient(
                api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
            )

        await self.initialize_positions_from_db()

        while not self.stop_event.is_set():
            try:
                strategy_data = self.config_queue.get_nowait()
                self.logger.info("New config for strategy executor: %s", strategy_data)
                if isinstance(strategy_data, HPBuyPosition):
                    asyncio.create_task(self.setup_buy_position(new_hp=strategy_data))
                if isinstance(strategy_data, HPSellPosition):
                    if not strategy_data.config.hp_id:
                        await self.setup_sell_position_with_new_hp(
                            strategy_data=strategy_data
                        )
                    else:
                        await self.setup_sell_position(strategy_data=strategy_data)

                if isinstance(strategy_data, RemoveRecord):
                    await self.remove_record(
                        hp_id=strategy_data.hp_id, side=strategy_data.side
                    )

            except queue.Empty:
                await asyncio.sleep(0.1)

    def stop(self):
        logger.info("Stopping strategy executor, stop event SET.")
        self.stop_event.set()

        if self.client:
            try:
                asyncio.run(
                    self.client.close_connection()
                )  # Ensure it's closed properly
            except RuntimeError:
                logger.warning("No running event loop, skipping async close.")

        logger.info("Client connection closed.")
        self.thread.join()
        logger.info("Strategy executor thread finished")

    async def setup_buy_position(
        self,
        new_hp: HPBuyPosition,
    ) -> None:
        self.logger.info("Setting up new position with config: %s", new_hp.config)

        new_hp.config.hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
        new_hp.state_info.generate_open_time()

        assert self.client is not None
        worker_queue: queue.Queue = queue.Queue()

        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            logger=self.logger,
            buy_config=new_hp.config,
            state_info=new_hp.state_info,
            balance=self.balances["USDC"],
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
        )

        strategy.buy.orders = strategy.buy.prepare_buy_orders(config=new_hp.config)
        strategy.buy.state_info.generate_open_time()

        self.strategies[new_hp.config.hp_id] = strategy

        assert new_hp.config.symbol_info.symbol.endswith(
            "USDC"
        ), "Symbol must end with 'USDC'"
        self.ui_queue.put_nowait(
            PositionData(
                config=new_hp.config,
                state_info=new_hp.state_info,
                hp_update=HPUpdate(
                    hp_id=new_hp.config.hp_id,
                    buy_price=new_hp.config.price_high,
                    asset=new_hp.config.symbol_info.symbol[:-4],
                    state=State.NEW,
                ),
            )
        )

        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=new_hp.config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=new_hp.config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

        self.db.upsert_price_level(
            position=HpPositionData(
                config=strategy.buy.config,
                state_info=strategy.buy.state_info,
            )
        )

        asyncio.create_task(strategy.worker())
        self.logger.info("System with ID %s initialized.", new_hp.config.hp_id)

    async def setup_sell_position(self, strategy_data: HPSellPosition) -> None:
        strategy: HpStrategy = self.strategies[strategy_data.config.hp_id]
        if strategy_data.state_info.state == State.NEW:
            self.logger.info("Sell price set: %s", strategy_data.config.sell_price)
            strategy.sell.config = strategy_data.config
            strategy.sell.state_info = strategy_data.state_info
            strategy.sell.orders = strategy.sell.prepare_sell_orders(
                config=strategy_data.config,
                buy_orders=strategy.buy.orders,
                sell_orders=strategy.sell.orders,
            )
        if strategy_data.state_info.state == State.CLOSED:
            self.logger.info("Closing sell position")
            if strategy.state == State.SELLING:
                await strategy.sell.cancel_position()

            strategy.sell.config.sell_price = strategy_data.config.sell_price
            strategy.sell.state_info.ui_state = UiState.CLOSED

        self.db.upsert_price_level(
            position=HpPositionData(
                config=strategy.sell.config,
                state_info=strategy.sell.state_info,
            )
        )
        self.ui_queue.put_nowait(
            PositionData(
                config=strategy.sell.config,
                state_info=strategy.sell.state_info,
                hp_update=HPUpdate(
                    hp_id=strategy.sell.config.hp_id,
                    sell_price=strategy.sell.config.price_low,
                    state=strategy.state,
                ),
            )
        )

    async def setup_sell_position_with_new_hp(
        self, strategy_data: HPSellPosition
    ) -> None:
        strategy: HpStrategy = self.strategies[strategy_data.config.hp_id]
        if strategy_data.state_info.state == State.NEW:
            self.logger.info("Sell price set: %s", strategy_data.config.sell_price)
            strategy.sell.config = strategy_data.config
            strategy.sell.state_info = strategy_data.state_info
            strategy.sell.orders = strategy.sell.prepare_sell_orders(
                config=strategy_data.config,
                buy_orders=strategy.buy.orders,
                sell_orders=strategy.sell.orders,
            )
        if strategy_data.state_info.state == State.CLOSED:
            self.logger.info("Closing sell position")
            if strategy.state == State.SELLING:
                await strategy.sell.cancel_position()

            strategy.sell.config.price_low = strategy_data.config.price_low
            strategy.sell.state_info.ui_state = UiState.CLOSED

        self.db.upsert_price_level(
            position=HPSellPosition(
                config=strategy.sell.config,
                state_info=strategy.sell.state_info,
            )
        )
        self.ui_queue.put_nowait(
            PositionData(
                config=strategy.sell.config,
                state_info=strategy.sell.state_info,
                hp_update=HPUpdate(
                    hp_id=strategy.sell.config.hp_id,
                    sell_price=strategy.sell.config.price_low,
                    state=strategy.state,
                ),
            )
        )

    async def close_sold_position(
        self,
        close_data: HpClose,
    ) -> None:
        hp_id = close_data.config.hp_id
        self.logger.info("Entered strategy %s removal!", hp_id)

        strategy = self.strategies[hp_id]
        strategy.stop_event.set()
        self.broker.unsubscribe(system_id=hp_id)
        self.logger.info("Removed strategy with %s.", hp_id)

    async def remove_record(self, hp_id: str, side: PositionSide) -> None:
        self.logger.info(
            "Entering remove record, id: %s to system: %s", hp_id, self.strategies
        )

        if hp_id not in self.strategies:
            self.logger.info("HP %s NOT in running strategies", hp_id)
            return

        strategy: HpStrategy = self.strategies[hp_id]
        self.logger.info(
            "Found strategy with hp id: %s, side to remove: %s", hp_id, side
        )
        buy = strategy.buy
        sell = strategy.sell

        if (
            side == PositionSide.LONG
            and sell.state_info.state == State.NEW
            and buy.state_info.state == State.NEW
        ):
            self.logger.info("Entered trading system removal!")
            self.broker.unsubscribe(system_id=hp_id)
            strategy.state = State.CLOSED
            buy.state_info.state = State.CLOSED
            if buy.orders:
                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.config.symbol_info.symbol,
                    orders=buy.orders,
                )
                for order in buy.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        self.db.upsert_order(
                            order=order,
                            position=HpPositionData(
                                config=buy.config, state_info=buy.state_info
                            ),
                        )
                buy.state_info.completeness = round(
                    sum(order.realized_quantity for order in buy.orders)
                    / sum(order.quantity for order in buy.orders),
                    2,
                )

            self.db.upsert_price_level(
                position=HpPositionData(config=buy.config, state_info=buy.state_info)
            )

            buy.state_info.ui_state = UiState.CLOSED

            self.ui_queue.put_nowait(
                PositionData(
                    config=buy.config,
                    state_info=buy.state_info,
                    hp_update=HPUpdate(hp_id=buy.config.hp_id, state=strategy.state),
                )
            )

            self.logger.info(f"Removed strategy {hp_id}.")
            return

        if side == PositionSide.LONG and buy.state_info.state == State.PARTIALLY_BOUGHT:
            if strategy.state == State.BUYING:
                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.config.symbol_info.symbol,
                    orders=buy.orders,
                )
                strategy.state = buy.state_info.state
                for order in buy.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        self.db.upsert_order(
                            order=order,
                            position=HpPositionData(
                                config=buy.config, state_info=buy.state_info
                            ),
                        )
            buy.state_info.state = State.CLOSED
            buy.state_info.ui_state = UiState.CLOSED
            buy.state_info.completeness = sum(
                order.realized_quantity for order in buy.orders
            ) / sum(order.quantity for order in buy.orders)
            self.ui_queue.put_nowait(
                PositionData(
                    config=buy.config,
                    state_info=buy.state_info,
                    hp_update=HPUpdate(hp_id=buy.config.hp_id, state=strategy.state),
                )
            )

            self.db.upsert_price_level(
                position=HpPositionData(config=buy.config, state_info=buy.state_info)
            )

        if side == PositionSide.SHORT:
            if strategy.state == State.SELLING:
                sell.orders = await sell.cancel_remaining_limit_orders(
                    symbol=sell.config.symbol_info.symbol,
                    orders=sell.orders,
                )
                # ToDo: Logic for determining state is to be added here, depending on the bp state and sp state
                # (shall we allow for changing the sell price if orders were at least touched? by not allowing we ease the implementation(Only one order for selling!)).
                strategy.state = buy.state_info.state
                for order in sell.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        self.db.upsert_order(
                            order=order,
                            position=HpPositionData(
                                config=sell.config, state_info=sell.state_info
                            ),
                        )
            sell.config.price_low = 0.0
            sell.state_info.ui_state = UiState.CLOSED
            sell.state_info.completeness = (
                sum(order.realized_quantity for order in sell.orders)
                / sum(order.quantity for order in sell.orders)
                if sell.orders
                else 0
            )
            self.ui_queue.put_nowait(
                PositionData(
                    config=sell.config,
                    state_info=sell.state_info,
                    hp_update=HPUpdate(
                        hp_id=sell.config.hp_id,
                        state=strategy.state,
                        sell_price=0.0,
                    ),
                )
            )
            self.db.upsert_price_level(
                position=HpPositionData(config=sell.config, state_info=sell.state_info)
            )

    def recover_price_levels(self, hp_id: str) -> Tuple[Dict, Optional[Dict]]:
        price_levels = self.db.fetch_price_levels_for_hp(hp_id=hp_id)
        logger.info("Current active price levels: %s", price_levels)

        buy_level = next(
            (pl for pl in price_levels if pl["side"] == PositionSide.LONG.value),
            None,
        )
        assert buy_level, f"Buy price level does not exist for active HP: {hp_id}"
        sell_level = next(
            (pl for pl in price_levels if pl["side"] == PositionSide.SHORT.value),
            None,
        )
        logger.info(
            "HP: %s\nBuy price level: %s\nSell price level: %s",
            hp_id,
            buy_level,
            sell_level,
        )
        return buy_level, sell_level

    def recover_broker_subscriptions(
        self, cfg: HPConfig, worker_queue: queue.Queue
    ) -> None:
        self.broker.subscribe(
            system_id=str(cfg.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=cfg.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id=str(cfg.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=cfg.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

    async def restore_buy_orders(
        self, buy_position: PositionHandler, worker_queue: queue.Queue
    ) -> List[Order]:
        assert self.client
        buy_config = buy_position.config
        # Restore orders for buy position
        orders = self.db.fetch_orders_for_price_level(
            hp_id=buy_config.hp_id, side=PositionSide.LONG.value
        )
        self.logger.info("Orders for HP: %s, %s", buy_config.hp_id, orders)
        if not orders:
            new_orders = buy_position.prepare_buy_orders(config=buy_config)
            self.logger.info(
                "No orders found in DB, prepared new: %s",
                new_orders,
            )
            return new_orders

        order_list: List[Order] = []
        order_list = [
            Order(
                order_id=order["order_id"],
                quantity=order["quantity"],
                precision=buy_config.symbol_info.precision,
                price_precision=buy_config.symbol_info.price_precision,
                price=order["price"],
                quantity_stable=order["quantity_stable"],
                realized_quantity=order["realized_quantity"],
                status=order["status"],
            )
            for order in orders
        ]
        self.logger.info("Buy orders restored from DB: %s.", order_list)

        # Confirm buy position state with the exchange
        for order in order_list:
            if order.status not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
                # Retrieve the latest order information from the API
                resp = await self.client.get_order(
                    symbol=buy_config.symbol_info.symbol,
                    orderId=order.order_id,
                )
                latest_status = resp["status"]
                latest_realized_quantity = float(resp["executedQty"])

                # Check if status or realized quantity has changed
                status_changed = latest_status != order.status
                quantity_changed = latest_realized_quantity != order.realized_quantity

                if status_changed or quantity_changed:
                    ex_report = ExecutionReport(
                        symbol=buy_config.symbol_info.symbol,
                        quantity=order.quantity,
                        price=order.price,
                        current_order_status=latest_status,
                        order_id=order.order_id,
                        cumulative_filled_quantity=latest_realized_quantity,
                    )
                    worker_queue.put_nowait(
                        Event(
                            name=EventName.EXECUTION_REPORT,
                            content=ex_report,
                        )
                    )
                    self.logger.info(
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    self.logger.info(
                        "No changes detected for order %s.", order.order_id
                    )

        return order_list

    async def restore_sell_orders(
        self, sell_config: HPConfig, worker_queue: queue.Queue
    ) -> List[Order]:
        assert self.client
        # Restore orders for sell position
        orders = self.db.fetch_orders_for_price_level(
            hp_id=sell_config.hp_id,
            side=PositionSide.SHORT.value,
        )
        if not orders:
            self.logger.info("No sell orders found in DB")
            return []

        order_list = [
            Order(
                order_id=order["order_id"],
                quantity=order["quantity"],
                precision=sell_config.symbol_info.precision,
                price_precision=sell_config.symbol_info.price_precision,
                price=order["price"],
                quantity_stable=order["quantity_stable"],
                realized_quantity=order["realized_quantity"],
                status=order["status"],
            )
            for order in orders
        ]
        self.logger.info("Sell orders restored from DB: %s.", order_list)

        for order in order_list:
            if order.status not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
                # Retrieve the latest order information from the API
                resp = await self.client.get_order(
                    symbol=sell_config.symbol_info.symbol,
                    orderId=order.order_id,
                )
                latest_status = resp["status"]
                latest_realized_quantity = float(resp["executedQty"])

                # Check if status or realized quantity has changed
                status_changed = latest_status != order.status
                quantity_changed = latest_realized_quantity != order.realized_quantity

                if status_changed or quantity_changed:
                    # Send a message to the appropriate queue

                    ex_report = ExecutionReport(
                        symbol=sell_config.symbol_info.symbol,
                        quantity=order.quantity,
                        price=order.price,
                        current_order_status=latest_status,
                        order_id=order.order_id,
                        cumulative_filled_quantity=latest_realized_quantity,
                    )
                    worker_queue.put_nowait(
                        Event(
                            name=EventName.EXECUTION_REPORT,
                            content=ex_report,
                        )
                    )
                    self.logger.info(
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    self.logger.info(
                        "No changes detected for order %s.", order.order_id
                    )
        return order_list

    def send_buy_position_data_to_ui(
        self, buy_position: PositionHandler, strategy_state: State
    ) -> None:
        # Send buy position data
        avg_realized_total = sum_realized_quant = 0.0

        for order in buy_position.orders:
            avg_realized_total += order.realized_quantity * order.price
            sum_realized_quant += order.realized_quantity

        buy_price = (
            buy_position.config.symbol_info.adjust_price(
                avg_realized_total / sum_realized_quant
            )
            if sum_realized_quant
            else 0
        )

        buy_pos_data = PositionData(
            config=buy_position.config,
            state_info=buy_position.state_info,
            hp_update=HPUpdate(
                hp_id=buy_position.config.hp_id,
                buy_price=buy_price,
                asset=buy_position.config.symbol_info.symbol[:-4],
                state=strategy_state,
            ),
        )
        buy_position.ui_queue.put_nowait(buy_pos_data)
        self.logger.info("Buy PositionData send to UI: %s.", buy_pos_data)

    async def initialize_positions_from_db(self) -> None:
        logger.info("Initialize positions from the database first")

        active_hps = self.db.fetch_active_hp_list()
        logger.info("Fetched list of active HPs: \n%s", active_hps)

        if not active_hps:
            logger.info("No active positions in the database.")

        for hp in active_hps:
            hp_id = hp["hp_id"]

            buy_level, sell_level = self.recover_price_levels(hp_id=hp_id)

            buy_config = HPConfig(
                symbol_info=self.symbols_info[buy_level["symbol"]],
                hp_id=buy_level["hp_id"],
                price_high=buy_level["price_high"],
                price_low=buy_level["price_low"],
                order_trigger=buy_level["order_trigger"],
                budget=buy_level["budget"],
                mode=Mode(buy_level["mode"]),
            )
            worker_queue: queue.Queue = queue.Queue()

            self.recover_broker_subscriptions(cfg=buy_config, worker_queue=worker_queue)

            # Initialize strategy
            assert self.client
            strategy = HpStrategy(
                client=self.client,
                ui_queue=self.ui_queue,
                logger=self.logger,
                buy_config=buy_config,
                state_info=StateInfo(
                    state=State(buy_level["state"]),
                    stagnation_counter=buy_level["stagnation_counter"],
                    open_time=buy_level["open_time"],
                ),
                balance=self.balances["USDC"],
                db=self.db,
                worker_queue=worker_queue,
                config_queue=self.config_queue,
            )
            self.strategies[buy_config.hp_id] = strategy

            self.logger.info("Entering strategy recovery.")

            strategy.state = State(hp["state"])

            strategy.buy.orders = await self.restore_buy_orders(
                buy_position=strategy.buy, worker_queue=worker_queue
            )
            strategy.buy.state_info.ui_state = (
                UiState.OPEN
                if strategy.state in [State.BUYING, State.SELLING]
                else UiState.CLOSED
                if strategy.state == State.BOUGHT
                else UiState.STAGNATED
            )
            strategy.buy.state_info.completeness = round(
                sum(order.realized_quantity for order in strategy.buy.orders)
                / sum(order.quantity for order in strategy.buy.orders),
                2,
            )
            strategy.buy.state_info.generate_next_monitor_time()
            self.send_buy_position_data_to_ui(
                buy_position=strategy.buy, strategy_state=strategy.state
            )

            if sell_level:
                strategy.sell.config = HPConfig(
                    symbol_info=self.symbols_info[sell_level["symbol"]],
                    hp_id=sell_level["hp_id"],
                    price_high=sell_level["price_high"],
                    price_low=sell_level["price_low"],
                    order_trigger=sell_level["order_trigger"],
                    budget=sell_level["budget"],
                    mode=Mode(sell_level["mode"]),
                )

                strategy.sell.state_info = StateInfo(
                    state=State(sell_level["state"]),
                    stagnation_counter=sell_level["stagnation_counter"],
                    open_time=sell_level["open_time"],
                    side=PositionSide(sell_level["side"]),
                )

                sell_config = strategy.sell.config
                strategy.sell.orders = await self.restore_sell_orders(
                    sell_config=sell_config, worker_queue=worker_queue
                )
                strategy.sell.state_info.generate_next_monitor_time()

                strategy.sell.state_info.ui_state = (
                    UiState.OPEN
                    if strategy.state in [State.BUYING, State.SELLING]
                    else UiState.STAGNATED
                )
                if strategy.sell.orders:
                    strategy.sell.state_info.completeness = round(
                        sum(order.realized_quantity for order in strategy.sell.orders)
                        / sum(order.quantity for order in strategy.sell.orders),
                        2,
                    )
                else:
                    strategy.sell.state_info.completeness = 0

                # Send sell position data
                sell_pos_data = PositionData(
                    config=sell_config,
                    state_info=strategy.sell.state_info,
                    hp_update=HPUpdate(
                        hp_id=sell_config.hp_id,
                        sell_price=sell_config.price_high,
                        asset=sell_config.symbol_info.symbol[:-4],
                        state=strategy.state,
                    ),
                )
                strategy.sell.ui_queue.put_nowait(sell_pos_data)
                self.logger.info("Sell PositionData send to UI: %s.", sell_pos_data)
            self.logger.info("Strategy position(s) restored")

            asyncio.create_task(strategy.worker())
            self.logger.info("HP %s restored.", buy_config.hp_id)
