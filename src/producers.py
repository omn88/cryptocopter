import asyncio
import logging
from enum import Enum
from typing import Dict, NamedTuple, Tuple
import features
from binance import BinanceSocketManager
import pandas
import numpy

logger = logging.getLogger("producer")


class EventName(Enum):
    KLINE = "Kline"
    ACCOUNT = "Account"
    ORDER = "Order"
    SIGNAL = "Signal"


class Event(NamedTuple):
    name: EventName
    content: Dict


async def ticker_socket(bm: BinanceSocketManager, queue: asyncio.Queue):

    ticker = bm.symbol_miniticker_socket(symbol="BTCUSDT")
    async with ticker:
        while True:
            msg = await ticker.recv()
            await queue.put(msg)
            logger.info(msg)
            await asyncio.sleep(0.01)


async def futures_user_socket(bm: BinanceSocketManager, queue: asyncio.Queue):

    fus = bm.futures_user_socket()
    async with fus:
        while True:
            msg = await fus.recv()
            logger.info("user")
            if msg["e"] == "ACCOUNT_UPDATE":
                await queue.put(Event(name=EventName.ACCOUNT, content=msg))
                logger.info("Account update msg: %s" % msg)
            elif msg["e"] == "ORDER_TRADE_UPDATE":
                await queue.put(Event(name=EventName.ORDER, content=msg))
                await queue.join()
                logger.info("Order trade update msg: %s" % msg)
            else:
                logger.info(
                    "SOME OTHER KIND OF MESSAGE TO BE IMPLEMENTED IN FUTURE: %s" % msg
                )
            await asyncio.sleep(0.01)


async def kline_futures_socket(
    bm: BinanceSocketManager,
    symbol: str,
    interval: str,
    queue: asyncio.Queue,
    last_index,
):

    kfs = bm.kline_futures_socket(symbol=symbol, interval=interval)
    async with kfs:
        while True:
            msg = await kfs.recv()
            index = pandas.to_datetime(msg["k"]["t"], unit="ms") + numpy.timedelta64(
                1, "h"
            )
            if index != last_index:
                await queue.put(Event(name=EventName.KLINE, content=msg))
                logger.info("New index: %s" % index)
                last_index = index

            await asyncio.sleep(0.01)


async def determine_start_position(
    df: pandas.DataFrame, queue: asyncio.Queue
) -> Tuple[pandas.DataFrame, features.Signals]:

    logger.info("Checking start position")

    last_signal = None
    last_signal_open_price = 0
    signal_index = None

    for index, row in df[::-1].iterrows():
        if row["signal"] != 0:
            last_signal = row["signal"]
            last_signal_open_price = row["Open"]
            signal_index = index
            break
        else:
            last_signal = features.Signals.NULL

    content = {
        "last_signal": last_signal,
        "last_signal_open_price": last_signal_open_price,
    }

    logger.info(
        "Last signal: %s, ls close price: %s" % (last_signal, last_signal_open_price)
    )
    await queue.put(Event(name=EventName.SIGNAL, content=content))
    logger.info("Event name signal send")

    return df, last_signal
