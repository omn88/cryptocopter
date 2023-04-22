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


async def process_kline(tsm: TradingStateMachine, kline_update: KlineUpdate):
    tsm.kline_update = kline_update
    await tsm.machine.model.process_kline()


async def process_signal(tsm: TradingStateMachine, signal_update: SignalUpdate):
    tsm.signal_update = signal_update
    await tsm.machine.model.process_signal()


async def process_account(tsm: TradingStateMachine, account_update: AccountUpdate):
    tsm.account_update = account_update
    await tsm.machine.model.process_account()


async def process_order(tsm: TradingStateMachine, order_update: OrderUpdate):
    tsm.order_update = order_update
    await tsm.machine.model.process_order()


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
            # TODO: THIS MAY NOT WORK, BUT IDE DOES NOT CRY ABOUT UNRESOLVED ATTRIBUTE!!
            await process_kline(tsm=tsm, kline_update=event.content)

        elif EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            await process_order(tsm=tsm, order_update=event.content)

        elif EventName.ACCOUNT == event.name:
            assert isinstance(event.content, AccountUpdate)
            await process_account(tsm=tsm, account_update=event.content)

        elif EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            await process_signal(tsm=tsm, signal_update=event.content)

            await print_last_n_rows(df=tsm.df)

        elif EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            return tsm.raw_data, tsm.df

        logger.info("Task Done: %s", event.content)
        queue.task_done()
