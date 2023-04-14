import asyncio
import errno
import logging
import os
import signal
from typing import List, Tuple
import datetime
import binance
import numpy
import pandas
from binance import BinanceSocketManager, AsyncClient
from binance.exceptions import BinanceAPIException
from decouple import config

from constants import SYMBOL
from src.common.identifiers import Position, State
from src.producers.producers import kline_futures_socket, futures_user_socket
from src.workers.handle_order import futures_position_close
from src.workers.trading_state_machine import TradingStateMachine
from src.workers.worker import worker

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
    client: binance.AsyncClient,
) -> Tuple[float, float, float]:
    """
    Retrieve the liquidation price for a given symbol on the Binance Futures trading platform.

    :param client: An instance of the Binance async client
    :type client: binance.AsyncClient
    :return: A dictionary containing the symbol, liquidation price, entry price and position amount for the given symbol
    :rtype: dict
    """
    logger.info("Enter position information")
    try:
        resp = await client.futures_position_information(symbol=SYMBOL)
        logger.info("RESP: %s", resp)
        liquidation_price = round(float(resp[0]["liquidationPrice"]), 1)
        entry_price = round(float(resp[0]["entryPrice"]), 1)
        position_amt = float(resp[0]["positionAmt"])
    except BinanceAPIException as e:
        raise ValueError(
            f"Failed to retrieve position information for symbol {SYMBOL} due to {e}"
        )

    logger.info("Exit position information")

    return liquidation_price, entry_price, position_amt


async def get_futures_historical_data(
    client: binance.AsyncClient, interval: str, lookback: str
) -> List:

    historical_data = await client.futures_historical_klines(
        SYMBOL, interval, lookback + "min ago UTC"
    )
    return historical_data[:-1]


async def print_last_n_rows(df: pandas.DataFrame, rows: int = 8):
    logger.info("Last %s rows from main df: %s", rows, df.tail(rows).to_string())


async def futures_get_balance(client: binance.AsyncClient, asset: str) -> float:
    account_balance = await client.futures_account_balance(asset=asset)
    logger.info("account balance: %s", account_balance)
    logger.info("asset: %s, other asset: %s", asset, account_balance[8]["asset"])
    assert asset == account_balance[8]["asset"]
    balance = round(float(account_balance[8]["balance"]), 2)

    logger.info("Balance for %s: %s", account_balance[6]["asset"], balance)

    return balance


async def log_signal_change(df, signal):
    logger.info(
        "Position was %s, signal: %s, position now: %s",
        df.at[df.index[-2], "position"],
        signal,
        df.at[df.index[-1], "position"],
    )


async def shutdown(
    client: binance.AsyncClient,
    posix_signal: signal.Signals,
    position: Position,
    balance: float,
):
    """Cleanup tasks tied to the service's shutdown."""
    logging.info("Received exit signal %s...", posix_signal.name)

    await futures_position_close(client=client, position=position, balance=balance)

    logging.info("Nacking outstanding messages")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    [task.cancel() for task in tasks]

    logging.info(f"Flushing metrics")
    await client.close_connection()


def register_signal_handlers(loop, client, position, balance):
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s,
            lambda s=s: asyncio.create_task(
                shutdown(
                    client=client,
                    posix_signal=s,
                    position=position,
                    balance=balance,
                )
            ),
        )


def prepare_producers(
    bsm: BinanceSocketManager, queue: asyncio.Queue, interval: str, df: pandas.DataFrame
):
    return [
        asyncio.create_task(
            kline_futures_socket(
                bsm=bsm,
                queue=queue,
                interval=interval,
                last_index=df.index[-1],
            )
        ),
        asyncio.create_task(futures_user_socket(bm=bsm, queue=queue)),
    ]


def prepare_workers(
    tsm: TradingStateMachine,
    queue: asyncio.Queue,
):
    return [
        asyncio.create_task(
            worker(
                tsm=tsm,
                queue=queue,
            )
        )
    ]


async def change_margin_type(client: binance.AsyncClient) -> None:
    try:
        await client.futures_change_margin_type(symbol=SYMBOL, marginType="ISOLATED")
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s" % e)


async def create_async_client() -> binance.AsyncClient:
    client = await AsyncClient.create(
        api_key=config("FUTURES_API_KEY"), api_secret=config("FUTURES_API_SECRET")
    )
    logger.info("Async client created")

    return client


async def create_socket_manager(client: binance.AsyncClient) -> BinanceSocketManager:
    bsm = BinanceSocketManager(client)
    logger.info("Binance socket manager ready")

    return bsm


async def create_async_queue() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    logger.info("Async FIFO Queue started")

    return queue
