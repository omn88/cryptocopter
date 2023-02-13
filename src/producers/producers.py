import asyncio
import logging
from enum import Enum
from typing import NamedTuple, List

import binance
from binance import BinanceSocketManager
import pandas
import numpy

from constants import SYMBOL
from src.features import Signals

logger = logging.getLogger("producer")


class OrderUpdate(NamedTuple):
    price: float
    quantity: float
    status: str
    realized_quantity: float
    last_filled_quantity: float
    order_id: int
    average_price: float = 0
    order_type: str = binance.AsyncClient.ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return f"OrderUpdate(price={self.price}, quantity={self.quantity}, status={self.status}, order_id={self.order_id}, order_type={self.order_type})"


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


async def futures_user_socket(bm: BinanceSocketManager, queue: asyncio.Queue):

    fus = bm.futures_user_socket()
    async with fus:
        while True:
            msg = await fus.recv()
            if msg["e"] == "ACCOUNT_UPDATE":
                await queue.put(Event(name=EventName.ACCOUNT, content=msg))
                logger.info("Account update msg: %s", msg)
            elif msg["e"] == "ORDER_TRADE_UPDATE":
                order_info = msg["o"]
                price = round(float(order_info["p"]), 1)
                average_price = round(float(order_info["ap"]), 1)
                quantity = round(float(order_info["z"]), 3)
                order_id = int(order_info["i"])
                status = order_info["X"]
                order_type = order_info["o"]
                realized_quantity = round(float(order_info["z"]), 3)
                last_filled_quantity = round(float(order_info["l"]), 3)
                order_update = OrderUpdate(
                    price=price,
                    average_price=average_price,
                    quantity=quantity,
                    status=status,
                    order_id=order_id,
                    order_type=order_type,
                    last_filled_quantity=last_filled_quantity,
                    realized_quantity=realized_quantity,
                )
                await queue.put(Event(name=EventName.ORDER, content=order_update))
                logger.info("Order trade update msg: %s", msg)
            elif msg["e"] == "MARGIN_CALL":
                logger.info("Margin call")
            else:
                logger.info(
                    "SOME OTHER KIND OF MESSAGE TO BE IMPLEMENTED IN FUTURE: %s", msg
                )
            await asyncio.sleep(0.1)


async def kline_futures_socket(
    bm: BinanceSocketManager,
    interval: str,
    queue: asyncio.Queue,
    last_index,
):

    kfs = bm.kline_futures_socket(symbol=SYMBOL, interval=interval)
    async with kfs:
        while True:
            msg = await kfs.recv()
            kline_start_time = int(msg["k"]["t"]) - 900000

            index = pandas.to_datetime(kline_start_time, unit="ms") + numpy.timedelta64(
                1, "h"
            )
            if index != last_index:
                logger.info("New index: %s", index)
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

            await asyncio.sleep(0.1)


async def determine_start_position(
    df: pandas.DataFrame, queue: asyncio.Queue
) -> pandas.DataFrame:
    logger.info("Checking start position")

    signal = Signals.NULL
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

        price = row["Close"]
        signal_index += 1

    try:
        assert signal_index <= len(df.index)
        df = df.iloc[len(df.index) - signal_index : :]
        logger.debug("New DF shortened to last signal + 3 rows: \n%s", df.to_string())
    except AssertionError as e:
        logger.debug(
            "Last signal almost on top of df, leaving df as is: \n%s", df.to_string()
        )

    signal_update = SignalUpdate(signal=signal, price=round(float(price), 2))
    if signal_update.signal != 0:
        await queue.put(Event(name=EventName.SIGNAL, content=signal_update))
        logger.info("Added signal to queue: signal: %s, price: %s", signal, price)
    else:
        logger.info("No signal created, starting flat and awaiting new signal.")

    return df
