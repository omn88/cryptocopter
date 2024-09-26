import asyncio
import logging
import queue
from typing import Optional
from transitions.extensions.asyncio import AsyncMachine
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import (
    BinanceClient,
    SentinelUpdate,
)
from src.strategies.spot.hp_manager import HpManager
from src.common.identifiers.spot import (
    AccountPosition,
    EventName,
    Event,
    ExecutionReport,
    SignalUpdate,
    State,
    StateInfo,
    TickerUpdate,
    StrategyConfig,
)

logger = logging.getLogger("trading_system")


class TradingSystem:
    def __init__(
        self,
        client: BinanceClient,
        ui_queue: queue.Queue,
        core_queue: queue.Queue,
        config: StrategyConfig,
        strategy_logger: StrategyLogger,
        db: Database,
    ):
        self.client = client
        self.config = config
        self.ui_queue = ui_queue
        self.core_queue = core_queue
        self.strategy_logger = strategy_logger
        self.db = db
        self.state_machine: Optional[AsyncMachine] = None
        self.strategy: Optional[HpManager] = None

    async def initialize_strategy(self, state_info: StateInfo, usdt_balance: float):
        # Strategy initialization
        self.strategy = HpManager(
            client=self.client,
            ui_queue=self.ui_queue,
            logger=self.strategy_logger,
            config=self.config,
            balance=usdt_balance,
            db=self.db,
            core_queue=self.core_queue,
        )

        self.strategy_logger.info("Config status: %s", state_info.last_state)

        if state_info.last_state is not None:
            self.strategy_logger.debug(
                "Old status is not None: %s, moving strategy state to recovering",
                state_info.last_state,
            )
            self.strategy.state = State.RECOVERING
            self.strategy.position_handler.last_state = state_info.last_state

        # Trading State Machine initialization
        self.state_machine = AsyncMachine(
            model=self.strategy,
            states=self.strategy.states,
            transitions=self.strategy.transitions,
            initial=self.strategy.state,
            send_event=True,
            queued=True,
        )

        self.strategy.position_handler.stagnation_counter = (
            state_info.stagnation_counter
        )
        self.strategy.position_handler.next_monitor_position_time = (
            state_info.next_monitor_time
        )

    async def worker(self):
        if self.state_machine:
            assert isinstance(self.state_machine.model, HpManager)
            logger.info("Worker start now, state: %s.", self.state_machine.model.state)
            while True:
                try:
                    event = self.state_machine.model.core_queue.get_nowait()
                    assert isinstance(event, Event)

                    logger.debug("New event: %s", event)

                    if EventName.TICKER == event.name:
                        assert isinstance(event.content, TickerUpdate)
                        self.state_machine.model.ticker_update = event.content
                        if self.state_machine.model.state == State.RECOVERING:
                            await self.state_machine.model.process_recovery()
                        else:
                            await self.state_machine.model.process_ticker()

                    elif EventName.EXECUTION_REPORT == event.name:
                        assert isinstance(event.content, ExecutionReport)
                        self.state_machine.model.execution_report = event.content
                        await self.state_machine.model.process_order()  # type: ignore

                    elif EventName.ACCOUNT_POSITION == event.name:
                        assert isinstance(event.content, AccountPosition)
                        self.state_machine.model.account_position = event.content
                        await self.state_machine.model.process_account()  # type: ignore

                    elif EventName.SIGNAL == event.name:
                        assert isinstance(event.content, SignalUpdate)
                        self.state_machine.model.signal_update = event.content
                        await self.state_machine.model.process_signal()  # type: ignore

                    elif EventName.SENTINEL == event.name:
                        assert isinstance(event.content, SentinelUpdate)
                        self.state_machine.model.state = State.CLOSED
                        await self.state_machine.model.position_handler.cancel_position(
                            state=self.state_machine.model.state
                        )
                        logger.info(
                            "Trading system: %s closed successfully.",
                            self.state_machine.model.config.system_id,
                        )
                        return

                    self.state_machine.model.core_queue.task_done()
                except queue.Empty:
                    await asyncio.sleep(0.1)

    async def stop(self):
        # This method stops the trading. You'll have to implement this based on how your strategy can be stopped.
        # It might involve cancelling the tasks that were started in `start`.
        self.strategy_logger.info(
            "Closing trading system: %s", self.strategy.config.system_id
        )
        self.strategy.core_queue.put_nowait(
            Event(EventName.SENTINEL, content=SentinelUpdate(sentinel="sentinel"))
        )
