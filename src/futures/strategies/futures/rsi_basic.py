import logging
import numpy
from src.identifiers.common import BinanceClient
from src.identifiers.futures import (
    Event,
    EventName,
    Signal,
    SignalUpdate,
)
from src.identifiers.futures import StrategyConfig
from src.futures.df_handler.futures import DfHandler
from src.gui.gui_handler.futures import GuiHandler
from src.futures.strategies.futures.base import BaseFuturesStrategy

import logging

logger = logging.getLogger("base")


class RsiBasic(BaseFuturesStrategy):
    def __init__(
        self,
        client: BinanceClient,
        balance: float,
        config: StrategyConfig,
        gui_handler: GuiHandler,
        df_handler: DfHandler,
    ):
        super().__init__(
            client=client,
            balance=balance,
            config=config,
            gui_handler=gui_handler,
            df_handler=df_handler,
        )
        self.df_handler.df = self.add_columns_for_rsi_basic(df=self.df_handler.df)
        self.df_handler.conditions += self.get_conditions_for_rsi_basic(
            df=self.df_handler.df
        )
        self.df_handler.df = self.df_handler.signals_from_features_generate(
            df=self.df_handler.df,
            conditions=self.df_handler.conditions,
            signals=self.df_handler.signals,
        )

    @staticmethod
    def add_columns_for_rsi_basic(df):
        df["RsiBelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
        df["RsiAboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)
        return df

    @staticmethod
    def get_conditions_for_rsi_basic(df):
        return [
            (df.RsiBelowThirty.diff() == 0) & (df.RsiBelowThirty.diff(periods=2) == -1),
            (df.RsiAboveSeventy.diff() == 0)
            & (df.RsiAboveSeventy.diff(periods=2) == -1),
        ]

    async def handle_kline(self, *args, **kwargs):
        logger.info("Entering handle kline")

        expected_index = int(self.df_handler.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.start_time)

        self.df_handler.raw_data.append(list(self.kline_update))

        temp_df = self.df_handler.insert_to_pandas()
        temp_df = self.df_handler.rsi_indicator_apply(df=temp_df)
        temp_df = self.add_columns_for_rsi_basic(df=temp_df)
        self.df_handler.conditions = self.get_conditions_for_rsi_basic(df=temp_df)

        temp_df = self.df_handler.signals_from_features_generate(
            df=temp_df,
            conditions=self.df_handler.conditions,
            signals=self.df_handler.signals,
        )

        self.df_handler.df = self.df_handler.df.append(temp_df.tail(1))

        # Copy current position value
        self.df_handler.df.iloc[-1, -1] = self.df_handler.df.iloc[-2, -1]

        signal_update = SignalUpdate(
            signal=Signal.NULL
            if self.df_handler.df.iloc[-1]["Signal"] == 0
            else self.df_handler.df.iloc[-1]["Signal"],
            price=round(float(self.df_handler.df.iloc[-1]["Close"]), 2),
        )

        await self.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
        logger.info(
            "Added to queue, signal: %s, price: %s",
            signal_update.signal,
            signal_update.price,
        )
