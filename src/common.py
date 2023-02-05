import errno
import logging
import os
from typing import List, Tuple
import datetime
import binance
import numpy
import pandas
from binance.exceptions import BinanceAPIException

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


async def futures_get_position_info(
    client: binance.AsyncClient, symbol: str
) -> Tuple[float, float, float]:
    """
    Retrieve the liquidation price for a given symbol on the Binance Futures trading platform.

    :param client: An instance of the Binance async client
    :type client: binance.AsyncClient
    :param symbol: The symbol for the futures contract
    :type symbol: str
    :return: A dictionary containing the symbol, liquidation price, entry price and position amount for the given symbol
    :rtype: dict
    """
    logger.info("Enter position information")
    try:
        resp = await client.futures_position_information(symbol=symbol)
        logger.info("RESP: %s", resp)
        liquidation_price = round(float(resp[0]["liquidationPrice"]), 1)
        entry_price = round(float(resp[0]["entryPrice"]), 1)
        position_amt = float(resp[0]["positionAmt"])
    except BinanceAPIException as e:
        raise ValueError(
            f"Failed to retrieve position information for symbol {symbol} due to {e}"
        )

    logger.info("Exit position information")

    return liquidation_price, entry_price, position_amt


async def print_last_n_rows(df: pandas.DataFrame, rows: int = 8):
    logger.info("Last %s rows from main df: %s", rows, df.tail(rows).to_string())


async def futures_get_balance(client: binance.AsyncClient, asset: str) -> float:
    account_balance = await client.futures_account_balance(asset=asset)
    assert asset == account_balance[6]["asset"]
    balance = round(float(account_balance[6]["balance"]), 2)

    logger.info("Balance for %s: %s", account_balance[6]["asset"], balance)

    return balance
