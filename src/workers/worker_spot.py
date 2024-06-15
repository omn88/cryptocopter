from logging_config import StrategyLogger
from src.common.identifiers.common import PositionStatus, SentinelUpdate
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
        event = await state_machine.strategy.queue.get()
        assert isinstance(event, Event)

        logger.debug("New event: %s", event)

        if EventName.TICKER == event.name:
            assert isinstance(event.content, TickerUpdate)
            assert isinstance(state_machine.strategy, HpManager)
            state_machine.strategy.ticker_update = event.content

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
            state_machine.strategy.position_handler.status = PositionStatus.CLOSED
            logger.info(
                "Trading system: %s closed successfully.",
                state_machine.strategy.config.system_id,
            )
            return

        state_machine.strategy.queue.task_done()
