import asyncio
from typing import Dict, List, Optional
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.spot import State, StrategyConfig
from src.trading_system.spot import TradingSystem


class StrategyExecutor:
    def __init__(
        self,
        client: BinanceClient,
        logger: StrategyLogger,
        gui_handler: asyncio.Queue,
        db: Database,
    ):
        self.client = client
        self.logger = logger
        self.gui_handler = gui_handler
        self.db = db
        self.config_queue: asyncio.Queue = asyncio.Queue()
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

            if isinstance(config, List):
                assert isinstance(config[1], StrategyConfig)
                asyncio.create_task(
                    self.initialize_trading_system(
                        config=config[1],
                        db=self.db,
                        last_state=config[0],
                        stagnation_counter=config[2],
                        next_monitor_time=config[3],
                    )
                )

    async def initialize_trading_system(
        self,
        config: StrategyConfig,
        db: Database,
        last_state: Optional[State],
        stagnation_counter: int,
        next_monitor_time: str,
    ) -> None:
        trading_system = TradingSystem(
            client=self.client,
            gui_handler=self.gui_handler,
            strategy_logger=self.logger,
            config=config,
            system_id=config.system_id,
            db=db,
        )
        await trading_system.initialize_strategy(last_state=last_state)
        assert trading_system.strategy is not None
        trading_system.strategy.position_handler.stagnation_counter = stagnation_counter
        trading_system.strategy.position_handler.next_monitor_position_time = (
            next_monitor_time
        )

        self.id_to_system[config.system_id] = trading_system
        self.logger.debug("Starting trading system for %s", config)
        await trading_system.start_trading()

    async def remove_record(self, system_id: str) -> None:
        if system_id in self.id_to_system:
            trading_system: TradingSystem = self.id_to_system.pop(system_id)

            await trading_system.stop()
            self.logger.debug(f"Removed trading system with {system_id}.")
