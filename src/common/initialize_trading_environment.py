import asyncio
import signal

import binance
import pandas
from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException
from decouple import config

import logging

from src.common.constants import SYMBOL, MARGIN_TYPE
from src.producers.producers import (
    kline_futures_socket,
    futures_user_socket,
    futures_symbol_mark_price_socket,
)
from src.workers.trading_state_machine import TradingStateMachine
from src.workers.worker import worker

logger = logging.getLogger("initialize_trading_environment")


async def create_async_client() -> binance.AsyncClient:
    client = await AsyncClient.create(
        api_key=config("FUTURES_API_KEY"), api_secret=config("FUTURES_API_SECRET")
    )
    logger.info("Async client created")

    return client


async def create_socket_manager(client: binance.AsyncClient) -> BinanceSocketManager:
    bsm = BinanceSocketManager(client)
    logger.info("Binance socket manager created.")

    return bsm


def create_async_queue() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    logger.info("Async FIFO Queue started")

    return queue


# def register_signal_handlers(loop, client, position, balance):
#     signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
#     for s in signals:
#         loop.add_signal_handler(
#             s,
#             lambda s=s: asyncio.create_task(  # ToDo: THERE IS A METHOD FOR CLOSING ALL OPEN ORDERS
#                 shutdown(
#                     client=client,
#                     posix_signal=s,
#                     position=position,
#                     balance=balance,
#                 )
#             ),
#         )


async def change_margin_type(client: binance.AsyncClient) -> None:
    try:
        await client.futures_change_margin_type(symbol=SYMBOL, marginType=MARGIN_TYPE)
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s" % e)


def prepare_producers(
    bsm: BinanceSocketManager,
    queue: asyncio.Queue,
    ui_queue: asyncio.Queue,
    interval: str,
    df: pandas.DataFrame,
    tsm: TradingStateMachine,
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
        asyncio.create_task(futures_user_socket(bm=bsm, queue=queue, tsm=tsm)),
        asyncio.create_task(
            futures_symbol_mark_price_socket(bsm=bsm, ui_queue=ui_queue)
        ),
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
