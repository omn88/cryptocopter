import errno
import logging
import os
from typing import List
from datetime import datetime
import btalib
import numpy
import pandas
import pytz
import uuid
from src.common.identifiers import Signal, State, BinanceClient

logger = logging.getLogger("common")


def create_directory_with_timestamp():
    mydir = os.path.join(
        os.getcwd() + "/artifacts",
        datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
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
    client: BinanceClient, interval: str, lookback: str, symbol: str
) -> List:
    historical_data = await client.futures_historical_klines(
        symbol, interval, lookback + "min ago UTC"
    )
    return historical_data[:-1]


async def print_last_n_rows(df: pandas.DataFrame, rows: int = 5):
    logger.info("Last %s rows from main df: %s", rows, df.tail(rows).to_string())


async def futures_get_balance(client: BinanceClient, asset: str) -> float:
    account_balance = await client.futures_account_balance(asset=asset)
    for account in account_balance:
        if account["asset"] == asset:
            balance = round(float(account["balance"]), 2)
            logger.info("Balance %s: %s", account["asset"], balance)
            return balance

    raise KeyError(f"Asset: {asset} not found in account balance")


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


def signal_to_state(signal: Signal) -> State:
    return State(signal.value)


def convert_time(timestamp):
    # Binance timestamp is in milliseconds, convert it to seconds
    timestamp_s = timestamp / 1000

    # Create datetime object in UTC
    utc_time = datetime.utcfromtimestamp(timestamp_s)

    # Add timezone information
    utc_time = utc_time.replace(tzinfo=pytz.utc)

    # Convert to Polish timezone
    poland_time = utc_time.astimezone(pytz.timezone("Europe/Warsaw"))

    # Format the datetime object to a string with desired format
    formatted_poland_time = poland_time.strftime("%Y-%m-%d %H:%M:%S")

    return formatted_poland_time


def generate_position_id(strategy_name):
    current_time = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex
    return f"{strategy_name}_{current_time}_{unique_id}"
