import asyncio
import logging
from typing import List
from pprint import pformat
import binance
import pandas
from src import orders
from src.common.common import print_last_n_rows
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
    position: orders.Position,
):

    while True:
        logger.info("Current position: %s", pformat(position.current_position))
        logger.info("Orders: \n%s", pformat(position.current_position.orders))
        logger.info("Events in queue: %s", queue.qsize())
        if queue.qsize() == 0:
            logger.info("Awaiting new event...")

        event = await queue.get()
        assert isinstance(event, producers.Event)
        logger.info("New event from queue: %s", event)

        if producers.EventName.KLINE == event.name:
            logger.info("Do debugu dla MYPY, <nothing> has no attribute kline, event content: %s", event.content)
            assert isinstance(event.content, KlineUpdate)
            historical_data, df, position.current_position = await kline_handle(
                client=client,
                historical_data=historical_data,
                df=df,
                current_position=position.current_position,
                kline=event.content.kline,
                balance=position.balance,
                order_quantity_list=position.order_quantity_list,
                queue=queue,
            )

        elif producers.EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            position.current_position, df, position.balance = await order_handle(
                client=client,
                current_position=position.current_position,
                order_update=event.content,
                df=df,
                balance=position.balance,
            )

        elif producers.EventName.ACCOUNT == event.name:
            df, position = await account_handle(df=df, position=position)

        elif producers.EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            position.current_position, df = await signal_handle(
                client=client,
                df=df,
                signal_update=event.content,
                current_position=position.current_position,
                balance=position.balance,
                order_quantity_list=position.order_quantity_list,
                queue=queue,
            )

            await print_last_n_rows(df=df)

        elif producers.EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            return historical_data, df, position

        logger.info("Task Done: %s", event.content)
        queue.task_done()
