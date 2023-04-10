import asyncio
import logging
from typing import List
from pprint import pformat
import binance
from src.common.common import print_last_n_rows
from src.common.orders import Position
from src.producers import producers
from src.producers.producers import (
    OrderUpdate,
    SignalUpdate,
    KlineUpdate,
)
from src.workers.handle_account import account_handle
from src.workers.kline_handle import kline_handle
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("worker_main")


async def worker(
    client: binance.AsyncClient,
    queue: asyncio.Queue,
    historical_data: List,
    tsm: TradingStateMachine,
    position: Position,
):
    while True:
        logger.info("Current position: %s", pformat(position))
        logger.info("Orders: \n%s", pformat(position.orders))
        logger.info("Events in queue: %s", queue.qsize())
        if queue.qsize() == 0:
            logger.info("Awaiting new event...")

        event = await queue.get()
        assert isinstance(event, producers.Event)
        logger.info("New event from queue: %s", event)

        if producers.EventName.KLINE == event.name:
            logger.info(
                "Do debugu dla MYPY, <nothing> has no attribute kline, event content: %s",
                event.content,
            )
            assert isinstance(event.content, KlineUpdate)
            historical_data, position = await kline_handle(
                historical_data=historical_data,
                position=position,
                kline=event.content.kline,
                tsm=tsm,
            )

        elif producers.EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            position = await tsm.process_order(
                order_update=event.content, position=position
            )

        elif producers.EventName.ACCOUNT == event.name:
            df, position = await account_handle(df=tsm.df, position=position)

        elif producers.EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)

            position = await tsm.process_signal(
                signal_update=event.content,
                position=position,
            )

            await print_last_n_rows(df=tsm.df)

        elif producers.EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            return historical_data, tsm.df

        logger.info("Task Done: %s", event.content)
        queue.task_done()
