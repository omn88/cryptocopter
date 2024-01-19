import asyncio
import logging
from typing import Dict
from binance import BinanceSocketManager
import pandas
import numpy
from src.common.identifiers import (
    Event,
    EventName,
    AccountUpdate,
    OrderUpdate,
    KlineUpdate,
)
from src.gui.identifiers import PriceData

logger = logging.getLogger("producer")


async def futures_user_socket(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    socket = socket_manager.futures_user_socket()
    async with socket:
        logger.info("Ready to receive first user socket message.")

        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                if msg["e"] == "ACCOUNT_UPDATE":
                    await queue.put(
                        Event(
                            name=EventName.ACCOUNT,
                            content=AccountUpdate(account_update=msg),
                        )
                    )
                    logger.debug("Account update msg: %s", msg)
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
                    logger.debug("Order trade update msg: %s", msg)
                elif msg["e"] == "MARGIN_CALL":
                    logger.info("Margin call")
                else:
                    logger.info(
                        "SOME OTHER KIND OF MESSAGE TO BE IMPLEMENTED IN FUTURE: %s",
                        msg,
                    )
            except asyncio.TimeoutError:
                continue


async def futures_symbol_mark_price_socket(
    socket_manager: BinanceSocketManager,
    ui_queue: asyncio.Queue,
    main_ui_queue: asyncio.Queue,
    symbol: str,
    stop_event: asyncio.Event,
):
    socket = socket_manager.symbol_mark_price_socket(symbol=symbol)

    async with socket:
        logger.info("Ready to receive first mark price socket message.")
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(socket.recv(), timeout=1.0)

                price_data = PriceData(
                    index_price=round(float(msg["data"]["i"]), 1),
                    symbol=msg["data"]["s"],
                    mark_price=round(float(msg["data"]["p"]), 1),
                )
                await ui_queue.put(price_data)
                await main_ui_queue.put(price_data)
            except asyncio.TimeoutError:
                continue


async def kline_futures_socket(
    socket_manager: BinanceSocketManager,
    interval: str,
    queue: asyncio.Queue,
    symbol: str,
    stop_event: asyncio.Event,
):
    last_index = None
    last_msg_before_new_kline: Dict = {}
    socket = socket_manager.kline_futures_socket(symbol=symbol, interval=interval)
    async with socket:
        logger.info("Ready to receive first kline socket message.")
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(socket.recv(), timeout=1.0)

                kline_start_time = int(msg["k"]["t"]) - 900000
                index = pandas.to_datetime(
                    kline_start_time, unit="ms"
                ) + numpy.timedelta64(1, "h")
                last_index = index if last_index is None else last_index
                if index != last_index:
                    logger.info("New index: %s", index)
                    kline = last_msg_before_new_kline["k"]

                    await queue.put(
                        Event(
                            name=EventName.KLINE,
                            content=KlineUpdate(
                                start_time=int(kline["t"]),
                                open_price=round(float(kline["o"]), 1),
                                close_price=round(float(kline["c"]), 1),
                                high_price=round(float(kline["h"]), 1),
                                low_price=round(float(kline["l"]), 1),
                                volume=0,
                                open_interest=0,
                            ),
                        )
                    )
                    last_index = index
                else:
                    last_msg_before_new_kline = msg
            except asyncio.TimeoutError:
                continue
