from datetime import datetime, timedelta
import queue
from typing import Optional
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
    HPConfig,
    Signal,
    SignalUpdate,
    State,
    StateInfo,
    TickerUpdate,
    Order,
)
from src.common.identifiers.common import (
    BinanceClient,
    PositionSide,
)
from src.gui.identifiers.spot import PositionData
from src.position_handler.spot import PositionHandler


class HpManager:
    def __init__(
        self,
        client: BinanceClient,
        config: HPConfig,
        state_info: StateInfo,
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
        self.core_queue: queue.Queue = core_queue
        self.buy_position = PositionHandler(
            client=client,
            strategy_logger=logger,
            config=config,
            ui_queue=ui_queue,
            db=db,
            state_info=state_info,
        )
        self.sell_position: PositionHandler = PositionHandler(
            client=client,
            strategy_logger=logger,
            config=HPConfig(
                symbol_info=self.buy_position.config.symbol_info,
                hp_id=self.buy_position.config.hp_id,
            ),
            ui_queue=ui_queue,
            db=db,
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.state = State.NEW

        self.states = [
            State.NEW,
            State.BUYING,
            State.PARTIALLY_BOUGHT,
            State.BOUGHT,
            State.READY_TO_SELL,
            State.SELLING,
            State.PARTIALLY_SOLD,
            State.SOLD,
            State.RECOVERING,
        ]

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.execution_report: ExecutionReport = ExecutionReport()
        self.ticker_update: TickerUpdate = TickerUpdate()
        self.account_position: AccountPosition = AccountPosition()

        self.transitions = self.get_transitions()

    def get_transitions(self):
        return [
            {
                # No 1
                "trigger": "process_ticker",
                "source": State.NEW,
                "dest": State.BUYING,
                "conditions": "conditions_for_sending_buy_orders",
                "after": "send_buy_orders",
            },
            {
                # No 2
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.NEW,
                "conditions": "conditions_for_cancelling_unfilled_buy_orders",
                "after": "cancel_unfilled_buy_orders",
            },
            {
                # No 3
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.PARTIALLY_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_bought_orders",
                "after": "cancel_partially_bought_orders",
            },
            {
                # No 4
                "trigger": "process_ticker",
                "source": State.PARTIALLY_BOUGHT,
                "dest": State.BUYING,
                "conditions": "conditions_for_resending_partially_bought_position",
                "after": "resend_buy_orders",
            },
            {
                # No 5
                "trigger": "process_ticker",
                "source": State.PARTIALLY_BOUGHT,
                "dest": State.SELLING,
                "conditions": "conditions_for_sending_sell_orders_for_partially_bought_position",
                "after": "send_sell_orders",
            },
            {
                # No 6
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.PARTIALLY_BOUGHT,
                "conditions": "conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position",
                "after": "cancel_unfilled_sell_orders",
            },
            {
                # No 7
                "trigger": "process_signal",
                "source": State.BUYING,
                "dest": State.BOUGHT,
                "conditions": "conditions_for_all_orders_filled_buy",
                "before": "close_filled_position_buy",
            },
            {
                # No 8
                "trigger": "process_ticker",
                "source": State.BOUGHT,
                "dest": State.SELLING,
                "conditions": "conditions_for_sending_sell_orders",
                "before": "send_sell_orders",
            },
            {
                # No 9
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.BOUGHT,
                "conditions": "conditions_for_cancelling_unfilled_sell_orders",
                "before": "cancel_unfilled_sell_orders",
            },
            {
                # No 10
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.PARTIALLY_SOLD,
                "conditions": "conditions_for_cancelling_partially_sold_orders",
                "after": "cancel_partially_sold_orders",
            },
            {
                # No 11
                "trigger": "process_ticker",
                "source": State.PARTIALLY_SOLD,
                "dest": State.SELLING,
                "conditions": "conditions_for_resending_partially_sold_orders",
                "after": "resend_sell_orders",
            },
            {
                # No 12
                "trigger": "process_signal",
                "source": State.SELLING,
                "dest": State.SOLD,
                "conditions": "conditions_for_all_orders_filled_sell",
                "before": "close_filled_position_sell",
            },
            {
                # No 13
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.PART_SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_sold_and_bought_orders_sell_position",
                "after": "cancel_sell_part_sold_part_bought",
            },
            {
                # No 14
                "trigger": "process_signal",
                "source": State.PART_SOLD_PART_BOUGHT,
                "dest": State.SELLING,
                "conditions": "conditions_for_resending_sell_orders_from_part_sold_and_bought_orders",
                "before": "resend_sell_orders",
            },
            {
                # No 15
                "trigger": "process_ticker",
                "source": State.PART_SOLD_PART_BOUGHT,
                "dest": State.BUYING,
                "conditions": "conditions_for_resending_buy_orders_from_part_sold_and_bought_orders",
                "after": "resend_buy_orders",
            },
            {
                # No 16
                "trigger": "process_signal",
                "source": State.BUYING,
                "dest": State.PART_SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_sold_and_bought_orders_buy_position",
                "before": "cancel_partially_bought_orders",
            },
            {
                # No 17
                "trigger": "process_signal",
                "source": State.BUYING,
                "dest": State.PARTIALLY_SOLD,
                "conditions": "conditions_for_buying_fully_previously_partially_sold_position",
                "before": "close_filled_position_buy",
            },
            {
                # No 18
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.SOLD_PART_BOUGHT,
                "conditions": "conditions_for_closing_sold_position_which_is_part_bought",
                "after": "close_sold_position_which_is_part_bought",
            },
            {
                # No 19
                "trigger": "process_ticker",
                "source": State.SOLD_PART_BOUGHT,
                "dest": State.BUYING,
                "conditions": "conditions_for_resending_buy_orders_for_sold_position",
                "after": "resend_buy_orders",
            },
            {
                # No 20
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_buy_orders_to_sold_part_bought",
                "after": "cancel_partially_bought_orders",
            },
            {
                "trigger": "process_order",
                "source": State.BUYING,
                "dest": "=",
                "conditions": "conditions_for_order_filled_buy",
                "before": "handle_order_filled_buy",
            },
            {
                "trigger": "process_order",
                "source": State.BUYING,
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled_buy",
                "before": "handle_order_partially_filled_buy",
            },
            {
                "trigger": "process_order",
                "source": State.SELLING,
                "dest": "=",
                "conditions": "conditions_for_order_filled_sell",
                "before": "handle_order_filled_sell",
            },
            {
                "trigger": "process_order",
                "source": State.SELLING,
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled_sell",
                "before": "handle_order_partially_filled_sell",
            },
            {
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": "=",
                "conditions": "conditions_for_position_stagnation_buy",
                "after": "increase_stagnation_counter_buy",
            },
            {
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": "=",
                "conditions": "conditions_for_position_stagnation_sell",
                "after": "increase_stagnation_counter_sell",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "confirm_new_order",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "confirm_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "confirm_expired_order",
            },
        ]

    def calculate_trigger_send_orders_price_buy(self):
        price = 0

        for order in self.buy_position.orders:
            if order.status != ORDER_STATUS_FILLED:
                price = max(price, order.price)

        return self.buy_position.config.symbol_info.adjust_price(
            price * (1 + (self.buy_position.config.order_trigger / 100))
        )

    def get_remaining_quantity_buy(self, *args, **kwargs) -> float:
        rem_quant = 0.0
        for order in self.buy_position.orders:
            rem_quant += order.quantity_stable - order.quantity_stable * (
                order.realized_quantity / order.quantity
            )
        self.logger.debug(
            "Remaining quantity: %s for %s",
            rem_quant,
            self.buy_position.config.symbol_info.symbol,
        )
        return rem_quant

    def conditions_for_sending_buy_orders(self, *args, **kwargs) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_buy()
        condition = (
            self.state == State.NEW
            and all(
                order.status == ORDER_STATUS_NEW for order in self.buy_position.orders
            )
            and self.buy_position.state_info.state == State.NEW
            and self.ticker_update.last_price <= trigger_send_orders_price
            and self.balance > self.buy_position.config.budget
        )
        if condition:
            self.logger.info(
                "[Send buy orders] %s, side: %s, state: %s, budget: %s, balance: %s, price trigger: %s last price: %s",
                self.buy_position.config.symbol_info.symbol,
                self.buy_position.state_info.side,
                self.state,
                self.buy_position.config.budget,
                self.balance,
                trigger_send_orders_price,
                self.ticker_update.last_price,
            )

        return condition

    async def send_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Sending %s BUY", self.buy_position.config.symbol_info.symbol)
        self.balance -= self.get_remaining_quantity_buy()

        self.buy_position.order_handler.prepare_buy_orders(
            config=self.buy_position.config
        )

        await self.buy_position.order_handler.create_orders(
            side=self.buy_position.state_info.side,
            symbol_info=self.buy_position.config.symbol_info,
            orders=self.buy_position.orders,
        )
        self.state = State.BUYING
        self.buy_position.state_info.state = State.NEW

        self.logger.info("Will update orders: %s", self.buy_position.orders)

        for order in self.buy_position.orders:
            self.db.run_db_task(
                self.db.update_order(
                    price=order.price,
                    quantity=order.quantity,
                    quantity_stable=order.quantity_stable,
                    realized_quantity=order.realized_quantity,
                    time_in_force=order.time_in_force,
                    status=order.status,
                    order_type=order.order_type,
                    order_id=order.order_id,
                    hp_id=str(self.buy_position.config.hp_id),
                )
            )
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

        self.buy_position.ui_queue.put_nowait(
            PositionData(
                config=self.buy_position.config,
                state_info=self.buy_position.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.buy_position.orders)
                    / sum(order.quantity for order in self.buy_position.orders),
                    2,
                ),
            )
        )

    def conditions_for_cancelling_unfilled_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.buy_position.state_info.stagnation_counter
            >= self.buy_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            >= self.calculate_trigger_cancel_orders_price_buy()
            and all(
                order.status == ORDER_STATUS_NEW for order in self.buy_position.orders
            )
        )
        if condition:
            self.logger.info(
                "[Cancel Unfilled BUY] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.buy_position.config.symbol_info.symbol,
                self.buy_position.state_info.stagnation_counter,
                self.buy_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_buy(),
            )

        return condition

    async def cancel_unfilled_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.buy_position.state_info.side.value)
        self.logger.info("Orders: %s", self.buy_position.orders)
        self.balance += self.get_remaining_quantity_buy()
        await self.buy_position.cancel_position()
        self.buy_position.state_info = StateInfo()

    def conditions_for_cancelling_partially_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.stagnation_counter
            >= self.buy_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            >= self.calculate_trigger_cancel_orders_price_buy()
            and not all(
                order.status == ORDER_STATUS_NEW for order in self.buy_position.orders
            )
        )
        if condition:
            self.logger.info(
                "[Cancel Partially Filled BUY] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.buy_position.config.symbol_info.symbol,
                self.buy_position.state_info.stagnation_counter,
                self.buy_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_buy(),
            )

        return condition

    async def cancel_partially_bought_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.buy_position.state_info.side.value)
        self.logger.info("Orders: %s", self.buy_position.orders)
        self.balance += self.get_remaining_quantity_buy()
        await self.buy_position.cancel_position()
        self.buy_position.state_info.state = State.PARTIALLY_BOUGHT

    def conditions_for_resending_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_buy()
        condition = (
            self.state == State.PARTIALLY_BOUGHT
            and self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.ticker_update.last_price <= trigger_send_orders_price
            and self.balance > self.buy_position.config.budget
        )
        if condition:
            self.logger.info(
                "[Send buy orders] %s, side: %s, state: %s, budget: %s, balance: %s, price trigger: %s last price: %s",
                self.buy_position.config.symbol_info.symbol,
                self.buy_position.state_info.side,
                self.state,
                self.buy_position.config.budget,
                self.balance,
                trigger_send_orders_price,
                self.ticker_update.last_price,
            )

        return condition

    async def resend_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info(
            "Resending %s BUY", self.buy_position.config.symbol_info.symbol
        )
        self.balance -= self.get_remaining_quantity_buy()
        new_orders = []

        await self.buy_position.order_handler.create_orders(
            side=self.buy_position.state_info.side,
            symbol_info=self.buy_position.config.symbol_info,
            orders=self.buy_position.orders,
        )
        self.state = State.BUYING
        self.buy_position.state_info.state = State.PARTIALLY_BOUGHT

        self.logger.info("Will update orders: %s", self.buy_position.orders)

        for order in self.buy_position.orders:
            self.db.run_db_task(
                self.db.update_order(
                    price=order.price,
                    quantity=order.quantity,
                    quantity_stable=order.quantity_stable,
                    realized_quantity=order.realized_quantity,
                    time_in_force=order.time_in_force,
                    status=order.status,
                    order_type=order.order_type,
                    order_id=order.order_id,
                    hp_id=str(self.buy_position.config.hp_id),
                )
            )
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

        self.buy_position.ui_queue.put_nowait(
            PositionData(
                config=self.buy_position.config,
                state_info=self.buy_position.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.buy_position.orders)
                    / sum(order.quantity for order in self.buy_position.orders),
                    2,
                ),
            )
        )

    def calculate_trigger_send_orders_price_sell(self):
        return self.sell_position.config.symbol_info.adjust_price(
            self.sell_position.config.price_low
            * (1 - (self.sell_position.config.order_trigger / 100))
        )

    def conditions_for_sending_sell_orders_from_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.NEW
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Send sell orders] hp id: %s, %s, side: %s, state: %s, budget: %s",
                self.sell_position.config.hp_id,
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.side,
                self.sell_position.state_info.state,
                self.sell_position.config.budget,
            )

        return condition

    async def send_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info(
            "Sending %s SELL", self.sell_position.config.symbol_info.symbol
        )

        self.sell_position.order_handler.prepare_sell_orders(
            config=self.buy_position.config,
            buy_orders=self.buy_position.orders,
            sell_orders=self.sell_position.orders,
        )

        await self.sell_position.order_handler.create_orders(
            side=self.sell_position.state_info.side,
            symbol_info=self.sell_position.config.symbol_info,
            orders=self.sell_position.orders,
        )
        self.state = State.SELLING

        for order in self.sell_position.orders:
            self.db.run_db_task(
                self.db.update_order(
                    price=order.price,
                    quantity=order.quantity,
                    quantity_stable=order.quantity_stable,
                    realized_quantity=order.realized_quantity,
                    time_in_force=order.time_in_force,
                    status=order.status,
                    order_type=order.order_type,
                    order_id=order.order_id,
                    hp_id=str(self.sell_position.config.hp_id),
                )
            )
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

        self.sell_position.ui_queue.put_nowait(
            PositionData(
                config=self.sell_position.config,
                state_info=self.sell_position.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.sell_position.orders)
                    / sum(order.quantity for order in self.sell_position.orders),
                    2,
                ),
            )
        )

    def conditions_for_all_orders_filled_buy(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.BUYING
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.buy_position.orders
            )
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            self.logger.info(
                "[All orders filled] %s %s",
                self.buy_position.config.symbol_info.symbol,
                self.buy_position.state_info.side,
            )
        return condition

    async def close_filled_position_buy(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")

        self.buy_position.state_info.state = State.BOUGHT

        self.buy_position.ui_queue.put_nowait(
            PositionData(
                config=self.buy_position.config,
                state_info=self.buy_position.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.buy_position.orders)
                    / sum(order.quantity for order in self.buy_position.orders),
                    2,
                ),
            )
        )
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

    def conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.NEW
            and self.sell_position.state_info.stagnation_counter
            >= self.sell_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and all(
                order.status == ORDER_STATUS_NEW for order in self.sell_position.orders
            )
        )
        if condition:
            self.logger.info(
                "[Cancel Unfilled SELL] %s, stagnation: %s/%s, last price: %s, trigger cancel price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_unfilled_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.sell_position.state_info.side.value)
        await self.sell_position.cancel_position()

    def conditions_for_sending_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.buy_position.state_info.state == State.BOUGHT
            and self.sell_position.state_info.state == State.NEW
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Send sell orders] hp id: %s, %s, side: %s, state: %s, budget: %s",
                self.sell_position.config.hp_id,
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.side,
                self.sell_position.state_info.state,
                self.sell_position.config.budget,
            )

        return condition

    def conditions_for_cancelling_unfilled_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.buy_position.state_info.state == State.BOUGHT
            and self.buy_position.state_info.state == State.NEW
            and self.sell_position.state_info.stagnation_counter
            >= self.sell_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and all(
                order.status == ORDER_STATUS_NEW for order in self.sell_position.orders
            )
        )
        if condition:
            self.logger.info(
                "[Cancel Unfilled SELL] %s, stagnation: %s/%s, last price: %s, trigger cancel price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    def conditions_for_cancelling_partially_sold_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.sell_position.state_info.stagnation_counter
            >= self.sell_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and not all(
                order.status == ORDER_STATUS_NEW for order in self.sell_position.orders
            )
            and self.buy_position.state_info.state == State.BOUGHT
        )
        if condition:
            self.logger.info(
                "[Cancel Partially Filled SELL] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_partially_sold_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.sell_position.state_info.side.value)
        await self.sell_position.cancel_position()
        self.state = State.PARTIALLY_SOLD
        self.sell_position.state_info = StateInfo(
            side=PositionSide.SHORT, state=State.PARTIALLY_SOLD
        )

    def conditions_for_all_orders_filled_sell(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.SELLING
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.sell_position.orders
            )
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            self.logger.info(
                "[All orders filled] %s %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.side,
            )
        return condition

    async def close_filled_position_sell(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")

        self.sell_position.state_info.state = State.SOLD

        self.sell_position.ui_queue.put_nowait(
            PositionData(
                config=self.sell_position.config,
                state_info=StateInfo(
                    state=State.SOLD,
                    stagnation_counter=self.sell_position.state_info.stagnation_counter,
                    side=PositionSide.SHORT,
                ),
                completeness=round(
                    sum(order.realized_quantity for order in self.sell_position.orders)
                    / sum(order.quantity for order in self.sell_position.orders),
                    2,
                ),
            )
        )
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

    def conditions_for_cancelling_partially_sold_and_bought_orders_sell_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_SOLD
            and self.sell_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.stagnation_counter
            >= self.sell_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Cancel Partially Filled SELL] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_sell_part_sold_part_bought(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.sell_position.state_info.side.value)
        await self.sell_position.cancel_position()
        self.state = State.PARTIALLY_SOLD
        self.sell_position.state_info = StateInfo(
            side=PositionSide.SHORT, state=State.PARTIALLY_SOLD
        )

    def conditions_for_resending_sell_orders_from_part_sold_and_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.PARTIALLY_SOLD
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Resend sell orders] hp id: %s, %s, side: %s, state: %s, budget: %s",
                self.sell_position.config.hp_id,
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.side,
                self.sell_position.state_info.state,
                self.sell_position.config.budget,
            )

        return condition

    def conditions_for_resending_buy_orders_from_part_sold_and_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.PARTIALLY_SOLD
            and self.ticker_update.last_price
            <= self.calculate_trigger_send_orders_price_buy()
        )
        if condition:
            self.logger.info(
                "[Resend buy orders] hp id: %s, %s, side: %s, state: %s, budget: %s",
                self.sell_position.config.hp_id,
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.side,
                self.sell_position.state_info.state,
                self.sell_position.config.budget,
            )

        return condition

    def conditions_for_cancelling_partially_sold_and_bought_orders_buy_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_SOLD
            and self.sell_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.stagnation_counter
            >= self.sell_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            >= self.calculate_trigger_cancel_orders_price_buy()
        )
        if condition:
            self.logger.info(
                "[Cancel Partially Filled BUY] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_buy(),
            )

        return condition

    def conditions_for_buying_fully_previously_partially_sold_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.state == State.BUYING
            and self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.PARTIALLY_SOLD
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.buy_position.orders
            )
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            self.logger.info(
                "[All orders filled] %s %s",
                self.buy_position.config.symbol_info.symbol,
                self.buy_position.state_info.side,
            )
        return condition

    def conditions_for_closing_sold_position_which_is_part_bought(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.state == State.SELLING
            and self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.SOLD
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.buy_position.orders
            )
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            self.logger.info(
                "[All orders filled] %s %s",
                self.buy_position.config.symbol_info.symbol,
                self.buy_position.state_info.side,
            )
        return condition

    async def close_sold_position_which_is_part_bought(self, *args, **kwargs) -> None:
        self.logger.info("Close sold position which is partially bought")

        self.sell_position.state_info.state = State.SOLD

        self.sell_position.ui_queue.put_nowait(
            PositionData(
                config=self.sell_position.config,
                state_info=StateInfo(
                    state=State.SOLD,
                    stagnation_counter=self.sell_position.state_info.stagnation_counter,
                    side=PositionSide.SHORT,
                ),
                completeness=round(
                    sum(order.realized_quantity for order in self.sell_position.orders)
                    / sum(order.quantity for order in self.buy_position.orders),
                    2,
                ),
            )
        )
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

    def conditions_for_resending_buy_orders_for_sold_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.SOLD
            and self.ticker_update.last_price
            <= self.calculate_trigger_send_orders_price_buy()
        )
        if condition:
            self.logger.info(
                "[Resend buy orders] hp id: %s, %s, side: %s, state: %s, budget: %s",
                self.sell_position.config.hp_id,
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.side,
                self.sell_position.state_info.state,
                self.sell_position.config.budget,
            )

        return condition

    def conditions_for_cancelling_buy_orders_to_sold_part_bought(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.SOLD
            and self.sell_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.stagnation_counter
            >= self.sell_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            >= self.calculate_trigger_cancel_orders_price_buy()
        )
        if condition:
            self.logger.info(
                "[Cancel Partially Filled BUY] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_buy(),
            )

        return condition

    def conditions_for_resending_partially_sold_orders(self, *args, **kwargs) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_sell()
        condition = (
            self.sell_position.state_info.state == State.PARTIALLY_SOLD
            and self.buy_position.state_info.state == State.BOUGHT
            and self.ticker_update.last_price <= trigger_send_orders_price
            and self.balance > self.sell_position.config.budget
        )
        if condition:
            self.logger.info(
                "[Resend sell orders] %s, side: %s, state: %s, budget: %s, balance: %s, price trigger: %s last price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.side,
                self.state,
                self.sell_position.config.budget,
                self.balance,
                trigger_send_orders_price,
                self.ticker_update.last_price,
            )

        return condition

    async def resend_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Sending %s SELL")

        await self.sell_position.order_handler.create_orders(
            side=self.sell_position.state_info.side,
            symbol_info=self.sell_position.config.symbol_info,
            orders=self.sell_position.orders,
        )
        self.state = State.SELLING
        self.sell_position.state_info.state = State.PARTIALLY_SOLD

        self.logger.info("Will update orders: %s", self.sell_position.orders)

        for order in self.sell_position.orders:
            self.db.run_db_task(
                self.db.update_order(
                    price=order.price,
                    quantity=order.quantity,
                    quantity_stable=order.quantity_stable,
                    realized_quantity=order.realized_quantity,
                    time_in_force=order.time_in_force,
                    status=order.status,
                    order_type=order.order_type,
                    order_id=order.order_id,
                    hp_id=str(self.sell_position.config.hp_id),
                )
            )
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.sell_position.config,
                state_info=self.sell_position.state_info,
            )
        )

        self.sell_position.ui_queue.put_nowait(
            PositionData(
                config=self.sell_position.config,
                state_info=self.sell_position.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.sell_position.orders)
                    / sum(order.quantity for order in self.sell_position.orders),
                    2,
                ),
            )
        )

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type
            in [
                ORDER_TYPE_LIMIT,
                ORDER_TYPE_MARKET,
            ]
            and self.execution_report.current_order_status == ORDER_STATUS_NEW
            and self.execution_report.symbol
            == self.buy_position.config.symbol_info.symbol
        )
        if condition:
            self.logger.info(
                "[New Order] %s, order type: %s order status: %s",
                self.execution_report.symbol,
                self.execution_report.order_type,
                self.execution_report.current_order_status,
            )
        return condition

    async def confirm_new_order(self, *args, **kwargs) -> None:
        for order in self.buy_position.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "New order confirmation: %s", self.execution_report.order_id
                )

        if self.sell_position:
            for order in self.sell_position.orders:
                if order.order_id == self.execution_report.order_id:
                    order.status = self.execution_report.current_order_status
                    order.order_id = self.execution_report.order_id
                    self.logger.debug(
                        "New order confirmation: %s", self.execution_report.order_id
                    )

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_CANCELED
            and self.execution_report.symbol
            == self.buy_position.config.symbol_info.symbol
        )
        if condition:
            self.logger.info(
                "[Cancelled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.buy_position.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Cancelled order confirmation: %s", self.execution_report.order_id
                )
        if self.sell_position:
            for order in self.sell_position.orders:
                if order.order_id == self.execution_report.order_id:
                    order.status = self.execution_report.current_order_status
                    order.order_id = self.execution_report.order_id
                    self.logger.debug(
                        "Cancelled order confirmation: %s",
                        self.execution_report.order_id,
                    )

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

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.buy_position.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Expired order confirmation: %s", self.execution_report.order_id
                )

        if self.sell_position:
            for order in self.sell_position.orders:
                if order.order_id == self.execution_report.order_id:
                    order.status = self.execution_report.current_order_status
                    order.order_id = self.execution_report.order_id
                    self.logger.debug(
                        "Expired order confirmation: %s", self.execution_report.order_id
                    )

    def conditions_for_order_filled_buy(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.buy_position.orders]
        )
        if condition:
            self.logger.info(
                "[Filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_filled_buy(self, *args, **kwargs) -> None:
        self.logger.debug("Entering handle order filled")

        self.buy_position.state_info.state = State.PARTIALLY_BOUGHT

        await self.buy_position.handle_order_filled(
            execution_report=self.execution_report
        )

        if all(
            order.status == ORDER_STATUS_FILLED for order in self.buy_position.orders
        ):
            signal = Signal.HP_ALL_ORDERS_FILLED
            self.logger.info("All orders filled, sending: %s", signal)
            self.core_queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

    def conditions_for_order_filled_sell(self, *args, **kwargs) -> bool:
        assert self.sell_position
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.sell_position.orders]
        )
        if condition:
            self.logger.info(
                "[Filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_filled_sell(self, *args, **kwargs) -> None:
        self.logger.debug("Entering handle order filled")

        self.sell_position.state_info.state = State.PARTIALLY_SOLD

        await self.sell_position.handle_order_filled(
            execution_report=self.execution_report
        )

        if all(
            order.status == ORDER_STATUS_FILLED for order in self.sell_position.orders
        ):
            self.sell_position.state_info.state = State.SOLD
            signal = Signal.HP_ALL_ORDERS_FILLED
            self.logger.info("All orders filled, sending: %s", signal)
            self.core_queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

    def conditions_for_order_partially_filled_buy(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status
            == ORDER_STATUS_PARTIALLY_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.buy_position.orders]
        )
        if condition:
            self.logger.info(
                "[Partially filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_partially_filled_buy(self, *args, **kwargs):
        self.logger.debug("Entering handle order partially filled")

        self.buy_position.state_info.state = State.PARTIALLY_BOUGHT

        await self.buy_position.handle_order_partially_filled(
            execution_report=self.execution_report
        )

    def conditions_for_order_partially_filled_sell(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status
            == ORDER_STATUS_PARTIALLY_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.sell_position.orders]
        )
        if condition:
            self.logger.info(
                "[Partially filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_partially_filled_sell(self, *args, **kwargs):
        self.logger.debug("Entering handle order partially filled")

        self.sell_position.state_info.state = State.PARTIALLY_SOLD

        await self.sell_position.handle_order_partially_filled(
            execution_report=self.execution_report
        )

    def calculate_trigger_cancel_orders_price_buy(self):
        return self.buy_position.config.symbol_info.adjust_price(
            self.buy_position.config.price_high
            * (1 + (2 * self.buy_position.config.order_trigger / 100))
        )

    def calculate_trigger_cancel_orders_price_sell(self):
        return self.sell_position.config.symbol_info.adjust_price(
            self.sell_position.config.price_low
            * (1 - (2 * self.sell_position.config.order_trigger / 100))
        )

    async def cancel_partially_filled_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.sell_position.state_info.side.value)
        await self.sell_position.cancel_position()
        self.sell_position.state_info = StateInfo(
            side=PositionSide.SHORT, state=State.PARTIALLY_SOLD
        )
        self.sell_position.orders = (
            self.sell_position.order_handler.prepare_sell_orders(
                config=self.sell_position.config,
                buy_orders=self.buy_position.orders,
                sell_orders=self.sell_position.orders,
            )
        )

    def conditions_for_cancelling_partially_filled_sell_orders_from_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell_position.state_info.state == State.PARTIALLY_SOLD
            and self.sell_position.state_info.stagnation_counter
            >= self.sell_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Cancel Partially Filled SELL] %s, stagnation: %s/%s, last price: %s, trigger cancel price: %s",
                self.sell_position.config.symbol_info.symbol,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    # async def cancel_buy_orders(self, *args, **kwargs) -> None:
    #     self.logger.info("Cancelling %s", self.buy_position.state_info.side.value)
    #     self.logger.info("Orders: %s", self.buy_position.orders)
    #     self.balance += self.get_remaining_quantity_buy()
    #     await self.buy_position.cancel_position()

    # def conditions_for_cancelling_sell_orders(self, *args, **kwargs) -> bool:
    #     assert self.sell_position
    #     condition = (
    #         self.sell_position is not None
    #         and self.sell_position.state_info.side == PositionSide.SHORT
    #         and self.sell_position.state_info.stagnation_counter
    #         >= self.sell_position.state_info.stagnation_limit
    #         and self.ticker_update.last_price
    #         < self.calculate_trigger_cancel_orders_price_sell()
    #     )
    #     if condition:
    #         self.logger.info(
    #             "[Stagnation Cancel SELL] %s, stagnation: %s/%s, last price: %s, trigger order price: %s",
    #             self.sell_position.config.symbol_info.symbol,
    #             self.sell_position.state_info.stagnation_counter,
    #             self.sell_position.state_info.stagnation_limit,
    #             self.ticker_update.last_price,
    #             self.calculate_trigger_cancel_orders_price_sell(),
    #         )

    #     return condition

    async def cancel_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.sell_position.state_info.side.value)
        await self.sell_position.cancel_position()

    def conditions_for_position_stagnation_buy(self, *args, **kwargs) -> bool:
        date_time_now = datetime.now()

        condition = self.state == State.BUYING and date_time_now > datetime.strptime(
            self.buy_position.state_info.next_monitor_time, "%Y-%m-%d %H:%M:%S"
        )
        if condition:
            self.logger.info(
                "[Handle stagnation]: %s, time now: %s, monitor time: %s",
                condition,
                date_time_now,
                self.buy_position.state_info.next_monitor_time,
            )
        return condition

    def increase_stagnation_counter_buy(self, *args, **kwargs) -> None:
        self.logger.info(
            "Entering increase stagnation coutner buy, counter before adding 1: %s",
            self.buy_position.state_info.stagnation_counter,
        )
        self.buy_position.state_info.stagnation_counter += 1

        if (
            self.buy_position.state_info.stagnation_counter
            < self.buy_position.state_info.stagnation_limit
        ):
            self.logger.info(
                "[%s]: stagnation counter increase to: %s, stagnation limit: %s",
                self.buy_position.config.hp_id,
                self.buy_position.state_info.stagnation_counter,
                self.buy_position.state_info.stagnation_limit,
            )
        else:
            self.logger.info(
                "[%s]: Stagnation limit reached, current price: %s, order cancel price: %s",
                self.buy_position.config.hp_id,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_buy(),
            )
        time_date = datetime.strptime(
            self.buy_position.state_info.next_monitor_time, "%Y-%m-%d %H:%M:%S"
        )
        time_date += timedelta(hours=1)
        self.buy_position.state_info.next_monitor_time = time_date.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        self.logger.info("Orders: %s", self.buy_position.orders)

        self.buy_position.ui_queue.put_nowait(
            PositionData(
                config=self.buy_position.config,
                state_info=self.buy_position.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.buy_position.orders)
                    / sum(order.quantity for order in self.buy_position.orders),
                    2,
                ),
            )
        )

        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

    def conditions_for_position_stagnation_sell(self, *args, **kwargs) -> bool:
        assert self.sell_position
        date_time_now = datetime.now()

        condition = (
            self.sell_position is not None
            and self.state == State.SELLING
            and date_time_now
            > datetime.strptime(
                self.sell_position.state_info.next_monitor_time, "%Y-%m-%d %H:%M:%S"
            )
        )
        if condition:
            self.logger.info(
                "[Handle stagnation]: %s, time now: %s, monitor time: %s",
                condition,
                date_time_now,
                self.sell_position.state_info.next_monitor_time,
            )

        return condition

    async def increase_stagnation_counter_sell(self, *args, **kwargs) -> None:
        assert self.sell_position
        self.sell_position.state_info.stagnation_counter += 1

        if (
            self.sell_position.state_info.stagnation_counter
            < self.sell_position.state_info.stagnation_limit
        ):
            self.logger.info(
                "[%s]: stagnation counter increase to: %s, stagnation limit: %s",
                self.sell_position.config.hp_id,
                self.sell_position.state_info.stagnation_counter,
                self.sell_position.state_info.stagnation_limit,
            )
        else:
            self.logger.info(
                "[%s]: Stagnation limit reached, current price: %s, order cancel price: %s",
                self.sell_position.config.hp_id,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_buy(),
            )
        time_date = datetime.strptime(
            self.sell_position.state_info.next_monitor_time, "%Y-%m-%d %H:%M:%S"
        )
        time_date += timedelta(hours=1)
        self.sell_position.state_info.next_monitor_time = time_date.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        self.sell_position.ui_queue.put_nowait(
            PositionData(
                config=self.sell_position.config,
                state_info=self.sell_position.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.sell_position.orders)
                    / sum(order.quantity for order in self.sell_position.orders),
                    2,
                ),
            )
        )

        self.db.run_db_task(
            self.db.update_price_level(
                config=self.buy_position.config, state_info=self.buy_position.state_info
            )
        )

    # def get_transitions(self):
    #     # add balance conditions where orders are to be send and update the variable after orders are cancelled.
    #     return [
    #         # {
    #         #     "trigger": "process_recovery",
    #         #     "source": State.RECOVERING,
    #         #     "dest": State.NEW,
    #         #     "conditions": "conditions_for_recovering_to_new",
    #         #     "after": "handle_recovery_to_new",
    #         # },
    #         # {
    #         #     "trigger": "process_recovery",
    #         #     "source": State.RECOVERING,
    #         #     "dest": State.OPEN,
    #         #     "conditions": "conditions_for_recovering_to_open",
    #         #     "after": "handle_recovery_to_open",
    #         # },
    #         # {
    #         #     "trigger": "process_recovery",
    #         #     "source": State.RECOVERING,
    #         #     "dest": State.STAGNATED,
    #         #     "conditions": "conditions_for_recovering_to_stagnated",
    #         #     "after": "handle_recovery_to_stagnated",
    #         # },
    #         {
    #             "trigger": "process_account",
    #             "source": [
    #                 State.NEW,
    #                 State.OPEN,
    #                 State.STAGNATED,
    #                 State.RECOVERING,
    #                 State.CLOSED,
    #             ],
    #             "dest": "=",
    #             "after": "handle_account",
    #         },

    #         {
    #             "trigger": "process_ticker",
    #             "source": State.CLOSED,
    #             "dest": "=",
    #             "after": "allow_messages",
    #         },
    #     ]

    # async def handle_account(self, *args, **kwargs):
    #     for balance in self.account_position.balances:
    #         if balance.asset == "USDT":
    #             self.balance = round(balance.free, 2)
    #     self.logger.debug("Account update: %s", self.account_position)

    # async def allow_messages(self, *args, **kwargs) -> None:
    # self.logger.info(
    #     "Ticker update from allow messages method: %s",
    #     self.ticker_update.last_price,
    # )

    # async def handle_recovery_to_new(self, *args, **kwargs) -> None:
    #     self.logger.debug("Handle recovery to new, just put to IDLE in GUI")

    #     self.position_handler.ui_queue.put_nowait(
    #         PositionData(
    #             config=self.config,
    #             state_info=StateInfo(last_state=State.NEW),
    #             completeness=0,
    #             recovering=True,
    #         )
    #     )

    # async def handle_recovery_to_open(self, *args, **kwargs) -> None:
    #     self.logger.debug("Handle recovery to open")

    #     orders_from_db: List[Dict] = self.db.run_db_task(
    #         self.db.fetch_orders_for_price_level(price_level_id=self.config.hp_id)
    #     )
    #     self.logger.debug(
    #         "Fetched orders from DB for price level: %s: \n%s",
    #         self.config.hp_id,
    #         orders_from_db,
    #     )

    #     orders = [
    #         Order(
    #             quantity=float(order["quantity"]),
    #             realized_quantity=float(order["realized_quantity"]),
    #             precision=0,
    #             price_precision=0,
    #             price=float(order["price"]),
    #             order_id=int(order["order_id"]),
    #         )
    #         for order in orders_from_db
    #     ]

    #     for order in self.position_handler.orders:
    #         for db_order in orders:
    #             if order.price == db_order.price:
    #                 order.realized_quantity = db_order.realized_quantity
    #                 order.order_id = db_order.order_id
    #                 order.open_time = db_order.open_time
    #                 order.status = db_order.status

    #     updated_orders = [
    #         await self.position_handler.order_handler.update_order_status(
    #             symbol=self.config.symbol_info.symbol, order=order
    #         )
    #         for order in orders
    #     ]
    #     self.logger.debug(
    #         "Fetched orders from Binance for price level: %s: \n%s",
    #         self.config.hp_id,
    #         updated_orders,
    #     )

    #     for order in self.position_handler.orders:
    #         for updated_order in updated_orders:
    #             if order.order_id == updated_order.order_id:
    #                 if order.realized_quantity != updated_order.realized_quantity:
    #                     self.logger.info(
    #                         "Order quantity has changed during outage, old: %s, new: %s",
    #                         order.realized_quantity,
    #                         updated_order.realized_quantity,
    #                     )

    #                     order.realized_quantity = updated_order.realized_quantity
    #                     order.status = updated_order.status

    #                     self.db.run_db_task(
    #                         self.db.update_order(
    #                             price=order.price,
    #                             quantity=order.quantity,
    #                             quantity_stable=order.quantity_stable,
    #                             realized_quantity=order.realized_quantity,
    #                             time_in_force=order.time_in_force,
    #                             status=order.status,
    #                             order_type=order.order_type,
    #                             order_id=order.order_id,
    #                             price_level_id=self.config.hp_id,
    #                         )
    #                     )

    #                     if all(
    #                         order.status == ORDER_STATUS_FILLED
    #                         for order in self.position_handler.orders
    #                     ):
    #                         signal = Signal.HP_ALL_ORDERS_FILLED
    #                         self.logger.info("All orders filled, sending: %s", signal)
    #                         self.core_queue.put(
    #                             Event(
    #                                 name=EventName.SIGNAL,
    #                                 content=SignalUpdate(signal=signal),
    #                             )
    #                         )

    #     self.position_handler.ui_queue.put_nowait(
    #         PositionData(
    #             config=self.config,
    #             state_info=StateInfo(last_state=State.OPEN),
    #             completeness=round(
    #                 sum(
    #                     order.realized_quantity
    #                     for order in self.position_handler.orders
    #                 )
    #                 / sum(order.quantity for order in self.position_handler.orders),
    #                 2,
    #             ),
    #             recovering=True,
    #         )
    #     )

    # async def handle_recovery_to_stagnated(self, *args, **kwargs) -> None:
    #     self.logger.debug("Handle recovery to stagnated")

    #     orders_from_db = self.db.run_db_task(
    #         self.db.fetch_orders_for_price_level(price_level_id=self.config.hp_id)
    #     )
    #     self.logger.debug(
    #         "Fetched orders for price level: %s: \n%s",
    #         self.config.hp_id,
    #         orders_from_db,
    #     )
    #     orders = [
    #         Order(
    #             quantity=float(order["quantity"]),
    #             realized_quantity=float(order["realized_quantity"]),
    #             precision=0,
    #             price_precision=0,
    #             price=float(order["price"]),
    #             order_id=int(order["order_id"]),
    #         )
    #         for order in orders_from_db
    #     ]

    #     for order in self.position_handler.orders:
    #         for fetched_order in orders:
    #             if order.price == fetched_order.price:
    #                 order.order_id = fetched_order.order_id
    #                 order.realized_quantity = fetched_order.realized_quantity
    #                 order.status = fetched_order.status

    #     self.position_handler.ui_queue.put_nowait(
    #         PositionData(
    #             config=self.config,
    #             state_info=StateInfo(
    #                 last_state=State.STAGNATED,
    #                 stagnation_counter=self.position_handler.stagnation_counter,
    #             ),
    #             completeness=round(
    #                 sum(
    #                     order.realized_quantity
    #                     for order in self.position_handler.orders
    #                 )
    #                 / sum(order.quantity for order in self.position_handler.orders),
    #                 2,
    #             ),
    #         )
    #     )
