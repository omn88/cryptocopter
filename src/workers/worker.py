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


async def worker(state_machine: TradingStateMachine, logger: logging.Logger):
    while True:
        logger.info(
            "-------------------------------------POSITION-------------------------------------------------------------------"
        )
        logger.info("Events in queue: %s", state_machine.strategy.queue.qsize())
        if state_machine.strategy.queue.qsize() == 0:
            logger.info("Awaiting new Event...")

        event = await state_machine.strategy.queue.get()
        assert isinstance(event, Event)
        logger.info("NEW: %s", event)

        if EventName.KLINE == event.name:
            logger.info("Entering kline event ")
            assert isinstance(event.content, KlineUpdate)
            state_machine.strategy.kline_update = event.content
            # All process_* methods are created dynamically, MyPy does not know it exists.
            await state_machine.strategy.process_kline()  # type: ignore

            await print_last_n_rows(df=state_machine.strategy.df)

        elif EventName.ORDER == event.name:
            logger.info(
                "Entering order event, content: %s, type: %s ",
                event.content,
                type(event.content),
            )
            assert isinstance(event.content, OrderUpdate)
            state_machine.strategy.order_update = event.content
            await state_machine.strategy.process_order()  # type: ignore

        elif EventName.ACCOUNT == event.name:
            logger.info(
                "Entering account event, content: %s, type: %s ",
                event.content,
                type(event.content),
            )
            assert isinstance(event.content, AccountUpdate)
            state_machine.strategy.account_update = event.content
            await state_machine.strategy.process_account()  # type: ignore

        elif EventName.SIGNAL == event.name:
            logger.info(
                "Entering signal event, content: %s, type: %s ",
                event.content,
                type(event.content),
            )
            assert isinstance(event.content, SignalUpdate)
            state_machine.strategy.signal_update = event.content
            await state_machine.strategy.process_signal()  # type: ignore

            await print_last_n_rows(df=state_machine.strategy.df)

        elif EventName.SENTINEL == event.name:
            logger.info("Entering sentinel event -> Exiting worker")
            await futures_position_close(
                client=state_machine.strategy.client,
                ui_queue=state_machine.strategy.ui_queue,
                position=state_machine.strategy.position,
                symbol=state_machine.strategy.symbol,
                main_ui_queue=state_machine.strategy.main_ui_queue,
                strategy_name=state_machine.strategy.strategy_name,
            )

            return

        state_machine.strategy.queue.task_done()
