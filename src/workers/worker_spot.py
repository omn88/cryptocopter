from logging_config import StrategyLogger
from src.common.identifiers.common import SentinelUpdate
from src.common.identifiers.spot import (
    AccountPosition,
    EventName,
    Event,
    ExecutionReport,
    SignalUpdate,
    TickerUpdate,
)
from src.strategies.spot.hp_manager import HpManager
from src.workers.trading_state_machine import TradingStateMachine


async def worker(state_machine: TradingStateMachine, logger: StrategyLogger):
    while True:
        logger.debug(
            "-------------------------------------POSITION-----------------------------------------"
        )
        if state_machine.strategy.queue.qsize() == 0:
            logger.debug("Awaiting new Event...")

        event = await state_machine.strategy.queue.get()
        assert isinstance(event, Event)

        logger.debug("New event: %s", event)

        if EventName.TICKER == event.name:
            assert isinstance(event.content, TickerUpdate)
            assert isinstance(state_machine.strategy, HpManager)
            state_machine.strategy.ticker_update = event.content

            logger.debug(
                "Last price for %s: %s, Order trigger price: %s",
                state_machine.strategy.ticker_update.symbol,
                state_machine.strategy.ticker_update.last_price,
                state_machine.strategy.trigger_orders_price,
            )

            await state_machine.strategy.process_ticker()  # type: ignore

        elif EventName.EXECUTION_REPORT == event.name:
            assert isinstance(event.content, ExecutionReport)
            state_machine.strategy.execution_report = event.content
            await state_machine.strategy.process_order()  # type: ignore

        elif EventName.ACCOUNT_POSITION == event.name:
            assert isinstance(event.content, AccountPosition)
            state_machine.strategy.account_position = event.content
            await state_machine.strategy.process_account()  # type: ignore

        elif EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            state_machine.strategy.signal_update = event.content
            await state_machine.strategy.process_signal()  # type: ignore

        elif EventName.SENTINEL == event.name:
            assert isinstance(event.content, SentinelUpdate)
            await state_machine.strategy.position_handler.cancel_position()
            return

        state_machine.strategy.queue.task_done()
