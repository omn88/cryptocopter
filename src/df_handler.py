from typing import List, Union
import numpy

import btalib
import pandas
from logging_config import StrategyLogger
from src.common.common import signal_to_state
from src.common.identifiers import BinanceClient, Signal, State, StrategyConfig


class DfHandler:
    def __init__(
        self, client: BinanceClient, config: StrategyConfig, logger: StrategyLogger
    ):
        self.client = client
        self.config: StrategyConfig = config
        self.raw_data: List = []
        self.df: pandas.DataFrame = pandas.DataFrame()
        self.signals: List = [Signal.LONG, Signal.SHORT]
        self.conditions: List = []
        self.logger: StrategyLogger = logger

    async def initialize(self):
        self.raw_data = await self.get_futures_historical_data(
            symbol=self.config.symbol,
            interval=self.config.interval,
            lookback=self.config.lookback,
        )
        self.df = self.insert_to_pandas()
        self.df = self.rsi_indicator_apply(df=self.df)

    # STRATEGY SHOULD HAVE A DF HANDLER, RATHER THAN POSITION HANDLER
    async def get_futures_historical_data(
        self, interval: str, lookback: str, symbol: str
    ) -> List:
        historical_data = await self.client.futures_historical_klines(
            symbol, interval, lookback + "min ago UTC"
        )
        return historical_data[:-1]

    def insert_to_pandas(self) -> pandas.DataFrame:
        # ToDo: Below Timedelta must react to time change (winter/summer)
        pandas.Timedelta(hours=1)
        df = pandas.DataFrame(data=self.raw_data)
        df = df.iloc[:, :7]
        df.columns = ["Date", "Open", "High", "Low", "Close", "Volume", "OpenInterest"]
        df = df.set_index("Date")
        df.index = pandas.to_datetime(df.index, unit="ms") + numpy.timedelta64(1, "h")
        df = df.astype(float)
        return df

    @staticmethod
    def rsi_indicator_apply(df) -> pandas.DataFrame:
        rsi = btalib.rsi(df, period=14)
        df["RSI"] = rsi.df
        df.dropna(inplace=True)
        return df

    @staticmethod
    def signals_from_features_generate(df, conditions, signals) -> pandas.DataFrame:
        df["Signal"] = numpy.select(conditions, signals)
        df["Position"] = State.FLAT.value
        return df

    def update_position_in_df(self, update: Union[Signal, State]):
        self.df.at[self.df.index[-1], "Position"] = (
            signal_to_state(update) if isinstance(update, Signal) else update
        )

    def print_last_n_rows(self, rows: int = 5):
        self.logger.info(
            "Last %s rows from main df: %s", rows, self.df.tail(rows).to_string()
        )

    def log_signal_change(self):
        self.logger.info(
            "Position was %s, signal: %s, position now: %s",
            self.df.at[self.df.index[-2], "Position"],
        )
