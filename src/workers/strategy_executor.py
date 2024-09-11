import asyncio
import csv
import logging
import os
import queue
import threading
from typing import Dict, List, Optional
import uuid
from decouple import Config, RepositoryEnv
from binance.exceptions import BinanceAPIException, BinanceRequestException
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, Mode, PositionSide
from src.common.identifiers.spot import (
    CsvConfig,
    LoadConfig,
    PositionSetup,
    RemoveRecord,
    SaveConfig,
    State,
    StateInfo,
    StrategyConfig,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
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
    ):
        self.client: Optional[BinanceClient] = None
        self.logger = strategy_logger
        self.db = db
        self.broker = broker
        self.ui_queue = ui_queue
        self.config_queue: queue.Queue = queue.Queue()
        self.id_to_system: Dict = {}
        self.symbols_info = symbols_info
        self.usdt_balance = 0.0

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
        self.usdt_balance = await self.get_usdt_balance()

        while not self.stop_event.is_set():
            try:
                strategy_data = self.config_queue.get_nowait()
                self.logger.info("New config for strategy executor: %s", strategy_data)
                if isinstance(strategy_data, PositionSetup):
                    asyncio.create_task(
                        self.initialize_trading_system(
                            position_setup=strategy_data, db=self.db
                        )
                    )
                if isinstance(strategy_data, RemoveRecord):
                    asyncio.create_task(
                        self.remove_record(
                            system_id=strategy_data.system_id,
                            symbol=strategy_data.symbol,
                        )
                    )
                if isinstance(strategy_data, SaveConfig):
                    await self.save_config(strategy_data.file_name)
                if isinstance(strategy_data, LoadConfig):
                    await self.load_config(strategy_data.file_name)
            except queue.Empty:
                await asyncio.sleep(0.1)

    def stop(self):
        self.stop_event.set()
        self.thread.join()  # Wait for thread to finish

    async def initialize_trading_system(
        self,
        position_setup: PositionSetup,
        db: Database,
    ) -> None:
        self.logger.info("Initializing trading system: %s", position_setup.config)
        assert self.client is not None
        core_queue: queue.Queue = queue.Queue()
        trading_system = TradingSystem(
            strategy_logger=self.logger,
            client=self.client,
            ui_queue=self.ui_queue,
            core_queue=core_queue,
            config=position_setup.config,
            db=db,
        )
        await trading_system.initialize_strategy(
            state_info=position_setup.state_info, usdt_balance=self.usdt_balance
        )
        assert trading_system.strategy is not None

        self.id_to_system[position_setup.config.system_id] = trading_system

        self.broker.subscribe(
            system_id=trading_system.strategy.config.system_id,
            data_type="USER",
            symbol=position_setup.config.symbol_info.symbol,
            queue_to_use=core_queue,
        )
        self.broker.subscribe(
            system_id=trading_system.strategy.config.system_id,
            data_type="PRICE",
            symbol=position_setup.config.symbol_info.symbol,
            queue_to_use=core_queue,
        )

        self.broker.subscribe(
            system_id=trading_system.strategy.config.system_id,
            data_type="PRICE",
            symbol=position_setup.config.symbol_info.symbol,
            queue_to_use=self.ui_queue,
        )

        asyncio.create_task(trading_system.worker())

    async def remove_record(self, system_id: str, symbol: str) -> None:
        if system_id in self.id_to_system:
            trading_system: TradingSystem = self.id_to_system.pop(system_id)

            self.broker.unsubscribe(
                system_id=system_id,
                data_type="USER",
                symbol=symbol,
            )
            self.broker.unsubscribe(
                system_id=system_id,
                data_type="PRICE",
                symbol=symbol,
            )

            await trading_system.stop()
            self.logger.debug(f"Removed trading system with {system_id}.")

    async def add_record(
        self,
        symbol: str,
        side: PositionSide,
        price_low: float,
        price_high: float,
        budget: float,
        order_trigger: float,
        mode: Mode,
        stagnation_counter: int = 0,
        next_monitor_time: str = "",
        open_time: Optional[str] = None,
        last_state: Optional[State] = None,
        system_id: Optional[str] = None,
    ) -> None:
        position_setup = PositionSetup(
            config=StrategyConfig(
                open_time=open_time,
                system_id=str(uuid.uuid4()) if system_id is None else system_id,
                symbol_info=self.symbols_info[symbol],
                side=side,
                price_low=price_low,
                price_high=price_high,
                budget=budget,
                order_trigger=order_trigger,
                mode=mode,
            ),
            state_info=StateInfo(
                last_state=last_state,
                stagnation_counter=stagnation_counter,
                next_monitor_time=next_monitor_time,
            ),
        )

        self.config_queue.put(position_setup)
        logger.info(
            "Adding new record with config: %s, state info: %s",
            position_setup.config,
            position_setup.state_info,
        )

        if (
            last_state is None
        ):  # inserting level only if there is no last known status, recovery will
            last_state = State.NEW
            self.ui_queue.put(
                PositionData(
                    config=position_setup.config,
                    stagnation_counter=0,
                    completeness=0,
                    state=last_state,
                )
            )
            self.db.run_db_task(
                self.db.insert_price_level(
                    config=position_setup.config, state=last_state
                )
            )

    async def initialize_position_from_db(self):
        active_price_levels = self.db.run_db_task(
            self.db.fetch_all_active_price_levels()
        )
        if not active_price_levels:
            logger.info("No active price levels found")
            return
        logger.info("Current active price levels: %s", active_price_levels)

        for price_level in active_price_levels:
            self.config_queue.put(
                PositionSetup(
                    config=StrategyConfig(
                        open_time=price_level.get("open_time"),
                        system_id=price_level.get("price_level_id"),
                        symbol_info=self.symbols_info[price_level["symbol"]],
                        side=PositionSide.LONG
                        if price_level["side"] == PositionSide.LONG.value
                        else PositionSide.SHORT,
                        price_low=float(price_level["price_low"]),
                        price_high=float(price_level["price_high"]),
                        budget=float(price_level["budget"]),
                        order_trigger=float(price_level["order_trigger"]),
                        mode=Mode.DCA
                        if price_level.get("mode") == Mode.DCA.value
                        else Mode.SINGLE,
                    ),
                    state_info=StateInfo(
                        last_state=State[price_level["state"]],
                        stagnation_counter=int(price_level["stagnation_counter"]),
                        next_monitor_time=price_level["next_monitor_time"],
                    ),
                )
            )

    async def save_config(self, file_name: str) -> None:
        """Handle saving the current configuration to a CSV file."""
        config_dir = "src/strategies/spot"
        file_path = os.path.join(config_dir, f"{file_name}.csv")
        os.makedirs(config_dir, exist_ok=True)

        # Collect the current configuration
        config_data = self.get_current_configuration()

        self.logger.info(f"Saving configuration to {file_path}")
        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "Symbol",
                    "Side",
                    "Price Low",
                    "Price High",
                    "Budget",
                    "Order Trigger",
                    "Mode",
                ]
            )
            for config in config_data:
                writer.writerow(
                    [
                        config.symbol,
                        config.side,
                        config.price_low,
                        config.price_high,
                        config.budget,
                        config.order_trigger,
                        config.mode,
                    ]
                )
        self.logger.info("Configuration saved successfully.")

    async def load_config(self, file_name: str) -> None:
        """Handle loading a configuration from a CSV file."""
        config_dir = "src/strategies/spot"
        file_path = os.path.join(config_dir, f"{file_name}.csv")

        try:
            with open(file_path, "r", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                headers = next(reader)  # Skip the headers
                config_data = list(reader)
                for cd in config_data:
                    # Prepare the PositionSetup and put it in the queue
                    self.config_queue.put(
                        PositionSetup(
                            config=StrategyConfig(
                                symbol_info=SymbolInfo(symbol=cd[0]),
                                side=PositionSide.LONG
                                if cd[1] == PositionSide.LONG.value
                                else PositionSide.SHORT,
                                price_low=float(cd[2]),
                                price_high=float(cd[3]),
                                budget=float(cd[4]),
                                order_trigger=float(cd[5]),
                                mode=Mode.DCA
                                if cd[6] == Mode.DCA.value
                                else Mode.SINGLE,
                            ),
                            state_info=StateInfo(
                                last_state=State.NEW,
                                stagnation_counter=0,
                                next_monitor_time="",
                            ),
                        )
                    )
            self.logger.info(f"Loaded configuration from {file_path}")
        except FileNotFoundError:
            self.logger.error(f"File {file_name}.csv not found.")

    def get_current_configuration(self) -> List[CsvConfig]:
        """Collect the current configurations."""
        hp_config = []
        for system_id, system in self.id_to_system.items():
            assert isinstance(system, TradingSystem)
            hp_config.append(
                CsvConfig(
                    symbol=system.config.symbol_info.symbol,
                    side=system.config.side.value,
                    price_low=system.config.price_low,
                    price_high=system.config.price_high,
                    budget=system.config.budget,
                    order_trigger=system.config.order_trigger,
                    mode=system.config.mode.value,
                )
            )
        return hp_config

    async def get_usdt_balance(self) -> float:
        """
        Retrieve the USDT balance from the spot market.

        :return: The balance of USDT in the account.
        :raises: BinanceAPIException, BinanceRequestException
        """
        try:
            assert self.client is not None
            account_info = await self.client.get_account()
            for asset in account_info["balances"]:
                if asset["asset"] == "USDT":
                    return float(asset["free"])
            return 0.0
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error("Failed to retrieve USDT balance: %s", e)
            raise e
