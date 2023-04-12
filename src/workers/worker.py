import asyncio
import logging
from typing import List
from pprint import pformat
from src.common.common import print_last_n_rows
from src.common.identifiers import (
    KlineUpdate,
    OrderUpdate,
    SignalUpdate,
    AccountUpdate,
    EventName,
    Event,
)
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("worker_main")


async def worker(
    queue: asyncio.Queue,
    tsm: TradingStateMachine,
):
    while True:
        logger.info("Current position: %s", pformat(tsm.position))
        logger.info("Orders: \n%s", pformat(tsm.position.orders))
        logger.info("Events in queue: %s", queue.qsize())
        if queue.qsize() == 0:
            logger.info("Awaiting new event...")

        event = await queue.get()
        assert isinstance(event, Event)
        logger.info("New event from queue: %s", event)

        if EventName.KLINE == event.name:
            logger.info(
                "Do debugu dla MYPY, <nothing> has no attribute kline, event content: %s",
                event.content,
            )
            assert isinstance(event.content, KlineUpdate)
            tsm.position = await tsm.process_kline(
                kline_update=event.content, position=tsm.position
            )

        elif EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            tsm.position = await tsm.process_order(
                order_update=event.content, position=tsm.position
            )

        elif EventName.ACCOUNT == event.name:
            assert isinstance(event.content, AccountUpdate)
            tsm.position = await tsm.process_account(
                account_update=event.content, position=tsm.position
            )

        elif EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            tsm.position = await tsm.process_signal(
                signal_update=event.content,
                position=tsm.position,
            )

            await print_last_n_rows(df=tsm.df)

        elif EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            return tsm.raw_data, tsm.df

        logger.info("Task Done: %s", event.content)
        queue.task_done()
