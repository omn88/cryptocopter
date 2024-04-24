from logging_config import StrategyLogger
from src.common.identifiers import (
    KlineUpdate,
    OrderUpdate,
    SignalUpdate,
    AccountUpdate,
    EventName,
    Event,
    TickerUpdate,
)
from src.strategies.base import BaseStrategy
from src.workers.trading_state_machine import TradingStateMachine


async def worker(state_machine: TradingStateMachine, logger: StrategyLogger):
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

            # await state_machine.strategy.df_handler.print_last_n_rows(
            #     df=state_machine.strategy.df
            # )
            logger.info(
                "Last %s rows from main df: %s",
                5,
                state_machine.strategy.df_handler.df.tail(5).to_string(),
            )

        if EventName.TICKER == event.name:
            logger.info("Entering ticker event ")
            assert isinstance(event.content, TickerUpdate)
            state_machine.strategy.ticker_update = event.content
            # All process_* methods are created dynamically, MyPy does not know it exists.
            await state_machine.strategy.process_kline()  # type: ignore

            # await state_machine.strategy.df_handler.print_last_n_rows(
            #     df=state_machine.strategy.df
            # )
            logger.info(
                "Last %s rows from main df: %s",
                5,
                state_machine.strategy.df_handler.df.tail(5).to_string(),
            )

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

            assert isinstance(state_machine.strategy, BaseStrategy)

            # ToDo: FIGURE OUT why this methods halts the system and direct same code works.
            # await state_machine.strategy.df_handler.print_last_n_rows()
            logger.info(
                "Last %s rows from main df: %s",
                5,
                state_machine.strategy.df_handler.df.tail(5).to_string(),
            )

        elif EventName.SENTINEL == event.name:
            logger.info("Entering sentinel event -> Exiting worker")

            await state_machine.strategy.position_handler.close_position()

            return

        state_machine.strategy.queue.task_done()
