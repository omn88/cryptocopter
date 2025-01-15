import asyncio
import csv
from datetime import datetime
import logging
import os
import queue
import threading
from typing import Dict, List, Optional
from decouple import Config, RepositoryEnv
from binance.exceptions import BinanceAPIException, BinanceRequestException
from binance.enums import ORDER_STATUS_CANCELED
from logging_config import StrategyLogger
from src.common.common import generate_hp_id
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, Mode, PositionSide
from src.common.identifiers.spot import (
    HpClose,
    HpNew,
    CsvConfig,
    HPConfig,
    LoadConfig,
    RemoveRecord,
    SaveConfig,
    SellConfig,
    State,
    StateInfo,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import HPUpdate, PositionData
from src.trading_system.spot import TradingSystem
from src.workers.broker_spot import BrokerSpot


# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))


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
    ):
        self.client: Optional[BinanceClient] = None
        self.logger = strategy_logger
        self.db = db
        self.broker = broker
        self.ui_queue = ui_queue
        self.config_queue: queue.Queue = queue.Queue()
        self.id_to_system: Dict[str, TradingSystem] = {}
        self.symbols_info = symbols_info
        self.hp_configurations: List[HPConfig] = []
        self.balances = balances

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
        self.client = BinanceClient(
            api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
        )

        # self.initialize_hp_list()

        # self.initialize_positions_from_db()

        while not self.stop_event.is_set():
            try:
                strategy_data = self.config_queue.get_nowait()
                self.logger.info("New config for strategy executor: %s", strategy_data)
                if isinstance(strategy_data, HpNew):
                    asyncio.create_task(
                        self.initialize_trading_system(new_hp=strategy_data)
                    )
                if isinstance(strategy_data, SellConfig):
                    trading_system: TradingSystem = self.id_to_system[
                        strategy_data.config.hp_id
                    ]
                    assert trading_system.strategy
                    if strategy_data.config.price_low:
                        self.logger.info(
                            "Sell price set: %s", strategy_data.config.price_low
                        )
                        trading_system.strategy.sell_position.config = (
                            strategy_data.config
                        )
                        trading_system.strategy.sell_position.state_info = (
                            strategy_data.state_info
                        )
                        trading_system.strategy.sell_position.orders = trading_system.strategy.sell_position.order_handler.prepare_sell_orders(
                            config=strategy_data.config,
                            buy_orders=trading_system.strategy.buy_position.orders,
                            sell_orders=trading_system.strategy.sell_position.orders,
                        )
                    else:
                        self.logger.info(
                            "Sell price set to 0, so cancelling current position"
                        )
                        if trading_system.strategy.state == State.SELLING:
                            await trading_system.strategy.sell_position.cancel_position()

                        trading_system.strategy.sell_position.config.price_low = (
                            strategy_data.config.price_low
                        )
                        trading_system.strategy.sell_position.state_info.ui_state = (
                            UiState.CLOSED
                        )
                        trading_system.strategy.state = (
                            trading_system.strategy.buy_position.state_info.state
                        )

                    self.ui_queue.put_nowait(
                        PositionData(
                            config=trading_system.strategy.sell_position.config,
                            state_info=trading_system.strategy.sell_position.state_info,
                            hp_update=HPUpdate(
                                hp_id=trading_system.strategy.sell_position.config.hp_id,
                                sell_price=trading_system.strategy.sell_position.config.price_low,
                                state=trading_system.strategy.state,
                            ),
                        )
                    )

                if isinstance(strategy_data, RemoveRecord):
                    await self.remove_record(
                        hp_id=strategy_data.hp_id, side=strategy_data.side
                    )
                if isinstance(strategy_data, HpClose):
                    await self.terminate_trading_system(close_data=strategy_data)
                # if isinstance(strategy_data, SaveConfig):
                #     await self.save_config(strategy_data.file_name)
                # if isinstance(strategy_data, LoadConfig):
                #     await self.load_config(strategy_data.file_name)
            except queue.Empty:
                await asyncio.sleep(0.1)

    def stop(self):
        logger.info("In the strategy executor stop method")
        self.stop_event.set()
        loop = asyncio.get_running_loop()
        loop.create_task(self.client.close_connection())
        logger.info("Strategy executor stop event SET")
        self.thread.join()  # Wait for thread to finish
        logger.info("Strategy executor thread finished")

    async def initialize_trading_system(
        self,
        new_hp: HpNew,
    ) -> None:
        self.logger.info(
            "Initializing new trading system with config: %s", new_hp.config
        )

        self.hp_configurations.append(new_hp.config)
        new_hp.config.hp_id = generate_hp_id(hp_list=self.hp_configurations)
        new_hp.state_info.open_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        assert self.client is not None
        core_queue: queue.Queue = queue.Queue()

        trading_system = TradingSystem(
            strategy_logger=self.logger,
            client=self.client,
            ui_queue=self.ui_queue,
            core_queue=core_queue,
            config=new_hp.config,
            db=self.db,
            config_queue=self.config_queue,
        )
        await trading_system.initialize_strategy(
            config=new_hp.config,
            state_info=new_hp.state_info,
            usdt_balance=self.balances["USDT"],
        )
        assert trading_system.strategy is not None
        assert new_hp.config.hp_id, "HP ID is zero after strategy init"
        self.id_to_system[new_hp.config.hp_id] = trading_system

        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=new_hp.config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=core_queue,
            ),
        )
        self.broker.subscribe(
            system_id=str(new_hp.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=new_hp.config.symbol_info.symbol,
                target=SubscriptionTarget.BACKEND,
                queue=core_queue,
            ),
        )

        self.db.run_db_task(
            self.db.insert_buy_price_level(
                config=new_hp.config, state_info=new_hp.state_info
            )
        )

        asyncio.create_task(trading_system.worker())
        self.logger.info("System with ID %s initialized.", new_hp.config.hp_id)

    async def terminate_trading_system(
        self,
        close_data: HpClose,
    ) -> None:
        self.logger.info("Entered trading system removal!")
        hp_id = close_data.config.hp_id
        self.broker.unsubscribe(system_id=hp_id)
        self.logger.info(f"Removed trading system with {hp_id}.")

    async def remove_record(self, hp_id: str, side: str) -> None:
        self.logger.info("Entering remove record")
        if hp_id in self.id_to_system:
            trading_system: TradingSystem = self.id_to_system[hp_id]
            self.logger.info(
                "Found trading system with hp id: %s, side to remove: %s", hp_id, side
            )
            assert trading_system.strategy
            bp = trading_system.strategy.buy_position
            sp = trading_system.strategy.sell_position

            if (
                side == "BUY"
                and sp.state_info.state == State.NEW
                and bp.state_info.state == State.NEW
            ):
                self.logger.info("Entered trading system removal!")
                self.broker.unsubscribe(system_id=hp_id)
                trading_system.strategy.state = State.CLOSED
                bp.state_info.state = State.CLOSED
                bp.orders = await bp.order_handler.cancel_remaining_limit_orders(
                    symbol=bp.config.symbol_info.symbol,
                    orders=bp.orders,
                )
                for order in bp.orders:
                    if order.status == ORDER_STATUS_CANCELED:
                        self.db.run_db_task(
                            self.db.update_order(
                                price=order.price,
                                quantity=order.quantity,
                                quantity_stable=order.quantity_stable,
                                realized_quantity=order.realized_quantity,
                                time_in_force=order.time_in_force,
                                status=order.status,
                                order_type=order.order_type,
                                order_id=order.order_id,
                                hp_id=bp.config.hp_id,
                                side=bp.state_info.side,
                            )
                        )

                self.db.run_db_task(
                    self.db.update_price_level(
                        config=bp.config,
                        state_info=bp.state_info,
                    )
                )

                bp.state_info.ui_state = UiState.CLOSED
                bp.state_info.completeness = round(
                    sum(order.realized_quantity for order in bp.orders)
                    / sum(order.quantity for order in bp.orders),
                    2,
                )

                self.ui_queue.put_nowait(
                    PositionData(
                        config=bp.config,
                        state_info=bp.state_info,
                        hp_update=HPUpdate(
                            hp_id=bp.config.hp_id, state=trading_system.strategy.state
                        ),
                    )
                )

                self.logger.info(f"Removed trading system with {hp_id}.")
                return

            if side == "BUY" and bp.state_info.state == State.PARTIALLY_BOUGHT:
                if trading_system.strategy.state == State.BUYING:
                    bp.orders = await bp.order_handler.cancel_remaining_limit_orders(
                        symbol=bp.config.symbol_info.symbol,
                        orders=bp.orders,
                    )
                    trading_system.strategy.state = bp.state_info.state
                    for order in bp.orders:
                        if order.status == ORDER_STATUS_CANCELED:
                            self.db.run_db_task(
                                self.db.update_order(
                                    price=order.price,
                                    quantity=order.quantity,
                                    quantity_stable=order.quantity_stable,
                                    realized_quantity=order.realized_quantity,
                                    time_in_force=order.time_in_force,
                                    status=order.status,
                                    order_type=order.order_type,
                                    order_id=order.order_id,
                                    hp_id=str(bp.config.hp_id),
                                    side=bp.state_info.side,
                                )
                            )

                bp.state_info.ui_state = UiState.CLOSED
                bp.state_info.completeness = sum(
                    order.realized_quantity for order in bp.orders
                ) / sum(order.quantity for order in bp.orders)
                self.ui_queue.put_nowait(
                    PositionData(
                        config=bp.config,
                        state_info=bp.state_info,
                        hp_update=HPUpdate(
                            hp_id=bp.config.hp_id, state=trading_system.strategy.state
                        ),
                    )
                )
                self.db.run_db_task(
                    self.db.update_price_level(
                        config=bp.config,
                        state_info=bp.state_info,
                    )
                )

            if side == "SELL":
                if trading_system.strategy.state == State.SELLING:
                    sp.orders = await sp.order_handler.cancel_remaining_limit_orders(
                        symbol=sp.config.symbol_info.symbol,
                        orders=sp.orders,
                    )
                    trading_system.strategy.state = bp.state_info.state
                    for order in sp.orders:
                        if order.status == ORDER_STATUS_CANCELED:
                            self.db.run_db_task(
                                self.db.update_order(
                                    price=order.price,
                                    quantity=order.quantity,
                                    quantity_stable=order.quantity_stable,
                                    realized_quantity=order.realized_quantity,
                                    time_in_force=order.time_in_force,
                                    status=order.status,
                                    order_type=order.order_type,
                                    order_id=order.order_id,
                                    hp_id=sp.config.hp_id,
                                    side=sp.state_info.side,
                                )
                            )
                sp.config.price_low = 0.0
                sp.state_info.ui_state = UiState.CLOSED
                sp.state_info.completeness = (
                    sum(order.realized_quantity for order in sp.orders)
                    / sum(order.quantity for order in sp.orders)
                    if sp.orders
                    else 0
                )
                self.ui_queue.put_nowait(
                    PositionData(
                        config=sp.config,
                        state_info=sp.state_info,
                        hp_update=HPUpdate(
                            hp_id=bp.config.hp_id,
                            state=trading_system.strategy.state,
                            sell_price=0.0,
                        ),
                    )
                )
                self.db.run_db_task(
                    self.db.update_price_level(
                        config=sp.config,
                        state_info=sp.state_info,
                    )
                )

    def initialize_positions_from_db(self):
        active_price_levels = self.db.run_db_task(
            self.db.fetch_all_active_price_levels()
        )
        if not active_price_levels:
            logger.info("No active price levels found")
            return
        logger.info("Current active price levels: %s", active_price_levels)

        for price_level in active_price_levels:
            self.config_queue.put_nowait(
                HpNew(
                    config=HPConfig(
                        hp_id=price_level.get("hp_id"),
                        symbol_info=self.symbols_info[price_level["symbol"]],
                        price_low=float(price_level["price_low"]),
                        price_high=float(price_level["price_high"]),
                        budget=float(price_level["budget"]),
                        order_trigger=float(price_level["order_trigger"]),
                        mode=Mode.DCA
                        if price_level.get("mode") == Mode.DCA.value
                        else Mode.SINGLE,
                    ),
                    state_info=StateInfo(
                        state=State[price_level["state"]],
                        stagnation_counter=int(price_level["stagnation_counter"]),
                        next_monitor_time=price_level["next_monitor_time"],
                    ),
                )
            )

    # async def save_config(self, file_name: str) -> None:
    #     """Handle saving the current configuration to a CSV file."""
    #     config_dir = "src/strategies/spot"
    #     file_path = os.path.join(config_dir, f"{file_name}.csv")
    #     os.makedirs(config_dir, exist_ok=True)

    #     # Collect the current configuration
    #     config_data = self.get_current_configuration()

    #     self.logger.info(f"Saving configuration to {file_path}")
    #     with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
    #         writer = csv.writer(csvfile)
    #         writer.writerow(
    #             [
    #                 "Symbol",
    #                 "Side",
    #                 "Price Low",
    #                 "Price High",
    #                 "Budget",
    #                 "Order Trigger",
    #                 "Mode",
    #             ]
    #         )
    #         for config in config_data:
    #             writer.writerow(
    #                 [
    #                     config.symbol,
    #                     config.side,
    #                     config.price_low,
    #                     config.price_high,
    #                     config.budget,
    #                     config.order_trigger,
    #                     config.mode,
    #                 ]
    #             )
    #     self.logger.info("Configuration saved successfully.")

    # async def load_config(self, file_name: str) -> None:
    #     """Handle loading a configuration from a CSV file."""
    #     config_dir = "src/strategies/spot/"
    #     file_path = f"{config_dir}{file_name}.csv"

    #     try:
    #         with open(file_path, "r", encoding="utf-8") as csvfile:
    #             reader = csv.reader(csvfile)
    #             headers = next(reader)  # Skip the headers
    #             config_data = list(reader)
    #             for cd in config_data:
    #                 # Prepare the PositionSetup and put it in the queue
    #                 config = HPConfig(
    #                     symbol_info=self.symbols_info[cd[0]],
    #                     price_low=float(cd[2]),
    #                     price_high=float(cd[3]),
    #                     budget=float(cd[4]),
    #                     order_trigger=float(cd[5]),
    #                     mode=Mode.DCA if cd[6] == Mode.DCA.value else Mode.SINGLE,
    #                 )

    #                 self.config_queue.put_nowait(
    #                     HpNew(config=config, state_info=StateInfo())
    #                 )
    #                 # self.ui_queue.put_nowait(
    #                 #     PositionData(
    #                 #         config=config, state_info=state_info, completeness=0.0
    #                 #     )
    #                 # )
    #         self.logger.info(f"Loaded configuration from {file_path}")
    #     except FileNotFoundError:
    #         self.logger.error(f"File {file_name}.csv not found.")

    # def get_current_configuration(self) -> List[CsvConfig]:
    #     """Collect the current configurations."""
    #     hp_config = []
    #     for system_id, system in self.id_to_system.items():
    #         logger.info("System id: %s, system: %s", system_id, system)
    #         assert isinstance(system, TradingSystem)
    #         hp_config.append(
    #             CsvConfig(
    #                 symbol=system.config.symbol_info.symbol,
    #                 side=system.state_info.side.value,
    #                 price_low=system.config.price_low,
    #                 price_high=system.config.price_high,
    #                 budget=system.config.budget,
    #                 order_trigger=system.config.order_trigger,
    #                 mode=system.config.mode.value,
    #             )
    #         )
    #     return hp_config

    # def initialize_hp_list(self) -> None:
    #     """
    #     Initialize the HP list by fetching data from the database and populating the UI.
    #     """

    #     self.db.run_db_task(self.db.create_hp_list_table())

    #     # Fetch existing records from the database
    #     hp_list_from_db: List[Dict] = self.db.run_db_task(self.db.fetch_hp_list())
    #     if not hp_list_from_db:
    #         logger.info("Creating new list.")
    #         hp_list_raw: List[Dict] = get_hp_list()

    #         for item in hp_list_raw:
    #             hp_update = HPUpdate(
    #                 hp_id=generate_hp_id(hp_list=self.hp_configurations),
    #                 asset=item["Asset"],
    #                 buy_price=float(item["Price"]),
    #                 quantity=float(item["Quantity"]),
    #                 quantity_usdt=round(
    #                     float(item["Price"]) * float(item["Quantity"]), 2
    #                 ),
    #                 sell_price=0,
    #                 expected_return=0,
    #                 state=State.NEW,
    #             )
    #             self.hp_configurations.append(hp_update)
    #             self.db.run_db_task(self.db.insert_hp_list_record(hp_update))
    #     else:
    #         logger.info("Reading list from the DB.")
    #         for item in hp_list_from_db:
    #             self.hp_configurations.append(
    #                 HPUpdate(
    #                     hp_id=item["hp_id"],
    #                     asset=item["asset"],
    #                     buy_price=float(item["buy_price"]),
    #                     quantity=float(item["quantity"]),
    #                     quantity_usdt=float(item["quantity_usdt"]),
    #                     sell_price=0,
    #                     expected_return=0,
    #                     state=State.NEW,
    #                 )
    #             )

    #     if self.hp_list_data:
    #         self.logger.debug("HP list records found: %s", self.hp_list_data)
    #         for record in self.hp_list_data:
    #             self.ui_queue.put_nowait(record)
    #         self.logger.info("All HPs send to UI.")
    #     else:
    #         self.logger.info("No records found in the HP list table.")


