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
    Kline = "Kline"
    User = "User"
    Signal = "Signal"


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
            await asyncio.sleep(0.1)


async def futures_user_socket(bm: BinanceSocketManager, queue: asyncio.Queue):

    fus = bm.futures_user_socket()
    async with fus:
        while True:
            msg = await fus.recv()
            await queue.put(Event(name=EventName.User, content=msg))
            logger.info(msg)
            await asyncio.sleep(0.1)


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
                await queue.put(Event(name=EventName.Kline, content=msg))
                logger.info("New index: %s" % index)
                last_index = index
            await asyncio.sleep(0.1)


async def determine_start_position(
    df: pandas.DataFrame, queue: asyncio.Queue
) -> Tuple[pandas.DataFrame, features.Signals]:
    last_signal = None
    last_signal_close_price = 0

    for index, row in df[::-1].iterrows():
        if row["signal"] != 0:
            last_signal = row["signal"]
            last_signal_close_price = row["Close"]
            break
        else:
            last_signal = features.Signals.FLAT

    latest_close = df.iloc[-1]["Close"]

    if last_signal in [features.Signals.LONG, features.Signals.LONG_20]:
        if latest_close < last_signal_close_price:
            signal = last_signal
        else:
            signal = features.Signals.FLAT
    elif last_signal in [features.Signals.SHORT, features.Signals.SHORT_80]:
        if latest_close > last_signal_close_price:
            signal = last_signal
        else:
            signal = features.Signals.FLAT
    else:
        signal = features.Signals.FLAT

    df.at[df.index[-1], "signal"] = signal
    df.at[df.index[-1], "position"] = features.Signals.FLAT
    await queue.put(signal)
    logger.info("Latest signal: %s" % signal)

    return df, signal
