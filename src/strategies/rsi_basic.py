import asyncio
import numpy
import pandas
from logging_config import StrategyLogger
from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import (
    Signal,
    SignalUpdate,
    Event,
    EventName,
    BinanceClient,
    StrategyConfig,
)
from src.gui.gui_handler import GuiHandler
from src.strategies.base import BaseStrategy


class RsiBasic(BaseStrategy):
    def __init__(
        self,
        client: BinanceClient,
        df: pandas.DataFrame,
        balance: float,
        raw_data,
        logger: StrategyLogger,
        config: StrategyConfig,
        gui_handler: GuiHandler,
    ):
        super().__init__(
            client=client,
            df=df,
            balance=balance,
            raw_data=raw_data,
            config=config,
            gui_handler=gui_handler,
            logger=logger,
        )
        self.df = self.add_columns_for_rsi_basic(df=self.df)
        self.conditions += self.get_conditions_for_rsi_basic(df=self.df)
        self.df = self.signals_from_features_generate(
            df=self.df, conditions=self.conditions, signals=self.signals
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
        self.logger.info("Entering handle kline")

        expected_index = int(self.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.start_time)

        self.raw_data.append(list(self.kline_update))

        temp_df = insert_to_pandas(data=self.raw_data)
        temp_df = rsi_indicator_apply(df=temp_df)
        temp_df = self.add_columns_for_rsi_basic(df=temp_df)
        self.conditions = self.get_conditions_for_rsi_basic(df=temp_df)

        temp_df = self.signals_from_features_generate(
            df=temp_df, conditions=self.conditions, signals=self.signals
        )

        self.df = self.df.append(temp_df.tail(1))

        # Copy current position value
        self.df.iloc[-1, -1] = self.df.iloc[-2, -1]

        signal_update = SignalUpdate(
            signal=Signal.NULL
            if self.df.iloc[-1]["Signal"] == 0
            else self.df.iloc[-1]["Signal"],
            price=round(float(self.df.iloc[-1]["Close"]), 2),
        )

        await self.queue.put(Event(name=EventName.SIGNAL, content=signal_update))
        self.logger.info(
            "Added to queue, signal: %s, price: %s",
            signal_update.signal,
            signal_update.price,
        )
