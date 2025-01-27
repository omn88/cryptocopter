import asyncio
import datetime
import logging
import queue
from binance.enums import (
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELED,
)
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
        strategy_state: State,
        buy_state: StateInfo,
    ) -> None:
        logger.info("Entering strategy recovery.")
        self.strategy = HpManager(
            client=self.client,
            ui_queue=self.ui_queue,
            logger=self.strategy_logger,
            buy_config=buy_config,
            state_info=buy_state,
            balance=usdt_balance,
            db=self.db,
            core_queue=self.core_queue,
            config_queue=self.config_queue,
        )
        self.strategy.state = strategy_state
        self.strategy.buy_position.state_info = buy_state
        # Trading State Machine initialization
        self.state_machine = AsyncMachine(
            model=self.strategy,
            states=self.strategy.states,
            transitions=self.strategy.transitions,
            initial=self.strategy.state,
            send_event=True,
            queued=True,
        )

        # Restore orders for buy position
        orders = self.db.run_db_task(
            self.db.fetch_orders_for_price_level(
                hp_id=buy_config.hp_id, side=PositionSide.LONG.value
            )
        )
        logger.info("Orders for HP: %s, %s", buy_config.hp_id, orders)
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

        # Confirm buy position state with the exchange

        for order in self.strategy.buy_position.orders:
            if order.status not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
                # Retrieve the latest order information from the API
                resp = await self.client.get_order(
                    symbol=buy_config.symbol_info.symbol, orderId=order.order_id
                )
                latest_status = resp["status"]
                latest_realized_quantity = float(resp["executedQty"])

                # Check if status or realized quantity has changed
                status_changed = latest_status != order.status
                quantity_changed = latest_realized_quantity != order.realized_quantity

                if status_changed or quantity_changed:
                    # Send a message to the appropriate queue

                    ex_report = ExecutionReport(
                        symbol=buy_config.symbol_info.symbol,
                        quantity=order.quantity,
                        price=order.price,
                        current_order_status=latest_status,
                        order_id=order.order_id,
                        cumulative_filled_quantity=latest_realized_quantity,
                    )

                    self.core_queue.put_nowait(
                        Event(
                            name=EventName.EXECUTION_REPORT,
                            content=ex_report,
                        )
                    )
                    logger.info(
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    logger.info("No changes detected for order %s.", order.order_id)

        if not self.strategy.buy_position.orders:
            self.strategy.buy_position.orders = (
                self.strategy.buy_position.order_handler.prepare_buy_orders(
                    config=buy_config
                )
            )
            logger.info(
                "No orders exist, prepared new: %s", self.strategy.buy_position.orders
            )

        # Restore orders for sell position
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

        for order in self.strategy.sell_position.orders:
            if order.status not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
                # Retrieve the latest order information from the API
                resp = await self.client.get_order(
                    symbol=buy_config.symbol_info.symbol, orderId=order.order_id
                )
                latest_status = resp["status"]
                latest_realized_quantity = float(resp["executedQty"])

                # Check if status or realized quantity has changed
                status_changed = latest_status != order.status
                quantity_changed = latest_realized_quantity != order.realized_quantity

                if status_changed or quantity_changed:
                    # Send a message to the appropriate queue

                    ex_report = ExecutionReport(
                        symbol=buy_config.symbol_info.symbol,
                        quantity=order.quantity,
                        price=order.price,
                        current_order_status=latest_status,
                        order_id=order.order_id,
                        cumulative_filled_quantity=latest_realized_quantity,
                    )

                    self.core_queue.put_nowait(
                        Event(
                            name=EventName.EXECUTION_REPORT,
                            content=ex_report,
                        )
                    )
                    logger.info(
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    logger.info("No changes detected for order %s.", order.order_id)

        # if not self.strategy.sell_position.orders:
        #     self.strategy.sell_position.order_handler.prepare_sell_orders(
        #         config=sell_config,
        #         buy_orders=self.strategy.buy_position.orders,
        #         sell_orders=[],
        #     )
        #     logger.info(
        #         "No orders exist, prepared new: %s", self.strategy.sell_position.orders
        #     )

        self.strategy.buy_position.state_info.generate_next_monitor_time()
        self.strategy.sell_position.state_info.generate_next_monitor_time()

        # Send buy position data
        if self.strategy.state in [
            State.BUYING,
            State.NEW,
            State.PARTIALLY_BOUGHT,
            State.SOLD_PART_BOUGHT,
            State.PART_SOLD_PART_BOUGHT,
        ]:
            buy_state.ui_state = (
                UiState.OPEN
                if self.strategy.state in [State.BUYING, State.SELLING]
                else UiState.STAGNATED
            )

            logger.info("ORDERS: %s", self.strategy.buy_position.orders)
            buy_state.completeness = round(
                sum(
                    order.realized_quantity
                    for order in self.strategy.buy_position.orders
                )
                / sum(order.quantity for order in self.strategy.buy_position.orders),
                2,
            )

            buy_pos_data = PositionData(
                config=buy_config,
                state_info=buy_state,
                hp_update=HPUpdate(
                    hp_id=buy_config.hp_id,
                    buy_price=buy_config.price_high,
                    asset=buy_config.symbol_info.symbol[:-4],
                    state=strategy_state,
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
                self.strategy.sell_position.state_info.ui_state = (
                    UiState.OPEN
                    if self.strategy.state in [State.BUYING, State.SELLING]
                    else UiState.STAGNATED
                )
                self.strategy.sell_position.state_info.completeness = round(
                    sum(
                        order.realized_quantity
                        for order in self.strategy.sell_position.orders
                    )
                    / sum(
                        order.quantity for order in self.strategy.sell_position.orders
                    ),
                    2,
                )

                sell_pos_data = PositionData(
                    config=sell_config,
                    state_info=self.strategy.sell_position.state_info,
                    hp_update=HPUpdate(
                        hp_id=sell_config.hp_id,
                        buy_price=sell_config.price_high,
                        asset=sell_config.symbol_info.symbol[:-4],
                        state=strategy_state,
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

                    self.state_machine.model.core_queue.task_done()
                except queue.Empty:
                    await asyncio.sleep(0.1)
