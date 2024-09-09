import asyncio
import logging
import queue
import threading
from typing import Dict, List, Optional
import uuid
from decouple import Config, RepositoryEnv
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, Mode, PositionSide
from src.common.identifiers.spot import PositionSetup, State, StateInfo, StrategyConfig
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
        logger: StrategyLogger,
        db: Database,
        broker: BrokerSpot,
        usdt_balance: float,
        symbols_info: Dict[str, SymbolInfo],
    ):
        self.client: Optional[BinanceClient] = None
        self.logger = logger
        self.db = db
        self.broker = broker
        self.usdt_balance = usdt_balance
        self.ui_queue: queue.Queue = queue.Queue()
        self.config_queue: queue.Queue = queue.Queue()
        self.id_to_system: Dict = {}
        self.symbols_info = symbols_info

        self.loop = None
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

        while True:
            try:
                strategy_data = self.config_queue.get_nowait()
                self.logger.info("New config for strategy executor: %s", strategy_data)
                if isinstance(strategy_data, PositionSetup):
                    asyncio.create_task(
                        self.initialize_trading_system(
                            position_setup=strategy_data, db=self.db
                        )
                    )
            except queue.Empty:
                await asyncio.sleep(0.1)

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
        self.logger.info("Starting trading system for %s", position_setup.config)

        self.broker.subscribe(
            strategy=trading_system.strategy,
            data_type="USER",
            symbol=position_setup.config.symbol_info.symbol,
            core_queue=core_queue,
        )
        self.broker.subscribe(
            strategy=trading_system.strategy,
            data_type="PRICE",
            symbol=position_setup.config.symbol_info.symbol,
            core_queue=core_queue,
        )

        asyncio.create_task(trading_system.worker())

    async def remove_record(self, system_id: str, symbol: str) -> None:
        if system_id in self.id_to_system:
            trading_system: TradingSystem = self.id_to_system.pop(system_id)

            self.broker.unsubscribe(
                strategy=trading_system.strategy,
                data_type="USER",
                symbol=symbol,
            )
            self.broker.unsubscribe(
                strategy=trading_system.strategy,
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
            await self.db.insert_price_level(
                config=position_setup.config, state=last_state
            )

    async def initialize_position_from_db(self):
        active_price_levels = await self.db.fetch_all_active_price_levels()
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
