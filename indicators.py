import binance
import btalib as ta
import pandas as pd
import numpy as np
from btalib import ema

client = binance.Client(
    api_key="oA6bheAMqRK8DGAKNnj2duGzIQepkOhhjz2OIJjgwRDVMbvF1uwuFOXhMA2Au8Lk",
    api_secret="i1C5VVg6W17vHTo5rQ6FJqZaP0e6eXc9k9NYZh0sUq6lRb4yN6mj1CKSw9jLld84",
)


def get_historical_data(symbol, interval, lookback):
    frame = pd.DataFrame(
        client.get_historical_klines(symbol, interval, lookback + "min ago UTC")
    )

    frame = frame.iloc[:, :7]
    frame.columns = ["Date", "Open", "High", "Low", "Close", "Volume", "OpenInterest"]
    frame = frame.set_index("Date")
    frame.index = pd.to_datetime(frame.index, unit="ms")
    frame = frame.astype(float)
    return frame


df = get_historical_data("BTCUSDT", "15m", "600")

print(df)


def apply_technicals():
    rsi = ta.rsi(df, period=14)  # default period is 30
    df["RSI"] = rsi.df


# Read a csv file into a pandas dataframe
# df1 = pd.read_csv('sample_data.txt', parse_dates=True, index_col='Date')
# print(df)

#
# # print(df1)


apply_technicals()

print(df)

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
