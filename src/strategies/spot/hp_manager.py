from datetime import datetime, timedelta
import queue
from typing import Dict, List
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
)
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.spot import (
    AccountPosition,
    Event,
    EventName,
    ExecutionReport,
    Signal,
    SignalUpdate,
    State,
    StrategyConfig,
    TickerUpdate,
    Order,
)
from src.common.identifiers.common import (
    BinanceClient,
    PositionSide,
)
from src.gui.identifiers.spot import PositionData
from src.position_handler.spot import PositionHandler

STAGNATION_LIMIT = 8


class HpManager:
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        logger: StrategyLogger,
        balance: float,
        ui_queue: queue.Queue,
        core_queue: queue.Queue,
        db: Database,
    ):
        self.client = client
        self.logger = logger
        self.balance = balance
        self.db = db
        self.queue: queue.Queue = core_queue
        self.config = config
        self.position_handler = PositionHandler(
            client=client,
            strategy_logger=logger,
            config=config,
            ui_queue=ui_queue,
            db=db,
        )
        self.state = State.NEW

        self.states = [
            State.CLOSED,
            State.NEW,
            State.OPEN,
            State.RECOVERING,
            State.STAGNATED,
        ]

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.execution_report: ExecutionReport = ExecutionReport()
        self.ticker_update: TickerUpdate = TickerUpdate()
        self.account_position: AccountPosition = AccountPosition()

        self.transitions = self.get_transitions()

    def __str__(self):
        return (
            f"HpManager(client={self.client}, config={self.config}, "
            f"logger={self.logger}, "
            f"balance={self.balance}, state={self.state}, "
            f"position_handler={self.position_handler})"
        )

    def get_transitions(self):
        # add balance conditions where orders are to be send and update the variable after orders are cancelled.
        return [
            {
                "trigger": "process_recovery",
                "source": State.RECOVERING,
                "dest": State.NEW,
                "conditions": "conditions_for_recovering_to_new",
                "after": "handle_recovery_to_new",
            },
            {
                "trigger": "process_recovery",
                "source": State.RECOVERING,
                "dest": State.OPEN,
                "conditions": "conditions_for_recovering_to_open",
                "after": "handle_recovery_to_open",
            },
            {
                "trigger": "process_recovery",
                "source": State.RECOVERING,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_recovering_to_stagnated",
                "after": "handle_recovery_to_stagnated",
            },
            {
                "trigger": "process_account",
                "source": [
                    State.NEW,
                    State.OPEN,
                    State.STAGNATED,
                    State.RECOVERING,
                    State.CLOSED,
                ],
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [State.OPEN, State.STAGNATED],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "confirm_new_order",
            },
            {
                "trigger": "process_order",
                "source": [State.OPEN, State.STAGNATED],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "confirm_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "confirm_expired_order",
            },
            {
                "trigger": "process_signal",
                "source": State.OPEN,
                "dest": State.CLOSED,
                "conditions": "conditions_for_all_orders_filled",
                "before": "close_filled_position",
            },
            {
                "trigger": "process_order",
                "source": [State.NEW, State.OPEN],
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [State.NEW, State.OPEN],
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled",
                "before": "handle_order_partially_filled",
            },
            {
                "trigger": "process_ticker",
                "source": State.NEW,
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_buy_orders",
                "after": "send_buy_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.NEW,
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_sell_orders",
                "after": "send_sell_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.STAGNATED,
                "dest": State.OPEN,
                "conditions": "conditions_for_resending_buy_orders",
                "after": "resend_buy_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.STAGNATED,
                "dest": State.OPEN,
                "conditions": "conditions_for_resending_sell_orders",
                "after": "resend_sell_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_buy_orders",
                "after": "cancel_buy_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_sell_orders",
                "after": "cancel_sell_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_position_stagnation",
                "after": "increase_stagnation_counter",
            },
            {
                "trigger": "process_ticker",
                "source": State.CLOSED,
                "dest": "=",
                "after": "allow_messages",
            },
        ]

    def calculate_trigger_send_orders_price(self):
        return (
            self.config.symbol_info.adjust_price(
                self.config.price_low * (1 - (self.config.order_trigger / 100))
            )
            if self.config.side == PositionSide.SHORT
            else self.config.symbol_info.adjust_price(
                self.config.price_high * (1 + (self.config.order_trigger / 100))
            )
        )

    def calculate_trigger_cancel_orders_price(self):
        return (
            self.config.symbol_info.adjust_price(
                self.config.price_low * (1 - (2 * self.config.order_trigger / 100))
            )
            if self.config.side == PositionSide.SHORT
            else self.config.symbol_info.adjust_price(
                self.config.price_high * (1 + (2 * self.config.order_trigger / 100))
            )
        )

    def conditions_for_recovering_to_new(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.state == State.RECOVERING
            and self.position_handler.last_state == State.NEW
        )
        if condition:
            self.logger.info("[Recovering] %s to state NEW", self.config)
        return condition

    def conditions_for_recovering_to_open(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.state == State.RECOVERING
            and self.position_handler.last_state == State.OPEN
        )
        if condition:
            self.logger.info("[Recovering] %s to state OPEN", self.config)
        return condition

    def conditions_for_recovering_to_stagnated(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.state == State.RECOVERING
            and self.position_handler.last_state == State.STAGNATED
        )
        if condition:
            self.logger.info("[Recovering] %s to state STAGNATED", self.config)
        return condition

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type
            in [
                ORDER_TYPE_LIMIT,
                ORDER_TYPE_MARKET,
            ]
            and self.execution_report.current_order_status == ORDER_STATUS_NEW
            and self.execution_report.symbol == self.config.symbol_info.symbol
        )
        if condition:
            self.logger.info(
                "[New Order] %s, order type: %s order status: %s",
                self.execution_report.symbol,
                self.execution_report.order_type,
                self.execution_report.current_order_status,
            )
        return condition

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_CANCELED
            and self.execution_report.symbol == self.config.symbol_info.symbol
        )
        if condition:
            self.logger.info(
                "[Cancelled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    def conditions_for_order_expiration(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_EXPIRED
        )
        if condition:
            self.logger.info(
                "[Expired order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.position_handler.orders]
        )
        if condition:
            self.logger.info(
                "[Filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    def conditions_for_order_partially_filled(self, *args, **kwargs):
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status
            == ORDER_STATUS_PARTIALLY_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.position_handler.orders]
        )
        if condition:
            self.logger.info(
                "[Partially filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    def conditions_for_all_orders_filled(self, *args, **kwargs):
        condition = (
            self.state == State.OPEN
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.position_handler.orders
            )
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            self.logger.info(
                "[All orders filled] %s %s",
                self.config.symbol_info.symbol,
                self.config.side,
            )
        return condition

    def conditions_for_sending_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.NEW
            and self.config.side == PositionSide.LONG
            and self.ticker_update.last_price
            <= self.calculate_trigger_send_orders_price()
            and self.balance > self.config.budget
        )
        if condition:
            self.logger.info(
                "[Send buy orders] %s, side: %s, state: %s, budget: %s, balance: %s",
                self.config.symbol_info.symbol,
                self.config.side,
                self.state,
                self.config.budget,
                self.balance,
            )

        return condition

    def get_remaining_quantity(self, *args, **kwargs) -> float:
        rem_quant = 0.0
        for order in self.position_handler.orders:
            rem_quant += order.quantity_stable - order.quantity_stable * (
                order.realized_quantity / order.quantity
            )
        self.logger.debug(
            "Remaining quantity: %s for %s",
            rem_quant,
            self.config.symbol_info.symbol,
        )
        return rem_quant

    def conditions_for_resending_buy_orders(self, *args, **kwargs) -> bool:
        remaining_quant = self.get_remaining_quantity()
        condition = (
            self.state == State.STAGNATED
            and self.config.side == PositionSide.LONG
            and self.ticker_update.last_price
            <= self.calculate_trigger_send_orders_price()
            and self.balance > remaining_quant
        )
        if condition:
            self.logger.info(
                "[Resend buy orders] %s, state: %s, balance: %s, remaining quantity: %s",
                self.config.symbol_info.symbol,
                self.state,
                self.balance,
                remaining_quant,
            )

        return condition

    def conditions_for_sending_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.NEW
            and self.config.side == PositionSide.SHORT
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price()
            and self.balance > self.config.budget
        )
        if condition:
            self.logger.info(
                "[Send sell orders] %s, side: %s, state: %s, budget: %s, balance: %s",
                self.config.symbol_info.symbol,
                self.config.side,
                self.state,
                self.config.budget,
                self.balance,
            )

        return condition

    def conditions_for_resending_sell_orders(self, *args, **kwargs) -> bool:
        remaining_quant = self.get_remaining_quantity()
        condition = (
            self.state == State.STAGNATED
            and self.config.side == PositionSide.SHORT
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price()
            and self.balance > remaining_quant
        )
        if condition:
            self.logger.info(
                "[Resend sell orders] %s, state: %s, balance: %s, remaining quantity: %s",
                self.config.symbol_info.symbol,
                self.state,
                self.balance,
                remaining_quant,
            )

        return condition

    def conditions_for_cancelling_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.config.side == PositionSide.LONG
            and self.position_handler.stagnation_counter >= STAGNATION_LIMIT
            and self.ticker_update.last_price
            > self.calculate_trigger_cancel_orders_price()
        )
        if condition:
            self.logger.info(
                "[Stagnation Cancel BUY] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.config.symbol_info.symbol,
                self.position_handler.stagnation_counter,
                STAGNATION_LIMIT,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price(),
            )

        return condition

    def conditions_for_cancelling_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.config.side == PositionSide.SHORT
            and self.position_handler.stagnation_counter >= STAGNATION_LIMIT
            and self.ticker_update.last_price
            < self.calculate_trigger_cancel_orders_price()
        )
        if condition:
            self.logger.info(
                "[Stagnation Cancel SELL] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.config.symbol_info.symbol,
                self.position_handler.stagnation_counter,
                STAGNATION_LIMIT,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price(),
            )

        return condition

    def conditions_for_position_stagnation(self, *args, **kwargs) -> bool:
        date_time_now = datetime.now()

        condition = self.state == State.OPEN and date_time_now > datetime.strptime(
            self.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
        )
        if condition:
            self.logger.info(
                "[Handle stagnation]: %s, time now: %s, monitor time: %s",
                condition,
                date_time_now,
                self.position_handler.next_monitor_position_time,
            )

        return condition

    async def send_buy_orders(self, *args, **kwargs) -> None:
        self.balance -= self.config.budget

        await self.position_handler.open_position(
            side=self.config.side,
            symbol_info=self.config.symbol_info,
        )

    async def resend_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info(
            "Resending %s %s", self.config.symbol_info.symbol, self.config.side.value
        )
        self.balance -= self.get_remaining_quantity()
        new_orders = []

        for order in self.position_handler.orders:
            if order.status != ORDER_STATUS_FILLED:
                order = Order(
                    quantity=self.config.symbol_info.adjust_quantity(
                        order.quantity - order.realized_quantity
                    ),
                    price=self.config.symbol_info.adjust_price(order.price),
                    quantity_stable=round(
                        (order.quantity - order.realized_quantity) * order.price, 2
                    ),
                    precision=self.config.symbol_info.precision,
                    price_precision=self.config.symbol_info.price_precision,
                )
                new_orders.append(order)
                self.logger.info("New order prepared: %s", order)

        self.position_handler.orders = new_orders

        await self.position_handler.order_handler.create_orders(
            side=self.config.side,
            symbol_info=self.config.symbol_info,
            orders=self.position_handler.orders,
        )
        self.state = State.OPEN

        self.logger.info("Will update orders: %s", self.position_handler.orders)

        for order in self.position_handler.orders:
            await self.db.update_order(
                price=order.price,
                quantity=order.quantity,
                quantity_stable=order.quantity_stable,
                realized_quantity=order.realized_quantity,
                time_in_force=order.time_in_force,
                status=order.status,
                order_type=order.order_type,
                order_id=order.order_id,
                price_level_id=self.config.system_id,
            )
        await self.db.update_price_level(
            self.config,
            state=self.state,
            stagnation_counter=self.position_handler.stagnation_counter,
            next_monitor_time=self.position_handler.next_monitor_position_time,
        )

        self.position_handler.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.position_handler.stagnation_counter,
                completeness=round(
                    sum(
                        order.realized_quantity
                        for order in self.position_handler.orders
                    )
                    / sum(order.quantity for order in self.position_handler.orders),
                    2,
                ),
                state=self.state,
            )
        )

    async def resend_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info(
            "Resending %s %s", self.config.symbol_info.symbol, self.config.side.value
        )
        self.balance -= self.get_remaining_quantity()
        new_orders = []

        for order in self.position_handler.orders:
            if order.status != ORDER_STATUS_FILLED:
                order = Order(
                    quantity=self.config.symbol_info.adjust_quantity(
                        order.quantity - order.realized_quantity
                    ),
                    price=self.config.symbol_info.adjust_price(order.price),
                    quantity_stable=round(
                        (order.quantity - order.realized_quantity) * order.price, 2
                    ),
                    precision=self.config.symbol_info.precision,
                    price_precision=self.config.symbol_info.price_precision,
                )
                new_orders.append(order)
                self.logger.info("New order prepared: %s", order)

        self.position_handler.orders = new_orders

        await self.position_handler.order_handler.create_orders(
            side=self.config.side,
            symbol_info=self.config.symbol_info,
            orders=self.position_handler.orders,
        )
        self.state = State.OPEN

        for order in self.position_handler.orders:
            await self.db.update_order(
                price=order.price,
                quantity=order.quantity,
                quantity_stable=order.quantity_stable,
                realized_quantity=order.realized_quantity,
                time_in_force=order.time_in_force,
                status=order.status,
                order_type=order.order_type,
                order_id=order.order_id,
                price_level_id=self.config.system_id,
            )
        await self.db.update_price_level(
            config=self.config,
            state=self.state,
            stagnation_counter=self.position_handler.stagnation_counter,
            next_monitor_time=self.position_handler.next_monitor_position_time,
        )

        self.position_handler.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.position_handler.stagnation_counter,
                completeness=round(
                    sum(
                        order.realized_quantity
                        for order in self.position_handler.orders
                    )
                    / sum(order.quantity for order in self.position_handler.orders),
                    2,
                ),
                state=self.state,
            )
        )

    async def send_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info(
            "Opening %s %s", self.config.symbol_info.symbol, self.config.side.value
        )
        self.balance -= self.config.budget

        await self.position_handler.open_position(
            side=self.config.side,
            symbol_info=self.config.symbol_info,
        )

    async def cancel_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.config.side.value)
        self.state = State.STAGNATED
        self.logger.info("Orders: %s", self.position_handler.orders)
        self.balance += self.get_remaining_quantity()
        await self.position_handler.cancel_position(state=self.state)

    async def cancel_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.config.side.value)
        self.state = State.STAGNATED
        self.balance += self.get_remaining_quantity()
        await self.position_handler.cancel_position(state=self.state)

    async def close_filled_position(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")
        self.state = State.CLOSED

        self.position_handler.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.position_handler.stagnation_counter,
                completeness=round(
                    sum(
                        order.realized_quantity
                        for order in self.position_handler.orders
                    )
                    / sum(order.quantity for order in self.position_handler.orders),
                    2,
                ),
                state=self.state,
            )
        )

        await self.position_handler.db.update_price_level(
            config=self.config,
            state=self.state,
            stagnation_counter=self.position_handler.stagnation_counter,
            next_monitor_time=self.position_handler.next_monitor_position_time,
        )

    async def increase_stagnation_counter(self, *args, **kwargs) -> None:
        self.position_handler.stagnation_counter += 1

        if self.position_handler.stagnation_counter < STAGNATION_LIMIT:
            self.logger.info(
                "[%s]: stagnation counter increase to: %s, stagnation limit: %s",
                self.config.system_id,
                self.position_handler.stagnation_counter,
                STAGNATION_LIMIT,
            )
        else:
            self.logger.info(
                "[%s]: Stagnation limit reached, current price: %s, order cancel price: %s",
                self.config.system_id,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price(),
            )
        time_date = datetime.strptime(
            self.position_handler.next_monitor_position_time, "%Y-%m-%d %H:%M:%S"
        )
        time_date += timedelta(hours=1)
        self.position_handler.next_monitor_position_time = time_date.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        self.position_handler.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.position_handler.stagnation_counter,
                completeness=round(
                    sum(
                        order.realized_quantity
                        for order in self.position_handler.orders
                    )
                    / sum(order.quantity for order in self.position_handler.orders),
                    2,
                ),
                state=self.state,
            )
        )

        await self.position_handler.db.update_price_level(
            config=self.config,
            state=self.state,
            stagnation_counter=self.position_handler.stagnation_counter,
            next_monitor_time=self.position_handler.next_monitor_position_time,
        )

    async def confirm_new_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "New order confirmation: %s", self.execution_report.order_id
                )

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Cancelled order confirmation: %s", self.execution_report.order_id
                )

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Expired order confirmation: %s", self.execution_report.order_id
                )

    async def handle_account(self, *args, **kwargs):
        for balance in self.account_position.balances:
            if balance.asset == "USDT":
                self.balance = round(balance.free, 2)
        self.logger.debug("Account update: %s", self.account_position)

    async def handle_order_filled(self, *args, **kwargs):
        self.logger.debug("Entering handle order filled")

        await self.position_handler.handle_order_filled(
            execution_report=self.execution_report
        )

        if all(
            order.status == ORDER_STATUS_FILLED
            for order in self.position_handler.orders
        ):
            signal = Signal.HP_ALL_ORDERS_FILLED
            self.logger.info("All orders filled, sending: %s", signal)
            self.queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.debug("Entering handle order partially filled")

        await self.position_handler.handle_order_partially_filled(
            execution_report=self.execution_report
        )

    async def handle_recovery_to_new(self, *args, **kwargs) -> None:
        self.logger.debug("Handle recovery to new, just put to IDLE in GUI")

        self.position_handler.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=0,
                completeness=0,
                recovering=True,
                state=State.NEW,
            )
        )

    async def handle_recovery_to_open(self, *args, **kwargs) -> None:
        self.logger.debug("Handle recovery to open")

        orders_from_db: List[Dict] = await self.db.fetch_orders_for_price_level(
            price_level_id=self.config.system_id
        )
        self.logger.debug(
            "Fetched orders from DB for price level: %s: \n%s",
            self.config.system_id,
            orders_from_db,
        )

        orders = [
            Order(
                quantity=float(order["quantity"]),
                realized_quantity=float(order["realized_quantity"]),
                precision=0,
                price_precision=0,
                price=float(order["price"]),
                order_id=int(order["order_id"]),
            )
            for order in orders_from_db
        ]

        for order in self.position_handler.orders:
            for db_order in orders:
                if order.price == db_order.price:
                    order.realized_quantity = db_order.realized_quantity
                    order.order_id = db_order.order_id
                    order.open_time = db_order.open_time
                    order.status = db_order.status

        updated_orders = [
            await self.position_handler.order_handler.update_order_status(
                symbol=self.config.symbol_info.symbol, order=order
            )
            for order in orders
        ]
        self.logger.debug(
            "Fetched orders from Binance for price level: %s: \n%s",
            self.config.system_id,
            updated_orders,
        )

        for order in self.position_handler.orders:
            for updated_order in updated_orders:
                if order.order_id == updated_order.order_id:
                    if order.realized_quantity != updated_order.realized_quantity:
                        self.logger.info(
                            "Order quantity has changed during outage, old: %s, new: %s",
                            order.realized_quantity,
                            updated_order.realized_quantity,
                        )

                        order.realized_quantity = updated_order.realized_quantity
                        order.status = updated_order.status

                        await self.db.update_order(
                            price=order.price,
                            quantity=order.quantity,
                            quantity_stable=order.quantity_stable,
                            realized_quantity=order.realized_quantity,
                            time_in_force=order.time_in_force,
                            status=order.status,
                            order_type=order.order_type,
                            order_id=order.order_id,
                            price_level_id=self.config.system_id,
                        )

                        if all(
                            order.status == ORDER_STATUS_FILLED
                            for order in self.position_handler.orders
                        ):
                            signal = Signal.HP_ALL_ORDERS_FILLED
                            self.logger.info("All orders filled, sending: %s", signal)
                            self.queue.put(
                                Event(
                                    name=EventName.SIGNAL,
                                    content=SignalUpdate(signal=signal),
                                )
                            )

        self.position_handler.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.position_handler.stagnation_counter,
                completeness=round(
                    sum(
                        order.realized_quantity
                        for order in self.position_handler.orders
                    )
                    / sum(order.quantity for order in self.position_handler.orders),
                    2,
                ),
                recovering=True,
                state=State.OPEN,
            )
        )

    async def handle_recovery_to_stagnated(self, *args, **kwargs) -> None:
        self.logger.debug("Handle recovery to stagnated")

        orders_from_db = await self.db.fetch_orders_for_price_level(
            price_level_id=self.config.system_id
        )
        self.logger.debug(
            "Fetched orders for price level: %s: \n%s",
            self.config.system_id,
            orders_from_db,
        )
        orders = [
            Order(
                quantity=float(order["quantity"]),
                realized_quantity=float(order["realized_quantity"]),
                precision=0,
                price_precision=0,
                price=float(order["price"]),
                order_id=int(order["order_id"]),
            )
            for order in orders_from_db
        ]

        for order in self.position_handler.orders:
            for fetched_order in orders:
                if order.price == fetched_order.price:
                    order.order_id = fetched_order.order_id
                    order.realized_quantity = fetched_order.realized_quantity
                    order.status = fetched_order.status

        self.position_handler.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.position_handler.stagnation_counter,
                completeness=round(
                    sum(
                        order.realized_quantity
                        for order in self.position_handler.orders
                    )
                    / sum(order.quantity for order in self.position_handler.orders),
                    2,
                ),
                state=State.STAGNATED,
            )
        )

    async def allow_messages(self, *args, **kwargs) -> None:
        self.logger.info(
            "Ticker update from allow messages method: %s",
            self.ticker_update.last_price,
        )
