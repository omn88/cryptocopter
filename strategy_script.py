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

    # Buy when RSI was lower than 30 and right now is above 30 for 2 consecutive candles or RSI crossed 20
    def get_buy_trigger(self):
        dfx = pd.DataFrame()
        for i in range(self.lags + 1):
            mask = self.df["RSI"].shift(i) < 30
            dfx = dfx.append(mask, ignore_index=True)

        return dfx.sum(axis=0)

    # Sell when RSI was above 70 and right now is below 70 for 2 consecutive candles or RSI crossed 80
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


def rsi_based_futures(
    symbol: str = "BTCUSDT", period=14, interval: str = "15m", lookback: int = "1440"
):

    df = indicators.get_historical_data(
        symbol=symbol, interval=interval, lookback=lookback
    )
    df = indicators.apply_rsi(df, period=period)

    rsi_signal = RsiSignal(df, lags=14)

    rsi_signal.decide()

    print(df.to_string())


rsi_based_futures()
