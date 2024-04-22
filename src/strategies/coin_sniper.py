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
        balance: float,
    ):
        super().__init__(client, config, gui_handler, logger, df_handler, balance)

    async def handle_kline(self):
        pass