def get_hp_list():
    return [
        {"Asset": "BTC", "Price": 64444.0, "Quantity": 0.427},
        {"Asset": "BTC", "Price": 67940.0, "Quantity": 0.072},
        {"Asset": "BTC", "Price": 55386.0, "Quantity": 0.03},
        {"Asset": "ETH", "Price": 3935.0, "Quantity": 2.7},
        {"Asset": "BNB", "Price": 325.0, "Quantity": 1.09},
        {"Asset": "USDT", "Price": 1.0, "Quantity": 2500.0},
        {"Asset": "PLN", "Price": 0.25, "Quantity": 0.0},
        {"Asset": "W", "Price": 0.694, "Quantity": 3256.0},
        {"Asset": "W", "Price": 0.572, "Quantity": 1748.0},
        {"Asset": "W", "Price": 0.498, "Quantity": 903.0},
        {"Asset": "W", "Price": 0.3051, "Quantity": 1210.0},
        {"Asset": "W", "Price": 0.2325, "Quantity": 2150.0},
        {"Asset": "PORTAL", "Price": 0.8187, "Quantity": 4885.7},
        {"Asset": "PORTAL", "Price": 0.9014, "Quantity": 1109.3},
        {"Asset": "PORTAL", "Price": 0.4058, "Quantity": 1400.0},
        {"Asset": "PORTAL", "Price": 0.2949, "Quantity": 1694.0},
        {"Asset": "XAI", "Price": 0.6355, "Quantity": 786.7},
        {"Asset": "XAI", "Price": 0.7231, "Quantity": 3137.0},
        {"Asset": "XAI", "Price": 0.3913, "Quantity": 2554.0},
        {"Asset": "XAI", "Price": 0.3388, "Quantity": 1121.0},
        {"Asset": "XAI", "Price": 0.192, "Quantity": 2470.0},
        {"Asset": "XAI", "Price": 0.1813, "Quantity": 540.0},
        {"Asset": "XAI", "Price": 0.202, "Quantity": 2466.0},
        {"Asset": "1000SATS", "Price": 0.0002552, "Quantity": 7829153.0},
        {"Asset": "1000SATS", "Price": 0.0002214, "Quantity": 4516711.0},
        {"Asset": "1000SATS", "Price": 0.0001534, "Quantity": 3434152.0},
        {"Asset": "LOKA", "Price": 0.261, "Quantity": 8892.3975},
        {"Asset": "LOKA", "Price": 0.178, "Quantity": 1303.0},
        {"Asset": "AEVO", "Price": 1.201, "Quantity": 1665.27},
        {"Asset": "AEVO", "Price": 1.244, "Quantity": 1607.71},
        {"Asset": "AEVO", "Price": 0.712, "Quantity": 2809.0},
        {"Asset": "AEVO", "Price": 0.434, "Quantity": 2604.0},
        {"Asset": "MAGIC", "Price": 0.6939, "Quantity": 3064.1},
        {"Asset": "MAGIC", "Price": 0.5195, "Quantity": 718.0},
        {"Asset": "JUP", "Price": 1.0401, "Quantity": 960.7},
        {"Asset": "JUP", "Price": 1.2163, "Quantity": 1231.0},
        {"Asset": "JUP", "Price": 0.7337, "Quantity": 846.0},
        {"Asset": "JUP", "Price": 0.803, "Quantity": 621.0},
        {"Asset": "HFT", "Price": 0.3019, "Quantity": 4086.0},
        {"Asset": "HFT", "Price": 0.3128, "Quantity": 4786.0},
        {"Asset": "HFT", "Price": 0.3131, "Quantity": 4786.0},
        {"Asset": "HFT", "Price": 0.3134, "Quantity": 7156.0},
        {"Asset": "HFT", "Price": 0.1965, "Quantity": 3300.0},
        {"Asset": "HFT", "Price": 0.155, "Quantity": 6440.0},
        {"Asset": "LQTY", "Price": 1.015, "Quantity": 492.6},
        {"Asset": "LQTY", "Price": 0.844, "Quantity": 960.0},
        {"Asset": "OMNI", "Price": 13.88, "Quantity": 72.0},
        {"Asset": "OMNI", "Price": 12.96, "Quantity": 38.55},
        {"Asset": "OMNI", "Price": 6.66, "Quantity": 30.0},
        {"Asset": "NTRN", "Price": 0.647, "Quantity": 1157.0},
        {"Asset": "NTRN", "Price": 0.4013, "Quantity": 1157.0},
        {"Asset": "KDA", "Price": 0.851, "Quantity": 2857.0},
        {"Asset": "KDA", "Price": 0.51, "Quantity": 1960.0},
        {"Asset": "DYM", "Price": 1.977, "Quantity": 505.3},
        {"Asset": "DYM", "Price": 1.4, "Quantity": 714.0},
        {"Asset": "DYM", "Price": 1.38, "Quantity": 84.0},
        {"Asset": "MANTA", "Price": 1.008, "Quantity": 992.0},
        {"Asset": "MANTA", "Price": 0.881, "Quantity": 844.0},
        {"Asset": "PYTH", "Price": 0.335, "Quantity": 3669.0},
        {"Asset": "PYTH", "Price": 0.2627, "Quantity": 950.0},
        {"Asset": "APE", "Price": 0.981, "Quantity": 1251.0},
        {"Asset": "APE", "Price": 0.767, "Quantity": 944.0},
        {"Asset": "AXL", "Price": 0.5842, "Quantity": 3157.0},
        {"Asset": "AXL", "Price": 0.4625, "Quantity": 569.0},
        {"Asset": "BLUR", "Price": 0.2104, "Quantity": 8771.0},
        {"Asset": "BLUR", "Price": 0.1343, "Quantity": 1861.0},
        {"Asset": "ENA", "Price": 0.564, "Quantity": 2180.0},
        {"Asset": "ENA", "Price": 0.41, "Quantity": 1100.0},
        {"Asset": "ENA", "Price": 0.248, "Quantity": 2016.0},
        {"Asset": "ENA", "Price": 0.214, "Quantity": 210.0},
        {"Asset": "STRK", "Price": 0.639, "Quantity": 1564.0},
        {"Asset": "STRK", "Price": 0.375, "Quantity": 668.0},
        {"Asset": "STRK", "Price": 0.341, "Quantity": 588.0},
        {"Asset": "ACE", "Price": 2.292, "Quantity": 271.0},
        {"Asset": "ACE", "Price": 2.17, "Quantity": 114.0},
        {"Asset": "SAGA", "Price": 0.9205, "Quantity": 606.0},
        {"Asset": "SAGA", "Price": 0.995, "Quantity": 250.0},
        {"Asset": "SAGA", "Price": 1.2, "Quantity": 233.0},
        {"Asset": "FIDA", "Price": 0.2373, "Quantity": 4214.0},
        {"Asset": "FIDA", "Price": 0.206, "Quantity": 1628.0},
        {"Asset": "BB", "Price": 0.3819, "Quantity": 3272.0},
        {"Asset": "BB", "Price": 0.29, "Quantity": 859.0},
        {"Asset": "BB", "Price": 0.26, "Quantity": 1680.0},
        {"Asset": "WIF", "Price": 1.374, "Quantity": 397.0},
        {"Asset": "AI", "Price": 0.433, "Quantity": 2308.0},
        {"Asset": "AI", "Price": 0.375, "Quantity": 2666.0},
        {"Asset": "BSW", "Price": 0.0499, "Quantity": 20040.0},
        {"Asset": "DODO", "Price": 0.1096, "Quantity": 4562.0},
        {"Asset": "ETHFI", "Price": 1.419, "Quantity": 704.0},
        {"Asset": "ETHFI", "Price": 1.32, "Quantity": 90.0},
        {"Asset": "ID", "Price": 0.3686, "Quantity": 1356.0},
        {"Asset": "HBAR", "Price": 0.0522, "Quantity": 9578.0},
        {"Asset": "AERGO", "Price": 0.0981, "Quantity": 5096.0},
        {"Asset": "EDU", "Price": 0.633, "Quantity": 789.0},
        {"Asset": "MINA", "Price": 0.4687, "Quantity": 2127.0},
        {"Asset": "RARE", "Price": 0.1327, "Quantity": 7524.0},
        {"Asset": "SYN", "Price": 0.4725, "Quantity": 2132.0},
        {"Asset": "CRV", "Price": 0.3106, "Quantity": 6428.0},
    ]
