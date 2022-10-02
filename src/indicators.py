import time
import logging
import btalib as ta
import numpy as np
import lib


def apply_rsi(df, period):
    rsi = ta.rsi(df, period=period)
    df["RSI"] = rsi.df

    return df


def apply_macd(df):
    macd = ta.macd(df)

    df["MACD"] = macd.macd
    df["Signal"] = macd.signal
    df["Histogram"] = macd.histogram

    return df


def rsi_based_futures(
    symbol: str = "BTCUSDT", period=14, interval: str = "15m", lookback: str = "6720"
):

    df = lib.get_historical_data(symbol=symbol, interval=interval, lookback=lookback)
    df = apply_rsi(df=df, period=period)
    # df = apply_macd(df=df)

    long_position = False
    short_position = False
    df.dropna(inplace=True)

    df["RSIbelowThirty"] = np.where(df["RSI"] < 30, 1, 0)

    df["RSIaboveSeventy"] = np.where(df["RSI"] > 70, 1, 0)

    df["RSIBuy"] = np.where(df.RSIbelowThirty.diff() == 0, 1, 0) & np.where(
        df.RSIbelowThirty.diff(periods=2) == -1, 1, 0
    )

    df["RSISell"] = np.where(df.RSIaboveSeventy.diff() == 0, 1, 0) & np.where(
        df.RSIaboveSeventy.diff(periods=2) == -1, 1, 0
    )

    df["RSIaboveEighty"] = np.where(df["RSI"] > 80, 1, 0)

    df["RSISellEighty"] = np.where(df.RSIaboveEighty.diff() == -1, 1, 0)

    df["RSIbelowTwenty"] = np.where(df["RSI"] < 20, 1, 0)

    df["RSIBuyTwenty"] = np.where(df.RSIbelowTwenty.diff() == -1, 1, 0)

    if df.RSIBuy.iloc[-1] and not [long_position, short_position]:
        buy_price = df.Close.iloc[-1]
        margin = 0.96 * buy_price
        logging.info(f"Zajebales panie order kupna po cenie {buy_price}")
        long_position = True

    if df.RSIBuy.iloc[-1] and not [long_position, short_position]:
        sell_price = df.Close.iloc[-1]
        margin = 1.04 * sell_price
        logging.info(f"Zajebales panie order sprzedazy po cenie {sell_price}")
        short_position = True

    while long_position:
        time.sleep(15)
        df = lib.get_historical_data(symbol=symbol, interval=interval, lookback=1)
        logging.info(f"Current close {df.Close.iloc[-1]}")
        logging.info(f"Current margin {margin}")
        logging.info(f"Target RSI reached? {df.RSISell.iloc[-1]}")

        if df.Close.iloc[-1] < margin:
            print(f"Wyjebalo cie z butow przy cenie {df.Close.iloc[-1]}")
            break

        if df.RSISellEighty.iloc[-1]:
            sell_price = df.Close.iloc[-1]
            logging.info(f"Sprzedales panie po cenie {sell_price}")
            break

        if df.RSISell.iloc[-1]:
            sell_price = df.Close.iloc[-1]
            logging.info(f"Sprzedales panie po cenie {sell_price}")
            break

    while short_position:
        time.sleep(15)
        df = lib.get_historical_data(symbol=symbol, interval=interval, lookback=1)
        logging.info(f"Current close {df.Close.iloc[-1]}")
        logging.info(f"Current margin {margin}")
        logging.info(f"Target RSI reached? {df.RSIBuy.iloc[-1]}")

        if df.Close.iloc[-1] > margin:
            print(f"Wyjebalo cie z butow przy cenie {df.Close.iloc[-1]}")
            break

        if df.RSIBuyTwenty.iloc[-1]:
            buy_price = df.Close.iloc[-1]
            logging.info(f"Odkupiles panie po cenie {buy_price}")
            break

        if df.RSISell.iloc[-1]:
            buy_price = df.Close.iloc[-1]
            logging.info(f"Odkupiles panie po cenie {buy_price}")
            break

    # df['RSIBelow20Buy'] = np.where(df.RSIbelowTwenty.diff() == 1, 1, 0) & np.where(df.InPosition.diff() == 0, 1, 0)

    # rsi_signal = RsiSignal(df, lags=14)
    #
    # rsi_signal.decide()

    print(df[period:].to_string())


# while True:
#     time.sleep(5)
# rsi_based_futures()

# apply_technicals()

# print(df.to_string())


# class Signal:
#     def __init__(self, df, lags):
#         self.df = df
#         self.lags = lags
#
#     def get_trigger(self):
#
#         dfx = pd.DataFrame()
#         for i in range(self.lags + 1):
#             mask = self.df["RSI"].shift(i) < 30
#             dfx = dfx.concat(mask, ignore_index=True)
#
#         return dfx.sum(axis=0)
#
#     def decide(self):
#         self.df["trigger"] = np.where(self.get_trigger(), 1, 0)
#         self.df["Buy"] = np.where(self.df.trigger, 1, 0)


# class RsiSignal(Signal):
#
#     # Buy when RSI was lower than 30 and right now is above 30 for 2 consecutive candles or RSI crossed 20
#     def get_buy_trigger(self):
#         dfx = pd.DataFrame()
#         for i in range(self.lags + 1):
#             mask = self.df["RSI"].shift(i) < 30
#             dfx = dfx.append(mask, ignore_index=True)
#
#             dfx = pd.concat(objs=dfx)
#
#         return dfx.sum(axis=0)
#
#     # Sell when RSI was above 70 and right now is below 70 for 2 consecutive candles or RSI crossed 80
#     def get_sell_trigger(self):
#         dfx = pd.DataFrame()
#         for i in range(self.lags + 1):
#             mask = self.df["RSI"].shift(i) > 70
#             dfx = dfx.append(mask, ignore_index=True)
#
#         return dfx.sum(axis=0)
#
#     def decide(self):
#         # self.df["trigger"] = np.where(self.get_buy_trigger(), 1, 0)
#         self.df["Buy"] = np.where(self.get_buy_trigger(), 1, 0)
#         self.df["Sell"] = np.where(self.get_sell_trigger(), 1, 0)


# def get_rsi_signal(df):


# inst = Signals(df, 100)
#
# inst.decide()
#
# print(df.to_string())


# Read a csv file into a pandas dataframe
# df1 = pd.read_csv('sample_data.txt', parse_dates=True, index_col='Date')
# print(df)
# frame = pd.read_csv(df)
#
# frame['sma'] = ta.sma(period=30)
#
# print(df)
#
# ta.config.set_return_dataframe()


# ema1 = ema(df, period=30)
# dema = 2.0 * ema1 - ema(ema1, period=30)
#
# print(dema)
# print(df)
#


# print(df)
#
#
# def apply_technicals():
#
#
#
#
#
#     return sma
#
#
# sma = apply_technicals()
#
# print(sma)
