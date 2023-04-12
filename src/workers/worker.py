import asyncio
import logging
from typing import List
from pprint import pformat
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
    queue: asyncio.Queue,
    historical_data: List,
    tsm: TradingStateMachine,
):
    while True:
        logger.info("Current position: %s", pformat(tsm.position))
        logger.info("Orders: \n%s", pformat(tsm.position.orders))
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
            tsm.position = await tsm.process_kline(
                kline_update=event.content, position=tsm.position
            )

        elif producers.EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            tsm.position = await tsm.process_order(
                order_update=event.content, position=tsm.position
            )

        elif producers.EventName.ACCOUNT == event.name:
            tsm.position = await tsm.process_account(
                account_update=event.content, position=tsm.position
            )

        elif producers.EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            tsm.position = await tsm.process_signal(
                signal_update=event.content,
                position=tsm.position,
            )

            await print_last_n_rows(df=tsm.df)

        elif producers.EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            return historical_data, tsm.df

        logger.info("Task Done: %s", event.content)
        queue.task_done()
