import asyncio
from typing import Dict
import uuid
from logging_config import StrategyLogger
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.spot import StrategyConfig
from src.trading_system.spot import TradingSystem


class StrategyExecutor:
    def __init__(
        self,
        client: BinanceClient,
        logger: StrategyLogger,
        gui_handler,
    ):
        self.client = client
        self.logger = logger
        self.gui_handler = gui_handler
        self.config_queue: asyncio.Queue = asyncio.Queue()
        self.id_to_system: Dict = {}  # Maps unique IDs to trading systems

    async def run(self) -> None:
        self.logger.info("Strategy executor ready to retrieve the first config")
        while True:
            config = await self.config_queue.get()
            self.logger.info("New config for strategy executor: %s", config)
            if config == "STOP":
                break

            if isinstance(config, str) and config.startswith("remove:"):
                await self.remove_record(config.split(":")[1])
            else:
                asyncio.create_task(self.initialize_trading_system(config))

    async def initialize_trading_system(self, config: StrategyConfig) -> None:
        trading_system = TradingSystem(
            client=self.client,
            gui_handler=self.gui_handler,
            strategy_logger=self.logger,
            config=config,
            system_id=config.system_id,
        )
        await trading_system.initialize()

        self.id_to_system[config.system_id] = trading_system
        self.logger.info("Starting trading system for %s", config)
        await trading_system.start_trading()

    async def remove_record(self, system_id: str) -> None:
        if system_id in self.id_to_system:
            trading_system: TradingSystem = self.id_to_system.pop(system_id)

            await trading_system.stop()
            self.logger.info(f"Removed trading system with {system_id}.")
