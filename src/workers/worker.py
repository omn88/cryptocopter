import asyncio
import logging
from src.common.common import print_last_n_rows
from src.common.identifiers import (
    KlineUpdate,
    OrderUpdate,
    SignalUpdate,
    AccountUpdate,
    EventName,
    Event,
)
from src.workers.handle_order import futures_position_close
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("worker_main")


async def process_kline(tsm: TradingStateMachine, kline_update: KlineUpdate):
    tsm.kline_update = kline_update
    # All process_* methods are created dynamically, MyPy does not know it exists.
    await tsm.process_kline()  # type: ignore


async def process_signal(tsm: TradingStateMachine, signal_update: SignalUpdate):
    tsm.signal_update = signal_update
    await tsm.process_signal()  # type: ignore


async def process_account(tsm: TradingStateMachine, account_update: AccountUpdate):
    tsm.account_update = account_update
    await tsm.process_account()  # type: ignore


async def process_order(tsm: TradingStateMachine, order_update: OrderUpdate):
    tsm.order_update = order_update
    await tsm.process_order()  # type: ignore


async def worker(
    queue: asyncio.Queue,
    tsm: TradingStateMachine,
):
    while True:
        logger.info(
            "-------------------------------------POSITION-------------------------------------------------------------------"
        )
        logger.info("Events in queue: %s", queue.qsize())
        if queue.qsize() == 0:
            logger.info("Awaiting new Event...")

        event = await queue.get()
        assert isinstance(event, Event)
        logger.info("NEW: %s", event)

        if EventName.KLINE == event.name:
            assert isinstance(event.content, KlineUpdate)
            await process_kline(tsm=tsm, kline_update=event.content)

            await print_last_n_rows(df=tsm.df)

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
            await futures_position_close(
                client=tsm.client,
                ui_queue=tsm.ui_queue,
                position=tsm.position,
            )
            return

        queue.task_done()
