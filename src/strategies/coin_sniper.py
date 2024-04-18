import asyncio
from logging_config import StrategyLogger
from src.common.identifiers import BinanceClient, StrategyConfig
from src.df_handler import DfHandler
from src.gui.gui_handler import GuiHandlerSpot
from src.strategies.base import BaseSpotStrategy


class CoinSniper(BaseSpotStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        gui_handler: GuiHandlerSpot,
        logger: StrategyLogger,
        df_handler: DfHandler,
    ):
        super().__init__(client, config, logger, df_handler)
        self.gui_handler: GuiHandlerSpot = gui_handler
        self.df_handler = df_handler
        self.queue: asyncio.Queue = asyncio.Queue()
