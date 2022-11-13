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
    Account = "Account"
    Order = "Order"
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
            if msg["e"] == "ACCOUNT_UPDATE":
                await queue.put(Event(name=EventName.Account, content=msg))
                logger.info("Account update msg: %s" % msg)
            elif msg["e"] == "ORDER_TRADE_UPDATE":
                await queue.put(Event(name=EventName.Order, content=msg))
                logger.info("Order trade update msg: %s" % msg)
            else:
                logger.info(
                    "SOME OTHER KIND OF MESSAGE TO BE IMPLEMENTED IN FUTURE: %s" % msg
                )
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

    logger.info("Checking start position")

    last_signal = None
    last_signal_close_price = 0

    for index, row in df[::-1].iterrows():
        if row["signal"] != 0:
            last_signal = row["signal"]
            last_signal_close_price = row["Close"]
            break
        else:
            last_signal = features.Signals.FLAT

    logger.info("Last signal was: %s" % last_signal)

    latest_close = df.iloc[-1]["Close"]
    logger.info("Last row's price close was: %s" % latest_close)

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
    if last_signal != signal:
        logger.info(
            "It seems the train is gone, let's start Flat and wait for another opportunity, signal: %s"
            % signal
        )
    else:
        logger.info(
            "It seems to be good opportunity. Let's start now, signal: %s" % signal
        )

    return df, signal
