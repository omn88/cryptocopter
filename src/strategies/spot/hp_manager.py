
from typing import Dict
from logging_config import StrategyLogger
from src.common.identifiers.spot import StrategyConfig
from src.common.identifiers.common import BinanceClient, Order
from src.df_handler.futures import DfHandler
from src.gui.gui_handler.spot import GuiHandler
from src.common.database import Database  # Import the Database class
from src.strategies.spot.base import BaseSpotStrategy  # Import your base class


class HpManager(BaseSpotStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        gui_handler: GuiHandler,
        logger: StrategyLogger,
        df_handler: DfHandler,
        balance: float,
        db: Database,  # Add database parameter
    ):
        super().__init__(client, config, gui_handler, logger, df_handler, balance)
        self.db = db  # Initialize database
        self.hp_list = []  # List to manage buy/sell areas

    async def initialize(self):
        await super().initialize()
        await self.load_hps_from_db()

    async def load_hps_from_db(self):
        # Load price levels from the database and initialize the areas list
        price_levels = await self.db.fetch_price_levels(self.config.system_id)
        for level in price_levels:
            self.hp_list.append(level)
        self.logger.info("Loaded price levels from database: %s", self.hp_list)

    # async def open_long(self, *args, **kwargs) -> None:
    #     await super().open_long(*args, **kwargs)
    #     # Additional logic for managing buy areas
    #     await self.save_price_levels_to_db()

    # async def open_short(self, *args, **kwargs) -> None:
    #     await super().open_short(*args, **kwargs)
    #     # Additional logic for managing sell areas
    # #     await self.save_price_levels_to_db()

    # async def save_price_levels_to_db(self):
    #     for area in self.hp_list:
    #         await self.db.create_price_level(StrategyConfig(**area))

    async def add_record(self, area: Dict):
        self.hp_list.append(area)
        await self.db.create_price_level(config=config)
        self.logger.info("Added new area: %s", area)

    async def create_order(self, strategy_id: int, price_level_id: int, order: Order):
        await self.db.create_order(strategy_id, price_level_id, order)
        self.logger.info("Created order: %s", order)
