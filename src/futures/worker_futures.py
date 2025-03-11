from transitions.extensions.asyncio import AsyncMachine
from logging_config import StrategyLogger
from src.identifiers.futures import (
    KlineUpdate,
    SignalUpdate,
    Event,
    EventName,
    AccountUpdate,
    OrderUpdate,
)
from src.futures.strategies.futures.base import BaseFuturesStrategy


async def worker(state_machine: AsyncMachine, logger: StrategyLogger):
    while True:
        logger.info(
            "-------------------------------------POSITION-----------------------------------------"
        )
        if state_machine.strategy.queue.qsize() == 0:
            logger.info("Awaiting new Event...")

        event = await state_machine.strategy.queue.get()
        assert isinstance(event, Event)

        if EventName.KLINE == event.name:
            logger.info("Entering kline event: %s", event)
            assert isinstance(event.content, KlineUpdate)
            state_machine.strategy.kline_update = event.content
            # All process_* methods are created dynamically, MyPy does not know it exists.
            await state_machine.strategy.process_kline()  # type: ignore

            logger.info(
                "Last %s rows from main df: %s",
                5,
                state_machine.strategy.df_handler.df.tail(5).to_string(),
            )

        elif EventName.ORDER == event.name:
            logger.info("Entering order event: %s", event)
            assert isinstance(event.content, OrderUpdate)
            state_machine.strategy.order_update = event.content
            await state_machine.strategy.process_order()  # type: ignore

        elif EventName.ACCOUNT == event.name:
            logger.info("Entering account event: %s", event)
            assert isinstance(event.content, AccountUpdate)
            state_machine.strategy.account_update = event.content
            await state_machine.strategy.process_account()  # type: ignore

        elif EventName.SIGNAL == event.name:
            logger.info("Entering signal event: %s", event)
            assert isinstance(event.content, SignalUpdate)
            state_machine.strategy.signal_update = event.content
            await state_machine.strategy.process_signal()  # type: ignore

            assert isinstance(state_machine.strategy, BaseFuturesStrategy)

            logger.info(
                "Last %s rows from main df: %s",
                5,
                state_machine.strategy.df_handler.df.tail(5).to_string(),
            )

        elif EventName.SENTINEL == event.name:
            logger.info("Entering sentinel event -> Exiting worker")

            await state_machine.strategy.position_handler.cancel_position()
            return

        state_machine.strategy.queue.task_done()
