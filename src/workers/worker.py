import asyncio
import logging
from typing import List
from pprint import pformat
import binance
import pandas
from src import orders
from src.common import print_last_n_rows
from src.producers import producers
from src.producers.producers import (
    OrderUpdate,
    SignalUpdate,
    KlineUpdate,
)
from src.workers.handle_account import account_handle
from src.workers.handle_order import order_handle
from src.workers.handle_signal import signal_handle
from src.workers.kline_handle import kline_handle

logger = logging.getLogger("worker_main")


async def worker(
    df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    historical_data: List,
    position: orders.RsiBasedFutures,
):

    while True:
        logger.info("Current position: %s", pformat(position.current_position))
        logger.info("Orders: \n%s", pformat(position.orders))
        logger.info("Events in queue: %s", queue.qsize())
        if queue.qsize() == 0:
            logger.info("Awaiting new event...")

        event = await queue.get()
        assert isinstance(event, producers.Event)
        logger.info("New event from queue: %s", event)

        if producers.EventName.KLINE == event.name:
            assert isinstance(event.content, KlineUpdate)
            historical_data, df, position = await kline_handle(
                client=client,
                historical_data=historical_data,
                df=df,
                position=position,
                kline=event.content.kline,
            )

        elif producers.EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            position, df = await order_handle(
                client=client, position=position, order_update=event.content, df=df
            )

        elif producers.EventName.ACCOUNT == event.name:
            df, position = await account_handle(df=df, position=position)

        elif producers.EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            df, position = await signal_handle(
                client=client,
                df=df,
                signal_update=event.content,
                rbf=position,
            )

            await print_last_n_rows(df=df)

        elif producers.EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            return historical_data, df, position

        logger.info("Task Done: %s", event.content)
        queue.task_done()
