import asyncio
import logging
from enum import Enum
from typing import NamedTuple, List
from binance import BinanceSocketManager
import pandas
import numpy

from src import features
from src.features import Signals

logger = logging.getLogger("producer")


class OrderUpdate(NamedTuple):
    price: float
    quantity: float
    status: str

    def __repr__(self) -> str:
        return f"OrderUpdate(price={self.price}, quantity={self.quantity}, status={self.status})"


class KlineUpdate(NamedTuple):
    kline: List

    def __repr__(self) -> str:
        return f"KlineUpdate(kline={self.kline})"


class SignalUpdate(NamedTuple):
    signal: Signals
    price: float

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal}, price={self.price})"


class EventName(Enum):

    KLINE = "Kline"
    ACCOUNT = "Account"
    ORDER = "Order"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"


class Event(NamedTuple):
    name: EventName
    content: NamedTuple

    def __repr__(self) -> str:
        return f"Event(name={self.name}, content={self.content})"


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
                order_info = msg["o"]
                price = round(float(order_info["p"]), 2)
                quantity = round(float(order_info["z"]), 3)
                status = order_info["X"]
                order_update = OrderUpdate(
                    price=price, quantity=quantity, status=status
                )
                await queue.put(Event(name=EventName.ORDER, content=order_update))
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
            kline_start_time = int(msg["k"]["t"]) - 900000

            index = pandas.to_datetime(kline_start_time, unit="ms") + numpy.timedelta64(
                1, "h"
            )
            if index != last_index:
                logger.info("New index: %s" % index)
                kline = last_msg_before_new_kline["k"]
                kline_start_time = int(kline["t"])
                open_price = round(float(kline["o"]), 1)
                close_price = round(float(kline["c"]), 1)
                high_price = round(float(kline["h"]), 1)
                low_price = round(float(kline["l"]), 1)

                new_kline = [
                    kline_start_time,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    0,
                    0,
                ]
                await queue.put(
                    Event(name=EventName.KLINE, content=KlineUpdate(kline=new_kline))
                )
                last_index = index
            else:
                last_msg_before_new_kline = msg

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

    signal_update = SignalUpdate(signal=signal, price=round(float(price), 2))
    await queue.put(Event(name=EventName.SIGNAL, content=signal_update))
    logger.info("Added signal to queue: signal: %s, price: %s" % (signal, price))

    return df
