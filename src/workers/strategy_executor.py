import asyncio
import uuid
from logging_config import StrategyLogger
from src.common.identifiers import BinanceClient
from src.trading_system import TradingSystemSpot


class StrategyExecutor:
    def __init__(self, client: BinanceClient, logger: StrategyLogger, gui_handler):
        self.client = client
        self.logger = logger
        self.gui_handler = gui_handler
        self.config_queue = asyncio.Queue()
        self.id_to_system = {}  # Maps unique IDs to trading systems

    async def run(self):
        self.logger.info("Strategy executor ready to retrieve the first config")
        while True:
            config = await self.config_queue.get()
            self.logger.info("New config for strategy executor: %s", config)
            if config == "STOP":
                break

            if isinstance(config, str) and config.startswith("remove:"):
                await self.remove_record(config.split(":")[1])
            else:
                await self.initialize_trading_system(config)

    async def initialize_trading_system(self, config):
        system_id = str(uuid.uuid4())  # Generate a unique identifier for the system
        trading_system = TradingSystemSpot(
            client=self.client,
            gui_handler=self.gui_handler,
            strategy_logger=self.logger,
            config=config,
        )
        await trading_system.initialize()
        self.id_to_system[system_id] = trading_system
        self.logger.info(
            "Starting trading system for %s with ID %s.",
            config,
            system_id,
        )
        await trading_system.start_trading()

    async def remove_record(self, system_id):
        if system_id in self.id_to_system:
            trading_system = self.id_to_system.pop(system_id)
            symbol = trading_system.config.symbol
            await trading_system.stop_trading()  # Ensure there's a method to cleanly stop trading
            self.logger.info(f"Removed trading system {system_id} for {symbol}.")
