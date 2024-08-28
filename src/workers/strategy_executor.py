import asyncio
import queue
import threading
from typing import Dict
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.spot import PositionSetup
from src.trading_system.spot import TradingSystem
from src.workers.broker_spot import BrokerSpot


class StrategyExecutor:
    def __init__(
        self,
        client: BinanceClient,
        logger: StrategyLogger,
        ui_queue: queue.Queue,
        db: Database,
        broker: BrokerSpot,
        usdt_balance: float,
    ):
        self.client = client
        self.logger = logger
        self.ui_queue = ui_queue
        self.db = db
        self.broker = broker
        self.usdt_balance = usdt_balance
        self.config_queue: queue.Queue = queue.Queue()
        self.id_to_system: Dict = {}  # Maps unique IDs to trading systems

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
        while True:
            try:
                # This blocks until there's something in the queue
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
