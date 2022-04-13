import asyncio
import enum
import indicators
import pandas as pd
import numpy as np


class Status(enum.Enum):
    PREPARED: enum.auto()
    NEW: enum.auto()
    LONG: enum.auto()
    SHORT: enum.auto()
    LONG_FULL: enum.auto()
    SHORT_FULL: enum.auto()
    SHORT_FILLED: enum.auto()
    LONG_FILLED: enum.auto()
    CANCELLED: enum.auto()


class Strategy:
    def __init__(self, client, bm):
        self.client = client
        self.bm = bm
        self.status: Status = Status.PREPARED


class RsiSignal(indicators.Signal):
    def get_buy_trigger(self):
        dfx = pd.DataFrame()
        for i in range(self.lags + 1):
            mask = self.df["RSI"].shift(i) < 30
            dfx = dfx.append(mask, ignore_index=True)

        return dfx.sum(axis=0)

    def get_sell_trigger(self):
        dfx = pd.DataFrame()
        for i in range(self.lags + 1):
            mask = self.df["RSI"].shift(i) > 70
            dfx = dfx.append(mask, ignore_index=True)

        return dfx.sum(axis=0)

    def decide(self):
        # self.df["trigger"] = np.where(self.get_buy_trigger(), 1, 0)
        self.df["Buy"] = np.where(self.get_buy_trigger(), 1, 0)
        self.df["Sell"] = np.where(self.get_sell_trigger(), 1, 0)


async def rsi_based_futures(period, interval: str):

    df = indicators.get_historical_data(
        symbol="BTCUSDT", interval=interval, lookback="1440"
    )
    df = indicators.apply_rsi(df, period=period)

    rsi_signal = RsiSignal(df, lags=14)

    rsi_signal.decide()

    print(df.to_string())
    #
    # while True:
    #     if
