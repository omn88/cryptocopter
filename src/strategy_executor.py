import asyncio
import logging
import os
import queue
import threading
from typing import Dict, List, Optional, Tuple
from decouple import Config, RepositoryEnv
from binance.enums import ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED
from src.common.common import generate_hp_id
from src.database import Database
from src.identifiers.common import BinanceClient, PositionSide
from src.identifiers.spot import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    Order,
    RemoveRecord,
    SellPosition,
    State,
    StateInfo,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import HPGuiDataBuy, HPGuiDataSell, HPUpdate
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell
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
        db: Database,
        broker: BrokerSpot,
        symbols_info: Dict[str, SymbolInfo],
        ui_queue: queue.Queue,
        balances: Dict[str, float],
        price_resolver: UsdPriceResolver,
        test_mode: bool = False,
    ):
        self.client: Optional[BinanceClient] = None
        self.db = db
        self.broker = broker
        self.ui_queue = ui_queue
        self.config_queue: queue.Queue = queue.Queue()
        self.strategies: Dict[str, HpStrategy] = {}
        self.symbols_info = symbols_info
        self.balances = balances
        self.supported_quotes = ["USDC", "PLN", "BTC", "BNB", "USDT"]
        self.test_mode = test_mode  # Add a test_mode parameter
        self.price_resolver = price_resolver

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
        logger.info("Strategy executor ready to retrieve the first config")
        if not self.test_mode:
            self.client = BinanceClient(
                api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
            )

        # await self.initialize_positions_from_db()

        while not self.stop_event.is_set():
            try:
                strategy_data = self.config_queue.get_nowait()
                logger.info("New config for strategy executor: %s", strategy_data)
                if isinstance(strategy_data, HPBuyData):
                    asyncio.create_task(self.setup_buy_position(new_hp=strategy_data))
                if isinstance(strategy_data, HPSellData):
                    sell_strategy = self.determine_sell_strategy(
                        config=strategy_data.config
                    )
                    logger.info("Sell strategy determined: %s", sell_strategy)
                    if sell_strategy[0].symbol.endswith("USDC"):
                        strategy_data.config.symbol_info = sell_strategy[0]
                    sell_position = SellPosition(
                        sell_order=Order(quantity=0),
                        config=strategy_data.config,
                        state_info=strategy_data.state_info,
                    )
                    if not strategy_data.config.hp_id:
                        await self.setup_sell_position_with_new_hp(
                            strategy_data=sell_position, sell_strategy=sell_strategy
                        )
                    else:
                        await self.setup_sell_position(
                            strategy_data=sell_position, sell_strategy=sell_strategy
                        )

                if isinstance(strategy_data, RemoveRecord):
                    await self.remove_record(
                        hp_id=strategy_data.hp_id, side=strategy_data.side
                    )

            except queue.Empty:
                await asyncio.sleep(0.1)

    def determine_sell_strategy(self, config: HPSellConfig) -> List[SymbolInfo]:
        delisted_coins = {
            "USDT",
            "FDUSD",
            "TUSD",
            "USDP",
            "DAI",
            "AEUR",
            "UST",
            "USTC",
            "PAXG",
        }

        strategy = []
        coin = config.coin
        end_currency = config.end_currency

        if end_currency == "PLN":
            # Priority 1: Direct pair to PLN
            if f"{coin}PLN" in self.symbols_info:
                strategy.append(self.symbols_info[f"{coin}PLN"])
                return strategy

            # Priority 2: coinUSDC + USDCPLN
            if f"{coin}USDC" in self.symbols_info and "USDCPLN" in self.symbols_info:
                strategy.append(self.symbols_info[f"{coin}USDC"])
                strategy.append(self.symbols_info["USDCPLN"])
                return strategy

            # Priority 3: coinBTC + BTCPLN
            if (
                coin not in delisted_coins
                and f"{coin}BTC" in self.symbols_info
                and "BTCPLN" in self.symbols_info
            ):
                strategy.append(self.symbols_info[f"{coin}BTC"])
                strategy.append(self.symbols_info["BTCPLN"])
                return strategy

            # Priority 4: coinBNB + BNBPLN
            if (
                coin not in delisted_coins
                and f"{coin}BNB" in self.symbols_info
                and "BNBPLN" in self.symbols_info
            ):
                strategy.append(self.symbols_info[f"{coin}BNB"])
                strategy.append(self.symbols_info["BNBPLN"])
                return strategy

            logger.warning(
                "No valid sell path to PLN for coin: %s, putting %sUSDT symbol info for conversion purpose.",
                coin,
                coin,
            )
            return [self.symbols_info[f"{coin}USDT"]]

        if end_currency == "USDC":
            # Priority 1: coinUSDC
            if f"{coin}USDC" in self.symbols_info:
                strategy.append(self.symbols_info[f"{coin}USDC"])
                return strategy

            # Priority 2: coinBTC + BTCUSDC
            if (
                coin not in delisted_coins
                and f"{coin}BTC" in self.symbols_info
                and "BTCUSDC" in self.symbols_info
            ):
                strategy.append(self.symbols_info[f"{coin}BTC"])
                strategy.append(self.symbols_info["BTCUSDC"])
                return strategy

            # Priority 3: Exotic coinXYZ + XYZUSDC
            if coin not in delisted_coins:
                for pair in self.symbols_info:
                    if pair.startswith(coin):
                        quote = pair.replace(coin, "")
                        if quote in delisted_coins:
                            continue
                        if f"{quote}USDC" in self.symbols_info:
                            strategy.append(self.symbols_info[pair])
                            strategy.append(self.symbols_info[f"{quote}USDC"])
                            return strategy

            logger.warning("No valid sell path to USDC for coin: %s", coin)
            logger.warning("Putting %sUSDT symbol info for conversion purpose.", coin)
            return [self.symbols_info[f"{coin}USDT"]]
        return []

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
        new_hp: HPBuyData,
    ) -> None:
        logger.info("Setting up new position with config: %s", new_hp.config)

        new_hp.config.hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
        new_hp.state_info.generate_open_time()

        assert self.client is not None
        worker_queue: queue.Queue = queue.Queue()

        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            balance=self.balances["USDC"],
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
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
                        symbol_info=new_hp.config.symbol_info,
                        coin=new_hp.config.coin,
                    ),
                    state_info=StateInfo(side=PositionSide.SHORT),
                    sell_order=Order(quantity=0.0),
                ),
                db=self.db,
                sell_strategy=[],
                price_resolver=self.price_resolver,
            ),
        )

        assert isinstance(strategy.buy.data.config, HPBuyConfig)

        strategy.buy.prepare_orders()
        strategy.buy.data.state_info.generate_open_time()

        self.strategies[new_hp.config.hp_id] = strategy

        assert new_hp.config.symbol_info.symbol.endswith(
            "USDC"
        ), "Symbol must end with 'USDC'"

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

        # self.db.upsert_buy_price_level(data=strategy.buy.data)

        asyncio.create_task(strategy.worker())
        logger.info("System with ID %s initialized.", new_hp.config.hp_id)

    def send_buy_position_to_ui(
        self,
        config: HPBuyConfig,
        state_info: StateInfo,
        state: State,
        buy_orders: List[Order],
    ):
        total_quant = sum(order.realized_quantity for order in buy_orders)
        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(config=config, state_info=state_info),
                hp_update=HPUpdate(
                    hp_id=config.hp_id,
                    coin=config.coin,
                    state=state,
                    buy_price=config.price_high,
                    quantity=float(total_quant) if total_quant else None,
                ),
            )
        )

    def send_sell_position_to_ui(
        self, config: HPSellConfig, state_info: StateInfo, state: State
    ):
        expected_return = None
        if config.buy_price is not None and config.sell_price is not None:
            expected_return = config.symbol_info.adjust_price(
                (config.sell_price - config.buy_price) * config.quantity
            )
        quantity_usd = config.symbol_info.adjust_price(
            config.quantity * config.buy_price
        )
        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(config=config, state_info=state_info),
                hp_update=HPUpdate(
                    hp_id=config.hp_id,
                    buy_price=config.buy_price,
                    sell_price=config.sell_price,
                    coin=config.coin,
                    state=state,
                    quantity=config.quantity,
                    quantity_usd=quantity_usd,
                    expected_return=expected_return,
                ),
            )
        )

    async def setup_sell_position(
        self, strategy_data: SellPosition, sell_strategy: List[SymbolInfo]
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
            )
            logger.info("New sell position: %s", strategy.sell)
            logger.info("Current position: %s", strategy.sell.current_position)
        if strategy_data.state_info.state == State.CLOSED:
            logger.info("Closing sell position")
            if strategy.state == State.SELLING:
                await strategy.sell.cancel_position()

            strategy.sell.current_position.config.sell_price = (
                strategy_data.config.sell_price
            )
            strategy.sell.current_position.state_info.ui_state = UiState.CLOSED

        # self.db.upsert_sell_price_level(data=strategy.sell.current_position)
        self.send_sell_position_to_ui(
            config=strategy.sell.current_position.config,
            state_info=strategy.sell.current_position.state_info,
            state=strategy.state,
        )
        logger.debug("Sell position setup exit")

    async def setup_sell_position_with_new_hp(
        self, strategy_data: SellPosition, sell_strategy: List[SymbolInfo]
    ) -> None:
        parent_hp_id = generate_hp_id(hp_list=list(self.strategies.keys()))
        strategy_data.config.hp_id = parent_hp_id
        logger.info(
            "Setting up NEW SELL position with config: %s", strategy_data.config
        )
        assert self.client is not None
        worker_queue: queue.Queue = queue.Queue()

        strategy = HpStrategy(
            client=self.client,
            ui_queue=self.ui_queue,
            buy_position=HPPositionBuy(
                client=self.client,
                data=HPBuyData(
                    config=HPBuyConfig(
                        hp_id=parent_hp_id,
                        symbol_info=strategy_data.config.symbol_info,
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
                ),
                db=self.db,
                sell_strategy=sell_strategy,
                price_resolver=self.price_resolver,
            ),
            balance=self.balances["USDC"],
            db=self.db,
            worker_queue=worker_queue,
            config_queue=self.config_queue,
            initial_state=State.BOUGHT,
        )
        config = strategy.sell.current_position.config
        strategy.sell.current_position.state_info.generate_open_time()

        logger.info("Current position: %s", strategy.sell.current_position)

        self.strategies[parent_hp_id] = strategy

        assert config.symbol_info.symbol.endswith(
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
                symbol=config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        for symbol_info in sell_strategy:
            self.broker.subscribe(
                system_id=str(parent_hp_id),
                subscription_info=SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol=symbol_info.symbol,
                    target=SubscriptionTarget.BACKEND,
                    queue=worker_queue,
                ),
            )

        # self.db.upsert_sell_price_level(data=strategy.sell.current_position)

        asyncio.create_task(strategy.worker())
        logger.info("System with ID %s initialized.", parent_hp_id)

    async def remove_record(self, hp_id: str, side: PositionSide) -> None:
        logger.info(
            "Entering remove record, id: %s to system: %s", hp_id, self.strategies
        )

        if hp_id not in self.strategies:
            logger.info("HP %s NOT in running strategies", hp_id)
            return

        strategy: HpStrategy = self.strategies[hp_id]
        logger.info("Found strategy with hp id: %s, side to remove: %s", hp_id, side)
        buy = strategy.buy
        sell = strategy.sell

        if (
            side == PositionSide.LONG
            and sell.current_position.state_info.state == State.NEW
            and buy.data.state_info.state == State.NEW
        ):
            logger.info("Entered trading system removal!")
            self.broker.unsubscribe(system_id=hp_id)
            strategy.state = State.CLOSED
            buy.data.state_info.state = State.CLOSED
            if buy.orders:
                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.data.config.symbol_info.symbol,
                    orders=buy.orders,
                )
                # for order in buy.orders:
                #     if order.status == ORDER_STATUS_CANCELED:
                #         self.db.upsert_order(
                #             order=order,
                #             hp_id=hp_id,
                #             side=side,
                #         )
                buy.data.state_info.completeness = round(
                    sum(order.realized_quantity for order in buy.orders)
                    / sum(order.quantity for order in buy.orders),
                    2,
                )

            # self.db.upsert_buy_price_level(data=buy.data)

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
                buy.orders = await buy.cancel_remaining_limit_orders(
                    symbol=buy.data.config.symbol_info.symbol,
                    orders=buy.orders,
                )
                strategy.state = buy.data.state_info.state
                # for order in buy.orders:
                #     if order.status == ORDER_STATUS_CANCELED:
                #         self.db.upsert_order(
                #             order=order, hp_id=buy.data.config.hp_id, side=side
                #         )
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

            # self.db.upsert_buy_price_level(data=buy.data)

        if side == PositionSide.SHORT:
            if strategy.state == State.SELLING:
                sell_rlzd_qty = (
                    strategy.sell.current_position.sell_order.realized_quantity
                )
                sell_order_qty = strategy.sell.current_position.sell_order.quantity
                fully_bought = all(
                    order.status == ORDER_STATUS_FILLED for order in strategy.buy.orders
                )
                await sell.cancel_remaining_order()
                strategy.state = (
                    State.PARTIALLY_BOUGHT
                    if not fully_bought
                    else State.BOUGHT
                    if fully_bought and not sell_rlzd_qty
                    else State.PARTIALLY_SOLD
                    if (
                        fully_bought
                        and sell_order_qty
                        and sell_rlzd_qty != sell_order_qty
                    )
                    else State.PART_SOLD_PART_BOUGHT
                    if (
                        not fully_bought
                        and sell_order_qty
                        and sell_rlzd_qty != sell_order_qty
                    )
                    else State.SOLD
                )

                # if sell.current_position.sell_order.status == ORDER_STATUS_CANCELED:
                #     self.db.upsert_order(
                #         order=sell.current_position.sell_order, hp_id=hp_id, side=side
                #     )
            sell.current_position.config.sell_price = 0.0
            sell.current_position.state_info.ui_state = UiState.CLOSED
            sell.current_position.state_info.completeness = round(
                sell.current_position.sell_order.realized_quantity
                / sell.current_position.sell_order.quantity,
                2,
            )
            self.send_sell_position_to_ui(
                config=strategy.sell.current_position.config,
                state_info=strategy.sell.current_position.state_info,
                state=strategy.state,
            )
            # self.db.upsert_sell_price_level(data=sell.current_position)

    def recover_price_levels(self, hp_id: str) -> Tuple[Dict, Dict]:
        buy_level, sell_level = self.db.fetch_price_levels_for_hp(hp_id=hp_id)
        logger.info(
            "HP: %s\nBuy price level: %s\nSell price level: %s",
            hp_id,
            buy_level,
            sell_level,
        )
        return buy_level, sell_level

    def recover_broker_subscriptions(
        self, symbol: str, hp_id: str, worker_queue: queue.Queue
    ) -> None:
        self.broker.subscribe(
            system_id=hp_id,
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id=hp_id,
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=symbol,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

    async def restore_buy_orders(
        self, buy_position: HPPositionBuy, worker_queue: queue.Queue
    ) -> List[Order]:
        assert self.client
        buy_config = buy_position.data.config
        # Restore orders for buy position
        orders = self.db.fetch_orders_for_price_level(
            hp_id=buy_config.hp_id, side=PositionSide.LONG.value
        )
        logger.info("Orders for HP: %s, %s", buy_config.hp_id, orders)
        if not orders:
            buy_position.prepare_orders()
            logger.info(
                "No orders found in DB, prepared new: %s",
                buy_position.orders,
            )
            return buy_position.orders

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
        logger.info("Buy orders restored from DB: %s.", order_list)

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
                    logger.info(
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    logger.info("No changes detected for order %s.", order.order_id)

        return order_list

    async def restore_sell_orders(
        self, sell_config: HPSellConfig, worker_queue: queue.Queue
    ) -> List[Order]:
        assert self.client
        # Restore orders for sell position
        orders = self.db.fetch_orders_for_price_level(
            hp_id=sell_config.hp_id,
            side=PositionSide.SHORT.value,
        )
        if not orders:
            logger.info("No sell orders found in DB")
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
        logger.info("Sell orders restored from DB: %s.", order_list)

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
                    logger.info(
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    logger.info("No changes detected for order %s.", order.order_id)
        return order_list

    def extract_coin_from_symbol(self, symbol: str) -> str:
        known_quote_currencies = ["BTC", "USDC", "PLN", "BNB", "USDT"]
        for quote in known_quote_currencies:
            if symbol.endswith(quote):
                return symbol[: -len(quote)]
        raise ValueError(f"Symbol '{symbol}' does not end with a known quote currency")

    # async def initialize_positions_from_db(self) -> None:
    #     logger.info("Initialize positions from the database first")

    #     active_hps = self.db.fetch_active_hp_list()
    #     logger.info("Fetched list of active HPs: \n%s", active_hps)

    #     if not active_hps:
    #         logger.info("No active positions in the database.")

    #     for hp in active_hps:
    #         hp_id = hp["hp_id"]

    #         buy_level, sell_level = self.recover_price_levels(hp_id=hp_id)

    #         buy_config = HPBuyConfig(
    #             coin=self.extract_coin_from_symbol(symbol=buy_level["symbol"]),
    #             symbol_info=self.symbols_info[buy_level["symbol"]],
    #             hp_id=buy_level["hp_id"],
    #             price_high=buy_level["price_high"],
    #             price_low=buy_level["price_low"],
    #             order_trigger=buy_level["order_trigger"],
    #             budget=buy_level["budget"],
    #             mode=Mode(buy_level["mode"]),
    #         )
    #         worker_queue: queue.Queue = queue.Queue()

    #         self.recover_broker_subscriptions(
    #             hp_id=buy_config.hp_id,
    #             symbol=buy_config.symbol_info.symbol,
    #             worker_queue=worker_queue,
    #         )

    #         # Initialize strategy
    #         assert self.client
    #         strategy = HpStrategy(
    #             client=self.client,
    #             ui_queue=self.ui_queue,
    #             logger=logger,
    #             buy_data=HPBuyData(
    #                 config=buy_config,
    #                 state_info=StateInfo(
    #                     state=State(buy_level["state"]),
    #                     stagnation_counter=buy_level["stagnation_counter"],
    #                     open_time=buy_level["open_time"],
    #                 ),
    #             ),
    #             balance=self.balances["USDC"],
    #             db=self.db,
    #             worker_queue=worker_queue,
    #             config_queue=self.config_queue,
    #             buy_position=HPPositionBuy(
    #             client=self.client,
    #             strategy_logger=logger,
    #             data=HPBuyData(
    #                 config=HPBuyConfig(
    #                     symbol_info=buy_config.symbol_info,
    #                     coin=buy_config.coin,
    #                 ),
    #                 state_info=StateInfo(ui_state=UiState.CLOSED, state=State.BOUGHT),
    #             ),
    #             db=self.db,
    #         ),

    #         proper sell config to be added here...
    #         sell_position=HPPositionSell(
    #             client=self.client,
    #             strategy_logger=logger,
    #             data=HPSellData(
    #                 config=HPSellConfig(
    #                     hp_id=strategy_data.config.hp_id,
    #                     symbol_info=strategy_data.config.symbol_info,
    #                     coin=strategy_data.config.coin,
    #                 ),
    #                 state_info=StateInfo(side=PositionSide.SHORT),
    #             ),
    #             db=self.db,
    #             sell_strategy=[]],
    #             price_resolver=self.price_resolver,
    #         ),
    #         )
    #         self.strategies[buy_config.hp_id] = strategy

    #         strategy.sell.sell_strategy = self.determine_sell_strategy(
    #             config=strategy.sell.original_position.config
    #         )

    #         logger.info("Entering strategy recovery.")

    #         strategy.state = State(hp["state"])

    #         strategy.buy.orders = await self.restore_buy_orders(
    #             buy_position=strategy.buy, worker_queue=worker_queue
    #         )
    #         strategy.buy.data.state_info.ui_state = (
    #             UiState.OPEN
    #             if strategy.state in [State.BUYING, State.SELLING]
    #             else UiState.CLOSED
    #             if strategy.state == State.BOUGHT
    #             else UiState.STAGNATED
    #         )
    #         strategy.buy.data.state_info.completeness = round(
    #             sum(order.realized_quantity for order in strategy.buy.orders)
    #             / sum(order.quantity for order in strategy.buy.orders),
    #             2,
    #         )
    #         strategy.buy.data.state_info.generate_next_monitor_time()
    #         self.send_buy_position_data_to_ui(
    #             buy_position=strategy.buy, strategy_state=strategy.state
    #         )

    #         if sell_level:
    #             strategy.sell.current_position.config = HPSellConfig(
    #                 symbol_info=self.symbols_info[sell_level["symbol"]],
    #                 hp_id=sell_level["hp_id"],
    #                 sell_price=sell_level["sell_price"],
    #                 buy_price=sell_level["buy_price"],
    #             )

    #             strategy.sell.current_position.state_info = StateInfo(
    #                 state=State(sell_level["state"]),
    #                 open_time=sell_level["open_time"],
    #                 side=PositionSide(sell_level["side"]),
    #             )

    #             sell_config = strategy.sell.current_position.config
    #             [
    #                 strategy.sell.current_position.sell_order
    #             ] = await self.restore_sell_orders(
    #                 sell_config=sell_config, worker_queue=worker_queue
    #             )
    #             strategy.sell.current_position.state_info.generate_next_monitor_time()

    #             strategy.sell.current_position.state_info.ui_state = (
    #                 UiState.OPEN
    #                 if strategy.state in [State.BUYING, State.SELLING]
    #                 else UiState.STAGNATED
    #             )
    #             if strategy.sell.current_position.sell_order:
    #                 strategy.sell.current_position.state_info.completeness = round(
    #                     strategy.sell.current_position.sell_order.realized_quantity
    #                     / strategy.sell.current_position.sell_order.quantity,
    #                     2,
    #                 )
    #             else:
    #                 strategy.sell.current_position.state_info.completeness = 0

    #             # Send sell position data
    #             sell_pos_data = HPGuiDataSell(
    #                 data=HPSellData(
    #                     sell_config,
    #                     state_info=strategy.sell.current_position.state_info,
    #                 ),
    #                 hp_update=HPUpdate(
    #                     hp_id=sell_config.hp_id,
    #                     sell_price=sell_config.sell_price,
    #                     coin=sell_config.symbol_info.symbol[:-4],
    #                     state=strategy.state,
    #                 ),
    #             )
    #             strategy.ui_queue.put_nowait(sell_pos_data)
    #             logger.info("Sell PositionData send to UI: %s.", sell_pos_data)
    #         logger.info("Strategy position(s) restored")

    #         asyncio.create_task(strategy.worker())
    #         logger.info("HP %s restored.", buy_config.hp_id)
