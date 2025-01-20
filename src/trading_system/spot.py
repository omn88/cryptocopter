import asyncio
import datetime
import logging
import queue
from typing import Optional
from transitions.extensions.asyncio import AsyncMachine
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, PositionSide
from src.gui.identifiers.spot import HPUpdate, PositionData
from src.strategies.spot.hp_manager import HpManager
from src.common.identifiers.spot import (
    AccountPosition,
    EventName,
    Event,
    ExecutionReport,
    HPConfig,
    Order,
    SignalUpdate,
    State,
    StateInfo,
    TickerUpdate,
    UiState,
)

logger = logging.getLogger("trading_system")


class TradingSystem:
    def __init__(
        self,
        client: BinanceClient,
        ui_queue: queue.Queue,
        core_queue: queue.Queue,
        config: HPConfig,
        strategy_logger: StrategyLogger,
        db: Database,
        config_queue: queue.Queue,
    ):
        self.client = client
        self.config = config
        self.ui_queue = ui_queue
        self.core_queue = core_queue
        self.strategy_logger = strategy_logger
        self.db = db
        self.config_queue = config_queue
        self.state_machine: Optional[AsyncMachine] = None
        self.strategy: Optional[HpManager] = None

    async def initialize_strategy(
        self, config: HPConfig, state_info: StateInfo, usdt_balance: float
    ):
        # Strategy initialization
        self.strategy = HpManager(
            client=self.client,
            ui_queue=self.ui_queue,
            logger=self.strategy_logger,
            buy_config=self.config,
            state_info=state_info,
            balance=usdt_balance,
            db=self.db,
            core_queue=self.core_queue,
            config_queue=self.config_queue,
        )

        self.strategy.buy_position.orders = (
            self.strategy.buy_position.order_handler.prepare_buy_orders(
                config=self.config
            )
        )
        self.strategy.buy_position.state_info.open_time = (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        self.strategy.buy_position.state_info.generate_next_monitor_time()

        self.strategy_logger.info("Config status: %s", state_info.state)

        # if state_info.last_state is not None:
        #     self.strategy_logger.debug(
        #         "Old status is not None: %s, moving strategy state to recovering",
        #         state_info.last_state,
        #     )
        #     self.strategy.state = State.RECOVERING
        #     self.strategy.position_handler.last_state = state_info.last_state

        # Trading State Machine initialization
        self.state_machine = AsyncMachine(
            model=self.strategy,
            states=self.strategy.states,
            transitions=self.strategy.transitions,
            initial=self.strategy.state,
            send_event=True,
            queued=True,
        )

        assert self.config.symbol_info.symbol.endswith(
            "USDT"
        ), "Symbol must end with 'USDT'"
        self.ui_queue.put_nowait(
            PositionData(
                config=config,
                state_info=state_info,
                hp_update=HPUpdate(
                    hp_id=self.config.hp_id,
                    buy_price=self.config.price_high,
                    asset=self.config.symbol_info.symbol[:-4],
                    state=State.NEW,
                ),
            )
        )

    async def recover_strategy(
        self,
        buy_config: HPConfig,
        sell_config: Optional[HPConfig],
        usdt_balance: float,
        state: State,
        buy_state: State,
    ) -> None:
        logger.info("Entering strategy recovery.")
        state_info = StateInfo(state=state)
        self.strategy = HpManager(
            client=self.client,
            ui_queue=self.ui_queue,
            logger=self.strategy_logger,
            buy_config=buy_config,
            state_info=state_info,
            balance=usdt_balance,
            db=self.db,
            core_queue=self.core_queue,
            config_queue=self.config_queue,
        )
        self.strategy.state = state_info.state
        self.strategy.buy_position.state_info.state = buy_state
        # Trading State Machine initialization
        self.state_machine = AsyncMachine(
            model=self.strategy,
            states=self.strategy.states,
            transitions=self.strategy.transitions,
            initial=self.strategy.state,
            send_event=True,
            queued=True,
        )

        orders = self.db.run_db_task(
            self.db.fetch_orders_for_price_level(
                hp_id=buy_config.hp_id, side=PositionSide.LONG.value
            )
        )
        order_list = []
        for order in orders:
            order_list.append(
                Order(
                    order_id=order["order_id"],
                    quantity=order["quantity"],
                    precision=buy_config.symbol_info.precision,
                    price_precision=buy_config.symbol_info.price_precision,
                    price=order["price"],
                    quantity_stable=order["quantity_stable"],
                    realized_quantity=order["realized_quantity"],
                    status=order["status"],
                )
            )
        self.strategy.buy_position.orders = order_list

        logger.info("Updated buy orders: %s.", order_list)

        # ToDO: CONFIRM WITH THE EXCHANGE!!!!

        orders = self.db.run_db_task(
            self.db.fetch_orders_for_price_level(
                hp_id=buy_config.hp_id, side=PositionSide.SHORT.value
            )
        )
        order_list = []
        for order in orders:
            order_list.append(
                Order(
                    order_id=order["order_id"],
                    quantity=order["quantity"],
                    precision=buy_config.symbol_info.precision,
                    price_precision=buy_config.symbol_info.price_precision,
                    price=order["price"],
                    quantity_stable=order["quantity_stable"],
                    realized_quantity=order["realized_quantity"],
                    status=order["status"],
                )
            )
        self.strategy.sell_position.orders = order_list

        logger.info("Updated sell orders: %s.", order_list)

        self.strategy.buy_position.state_info.generate_next_monitor_time()
        self.strategy.sell_position.state_info.generate_next_monitor_time()

        # Send buy position data
        if self.strategy.buy_position.state_info.state in [
            State.BUYING,
            State.NEW,
            State.PARTIALLY_BOUGHT,
            State.SOLD_PART_BOUGHT,
            State.PART_SOLD_PART_BOUGHT,
        ]:
            state_info.ui_state = (
                UiState.OPEN
                if self.strategy.state in [State.BUYING, State.SELLING]
                else UiState.STAGNATED
            )

            buy_pos_data = PositionData(
                config=buy_config,
                state_info=state_info,
                hp_update=HPUpdate(
                    hp_id=buy_config.hp_id,
                    buy_price=buy_config.price_high,
                    asset=buy_config.symbol_info.symbol[:-4],
                    state=state_info.state,
                ),
            )
            self.ui_queue.put_nowait(buy_pos_data)
            logger.info("Buy PositionData send to UI: %s.", buy_pos_data)

        if sell_config:
            # Send sell position data
            if self.strategy.sell_position.state_info.state in [
                State.SELLING,
                State.NEW,
                State.PARTIALLY_SOLD,
                State.PART_SOLD_PART_BOUGHT,
            ]:
                state_info.ui_state = (
                    UiState.OPEN
                    if self.strategy.state in [State.BUYING, State.SELLING]
                    else UiState.STAGNATED
                )

                sell_pos_data = PositionData(
                    config=sell_config,
                    state_info=state_info,
                    hp_update=HPUpdate(
                        hp_id=sell_config.hp_id,
                        buy_price=sell_config.price_high,
                        asset=sell_config.symbol_info.symbol[:-4],
                        state=state_info.state,
                    ),
                )
                self.ui_queue.put_nowait(sell_pos_data)
                logger.info("Sell PositionData send to UI: %s.", sell_pos_data)

        logger.info("Strategy position(s) restored")

    async def worker(self):
        if self.state_machine:
            assert isinstance(self.state_machine.model, HpManager)
            logger.info("Worker start now, state: %s.", self.state_machine.model.state)
            while True:
                try:
                    event = self.state_machine.model.core_queue.get_nowait()
                    assert isinstance(event, Event)

                    logger.info("New event: %s", event)

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

                    self.state_machine.model.core_queue.task_done()
                except queue.Empty:
                    await asyncio.sleep(0.1)
