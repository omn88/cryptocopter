import asyncio
import logging
from typing import List
from pprint import pformat
import binance
import pandas
from src import orders
from src.common.common import print_last_n_rows
from src.orders import CurrentPosition
from src.producers import producers
from src.producers.producers import (
    OrderUpdate,
    SignalUpdate,
    KlineUpdate,
)
from src.workers.handle_account import account_handle
from src.workers.handle_order import order_handle
from src.workers.state_actions import signal_handle
from src.workers.kline_handle import kline_handle
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("worker_main")


async def worker(
    historical_data: List,
    state_machine: TradingStateMachine,
    current_position: CurrentPosition,
):

    while True:
        logger.info("Current position: %s", pformat(current_position))
        logger.info("Orders: \n%s", pformat(current_position.orders))
        logger.info("Events in queue: %s", state_machine.queue.qsize())
        if state_machine.queue.qsize() == 0:
            logger.info("Awaiting new event...")

        event = await state_machine.queue.get()
        assert isinstance(event, producers.Event)
        logger.info("New event from queue: %s", event)

        if producers.EventName.KLINE == event.name:
            logger.info(
                "Do debugu dla MYPY, <nothing> has no attribute kline, event content: %s",
                event.content,
            )
            assert isinstance(event.content, KlineUpdate)
            historical_data, current_position = await kline_handle(
                historical_data=historical_data,
                current_position=current_position,
                kline=event.content.kline,
                state_machine=state_machine,
            )

        elif producers.EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            current_position, state_machine = await order_handle(
                current_position=current_position,
                order_update=event.content,
                state_machine=state_machine,
            )

        elif producers.EventName.ACCOUNT == event.name:
            df, position = await account_handle(df=state_machine.df, position=position)

        elif producers.EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            current_position, state_machine = await signal_handle(
                signal_update=event.content,
                current_position=position.current_position,
                state_machine=state_machine,
            )

            await print_last_n_rows(df=state_machine.df)

        elif producers.EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            return historical_data, state_machine.df

        logger.info("Task Done: %s", event.content)
        state_machine.queue.task_done()
