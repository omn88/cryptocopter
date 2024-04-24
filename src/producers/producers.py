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
    TickerUpdate,
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
                    await queue.put(
                        Event(
                            name=EventName.ORDER,
                            content=OrderUpdate(
                                price=round(float(order_info["p"]), 1),
                                average_price=round(float(order_info["ap"]), 1),
                                quantity=round(float(order_info["z"]), 3),
                                status=order_info["X"],
                                order_id=int(order_info["i"]),
                                order_type=order_info["o"],
                                last_filled_quantity=round(float(order_info["l"]), 3),
                                realized_quantity=round(float(order_info["z"]), 3),
                            ),
                        )
                    )
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
        logger.debug("Stop Event is set, stopping user socket.")


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
        logger.debug(
            "Stop Event is set, stopping symbol mark price socket for %s", symbol
        )


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
        logger.debug("Stop Event is set, stopping kline socket for %s", symbol)


async def spot_user_socket(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    stop_event: asyncio.Event,
):
    socket = socket_manager.user_socket()  # This should be the spot user socket
    async with socket:
        logger.info("Spot user socket connected.")
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                logger.info("From spot user: %s", msg)
                if msg["e"] == "ACCOUNT_UPDATE":
                    await queue.put(
                        Event(
                            name=EventName.ACCOUNT,
                            content=AccountUpdate(account_update=msg),
                        )
                    )
                elif msg["e"] == "ORDER_TRADE_UPDATE":
                    order_info = msg["o"]
                    await queue.put(
                        Event(
                            name=EventName.ORDER,
                            content=OrderUpdate(
                                symbol=order_info["s"],
                                price=round(float(order_info["p"]), 1),
                                average_price=round(float(order_info["ap"]), 1),
                                quantity=round(float(order_info["z"]), 3),
                                status=order_info["X"],
                                order_id=int(order_info["i"]),
                                order_type=order_info["o"],
                                last_filled_quantity=round(float(order_info["l"]), 3),
                                realized_quantity=round(float(order_info["z"]), 3),
                            ),
                        )
                    )
                else:
                    logger.info("Unhandled message type: %s", msg)
            except asyncio.TimeoutError:
                continue


# async def spot_kline_socket(
#     socket_manager: BinanceSocketManager,
#     interval: str,
#     queue: asyncio.Queue,
#     symbol: str,
#     stop_event: asyncio.Event,
# ):
#     socket = socket_manager.kline_socket(symbol=symbol, interval=interval)
#     async with socket:
#         logger.info("Spot kline socket connected.")
#         while not stop_event.is_set():
#             try:
#                 msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
#                 kline = msg["k"]
#                 logger.info("From spot kline: %s", msg)
#                 await queue.put(
#                     Event(
#                         name=EventName.KLINE,
#                         content=KlineUpdate(
#                             start_time=int(kline["t"]),
#                             open_price=round(float(kline["o"]), 1),
#                             close_price=round(float(kline["c"]), 1),
#                             high_price=round(float(kline["h"]), 1),
#                             low_price=round(float(kline["l"]), 1),
#                             volume=0,
#                             open_interest=0,
#                         ),
#                     )
#                 )

#             except asyncio.TimeoutError:
#                 continue


async def spot_ticker_socket(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    symbol: str,
    stop_event: asyncio.Event,
):
    socket = socket_manager.ticker_socket(symbol=symbol)
    async with socket:
        logger.info("Spot ticker socket connected.")
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(socket.recv(), timeout=1.0)
                ticker = msg["data"]
                logger.info("From spot ticker: %s", msg)
                await queue.put(
                    Event(
                        name=EventName.TICKER,
                        content=TickerUpdate(
                            last_price=round(float(ticker["c"]), 1),  # Last price
                            best_bid_price=round(
                                float(ticker["b"]), 1
                            ),  # Best bid price
                            best_ask_price=round(
                                float(ticker["a"]), 1
                            ),  # Best ask price
                            high_price=round(
                                float(ticker["h"]), 1
                            ),  # High price of the day
                            low_price=round(
                                float(ticker["l"]), 1
                            ),  # Low price of the day
                            volume=float(ticker["v"]),  # Total traded base asset volume
                        ),
                    )
                )

            except asyncio.TimeoutError:
                continue
