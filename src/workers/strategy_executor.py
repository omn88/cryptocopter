import asyncio
import queue
from typing import Dict
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.spot import PositionSetup
from src.trading_system.spot import TradingSystem


class StrategyExecutor:
    def __init__(
        self,
        client: BinanceClient,
        logger: StrategyLogger,
        ui_queue: queue.Queue,
        db: Database,
        usdt_balance: float,
    ):
        self.client = client
        self.logger = logger
        self.ui_queue = ui_queue
        self.db = db
        self.usdt_balance = usdt_balance
        self.config_queue: queue.Queue = queue.Queue()
        self.id_to_system: Dict = {}  # Maps unique IDs to trading systems

    async def run(self) -> None:
        self.logger.info("Strategy executor ready to retrieve the first config")
        while True:
            config = await self.config_queue.get()
            self.logger.debug("New config for strategy executor: %s", config)
            if config == "STOP":
                break

            if isinstance(config, str) and config.startswith("remove:"):
                await self.remove_record(config.split(":")[1])

            if isinstance(config, PositionSetup):
                asyncio.create_task(
                    self.initialize_trading_system(
                        position_setup=config,
                        db=self.db,
                        usdt_balance=self.usdt_balance,
                    )
                )

    async def initialize_trading_system(
        self,
        position_setup: PositionSetup,
        db: Database,
        usdt_balance: float,
    ) -> None:
        self.logger.info("Initializing trading system: %s", position_setup.config)
        trading_system = TradingSystem(
            strategy_logger=self.logger,
            client=self.client,
            ui_queue=self.ui_queue,
            config=position_setup.config,
            db=db,
        )
        await trading_system.initialize_strategy(
            state_info=position_setup.state_info, usdt_balance=usdt_balance
        )
        assert trading_system.strategy is not None

        self.id_to_system[position_setup.config.system_id] = trading_system
        self.logger.info("Starting trading system for %s", position_setup.config)
        asyncio.create_task(trading_system.worker())

    async def remove_record(self, system_id: str) -> None:
        if system_id in self.id_to_system:
            trading_system: TradingSystem = self.id_to_system.pop(system_id)

            await trading_system.stop()
            self.logger.debug(f"Removed trading system with {system_id}.")
