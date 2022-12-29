import asyncio
import logging
from enum import Enum
from typing import Dict, NamedTuple
from binance import BinanceSocketManager
import pandas
import numpy

from src import features

logger = logging.getLogger("producer")


class EventName(Enum):
    KLINE = "Kline"
    ACCOUNT = "Account"
    ORDER = "Order"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"


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
            if msg["e"] == "ACCOUNT_UPDATE":
                await queue.put(Event(name=EventName.ACCOUNT, content=msg))
                logger.info("Account update msg: %s" % msg)
            elif msg["e"] == "ORDER_TRADE_UPDATE":
                await queue.put(Event(name=EventName.ORDER, content=msg))
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
) -> pandas.DataFrame:
    logger.info("Checking start position")

    signal = None
    price = 0
    signal_index = 0
    date_index = None

    for index, row in df[::-1].iterrows():
        if row["signal"] != 0:
            signal = row["signal"]
            price = row["Close"]
            # Adding extra lines to see what happened before signal
            signal_index += 4
            break
        else:
            signal = features.Signals.NULL
            price = row["Close"]
            signal_index += 1

    try:
        assert signal_index <= len(df.index)
        df = df.iloc[len(df.index) - signal_index : :]
        logger.info("New DF shortened to last signal + 3 rows: \n%s" % df.to_string())
    except AssertionError as e:
        logger.info(
            "Last signal almost on top of df, leaving df as is: \n%s" % df.to_string()
        )

    content = {
        "signal": signal,
        "price": price,
    }

    await queue.put(Event(name=EventName.SIGNAL, content=content))

    logger.info("Added signal to queue: signal: %s, price: %s" % (signal, price))

    return df
