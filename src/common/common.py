import errno
import logging
import os
from typing import List
import datetime
import binance
import btalib
import numpy
import pandas

from constants import SYMBOL
from src.common.identifiers import Signal

logger = logging.getLogger("common")


def create_directory_with_timestamp():
    mydir = os.path.join(
        os.getcwd() + "/artifacts",
        datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
    )
    try:
        os.makedirs(mydir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # This was not a "directory exist" error..

    return mydir


def insert_to_pandas(data: List) -> pandas.DataFrame:
    # ToDo: Below Timedelta must react to time change (winter/summer)
    pandas.Timedelta(hours=1)
    df = pandas.DataFrame(data=data)
    df = df.iloc[:, :7]
    df.columns = ["Date", "Open", "High", "Low", "Close", "Volume", "OpenInterest"]
    df = df.set_index("Date")
    df.index = pandas.to_datetime(df.index, unit="ms") + numpy.timedelta64(1, "h")
    df = df.astype(float)
    return df


async def get_futures_historical_data(
    client: binance.AsyncClient, interval: str, lookback: str
) -> List:
    historical_data = await client.futures_historical_klines(
        SYMBOL, interval, lookback + "min ago UTC"
    )
    return historical_data[:-1]


async def print_last_n_rows(df: pandas.DataFrame, rows: int = 5):
    logger.info("Last %s rows from main df: %s", rows, df.tail(rows).to_string())


async def futures_get_balance(client: binance.AsyncClient, asset: str) -> float:
    account_balance = await client.futures_account_balance(asset=asset)
    assert asset == account_balance[8]["asset"]
    balance = round(float(account_balance[8]["balance"]), 2)

    logger.info("Balance %s: %s", account_balance[8]["asset"], balance)

    return balance


async def log_signal_change(df, signal):
    logger.info(
        "Position was %s, signal: %s, position now: %s",
        df.at[df.index[-2], "Position"],
        signal,
        df.at[df.index[-1], "Position"],
    )


def rsi_indicator_apply(df: pandas.DataFrame) -> pandas.DataFrame:
    rsi = btalib.rsi(df, period=14)
    df["RSI"] = rsi.df
    df.dropna(inplace=True)

    return df
