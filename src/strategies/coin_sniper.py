from logging_config import StrategyLogger
from src.common.identifiers import (
    BinanceClient,
    CoinSniperConfig,
    PositionSide,
    SignalUpdate,
)
from src.df_handler import DfHandler
from src.gui.gui_handler import GuiHandlerSpot
from src.strategies.base import BaseSpotStrategy


class CoinSniper(BaseSpotStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: CoinSniperConfig,
        gui_handler: GuiHandlerSpot,
        logger: StrategyLogger,
        df_handler: DfHandler,
        balance: float,
    ):
        super().__init__(client, config, gui_handler, logger, df_handler, balance)
        self.trigger_orders_price = (
            round(self.config.price_low * (1 - self.config.order_trigger_buffer), 2)
            if self.config.side == PositionSide.SHORT
            else round(
                self.config.price_high * (1 + self.config.order_trigger_buffer), 2
            )
        )

    async def handle_ticker(self, *args):
        if not self.position_handler.position.opened:
            if (
                self.config.side == PositionSide.LONG
                and self.ticker_update.last_price < self.trigger_orders_price
            ):
                await self.position_handler.open_position()

            if (
                self.config.side == PositionSide.SHORT
                and self.ticker_update.last_price > self.trigger_orders_price
            ):
                await self.position_handler.open_position()
        else:
            # To Close it if the target is not reached and the price is again far from threshold
            await self.monitor_position()
