import asyncio
from typing import Optional
from binance import BinanceSocketManager
from transitions.extensions.asyncio import AsyncMachine
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import (
    BinanceClient,
    SentinelUpdate,
)
from src.common.initialize_trading_environment import spot_prepare_producers
from src.strategies.spot.hp_manager import HpManager
from src.common.identifiers.spot import (
    AccountPosition,
    EventName,
    Event,
    ExecutionReport,
    SignalUpdate,
    State,
    TickerUpdate,
    StrategyConfig,
)

# logger = logging.getLogger("trading_system")


class TradingSystem:
    def __init__(
        self,
        system_id: str,
        client: BinanceClient,
        gui_handler: asyncio.Queue,
        config: StrategyConfig,
        strategy_logger: StrategyLogger,
        db: Database,
    ):
        self.system_id = system_id
        self.client = client
        self.config = config
        self.gui_handler = gui_handler
        self.strategy_logger = strategy_logger
        self.db = db
        self.binance_socket_manager = BinanceSocketManager(client=client)
        self.stop_producers_event = asyncio.Event()
        self.state_machine: Optional[AsyncMachine] = None
        self.strategy: Optional[HpManager] = None

    async def initialize_strategy(
        self, last_state: Optional[State], usdt_balance: float
    ):
        # Strategy initialization
        self.strategy = HpManager(
            client=self.client,
            gui_handler=self.gui_handler,
            logger=self.strategy_logger,
            config=self.config,
            balance=usdt_balance,
            db=self.db,
        )

        self.strategy_logger.info("Config status: %s", last_state)

        if last_state is not None:
            self.strategy_logger.debug(
                "Old status is not None: %s, moving strategy state to recovering",
                last_state,
            )
            self.strategy.state = State.RECOVERING
            self.strategy.position_handler.last_state = last_state

        # Trading State Machine initialization
        self.state_machine = AsyncMachine(
            model=self.strategy,
            states=self.strategy.states,
            transitions=self.strategy.transitions,
            initial=self.strategy.state,
            send_event=True,
            queued=True,
        )

    async def worker(self, logger: StrategyLogger):
        if self.state_machine:
            assert isinstance(self.state_machine.model, HpManager)
            logger.debug(
                "Worker sleep 5 secs before starting, so the sockets can start"
            )
            await asyncio.sleep(5)
            logger.debug("Worker start now, state: %s.", self.state_machine.model.state)
            while True:
                event = await self.state_machine.model.queue.get()
                assert isinstance(event, Event)

                logger.debug("New event: %s", event)

                if EventName.TICKER == event.name:
                    assert isinstance(event.content, TickerUpdate)
                    self.state_machine.model.ticker_update = event.content
                    if self.state_machine.model.state == State.RECOVERING:
                        await self.state_machine.model.process_recovery()  # type: ignore
                    else:
                        await self.state_machine.model.process_ticker()  # type: ignore

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

                self.state_machine.model.queue.task_done()

    async def start_trading(self):
        await asyncio.gather(
            *spot_prepare_producers(
                socket_manager=self.binance_socket_manager,
                stop_event=self.stop_producers_event,
                queue=self.strategy.queue,
                ui_queue=self.gui_handler,
                symbol_info=self.config.symbol_info,
            ),
            asyncio.create_task(self.worker(logger=self.strategy_logger)),
            return_exceptions=True,
        )

    async def stop(self):
        # This method stops the trading. You'll have to implement this based on how your strategy can be stopped.
        # It might involve cancelling the tasks that were started in `start`.
        self.strategy_logger.info(
            "Closing trading system: %s", self.strategy.config.system_id
        )
        await self.strategy.queue.put(
            Event(EventName.SENTINEL, content=SentinelUpdate(sentinel="sentinel"))
        )
        await asyncio.sleep(5)
        self.stop_producers_event.set()
