from datetime import datetime, timedelta
from typing import Dict
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
from src.common.identifiers.spot import State, StrategyConfig
from src.common.identifiers.common import BinanceClient, PositionSide
from src.gui.gui_handler.spot import GuiHandler
from src.position_handler.spot import PositionHandler
from src.strategies.base import BaseStrategy

STAGNATION_LIMIT = 8


class HpManager(BaseStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        gui_handler: GuiHandler,
        logger: StrategyLogger,
        balance: float,
    ):
        super().__init__(client, logger, balance)
        self.gui_handler = gui_handler
        self.config = config
        self.position_handler = PositionHandler(
            client=client,
            strategy_logger=logger,
            config=config,
            gui_handler=gui_handler,
        )
        self.state = State.NEW
        self.states = [
            State.NEW,
            State.OPEN,
            State.STAGNATED,
            State.CLOSED,
        ]

        self.min_order_values = None
        self.trigger_orders_price = self.calculate_trigger_orders_price()

        self.transitions = [
            {
                "trigger": "process_account",
                "source": [State.NEW, State.OPEN, State.STAGNATED, State.CLOSED],
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
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": State.CLOSED,
                "conditions": "conditions_for_all_orders_filled",
                "before": "handle_position_closure",
            },
            {
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled",
                "before": "handle_order_partially_filled",
            },
            {
                "trigger": "process_ticker",
                "source": [State.NEW, State.STAGNATED],
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_long_orders",
                "after": "open_long",
            },
            {
                "trigger": "process_ticker",
                "source": [State.NEW, State.STAGNATED],
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_short_orders",
                "after": "open_short",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_long_orders",
                "after": "cancel_long",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_short_orders",
                "after": "cancel_short",
            },
            {
                "trigger": "process_ticker",
                "source": [State.NEW, State.OPEN, State.STAGNATED, State.CLOSED],
                "dest": "=",
                "after": "handle_ticker",
            },
        ]

    def __str__(self):
        return (
            f"HpManager(client={self.client}, config={self.config}, "
            f"gui_handler={self.gui_handler}, logger={self.logger}, "
            f"balance={self.balance}, state={self.state}, "
            f"trigger_orders_price={self.trigger_orders_price}, "
            f"min_order_values={self.min_order_values}, position_handler={self.position_handler})"
        )

    async def initialize(self):
        # Now you can await the _get_minimum_order_values method
        self.min_order_values = await self._get_minimum_order_values()
        # Additional initialization code can go here

    def calculate_trigger_orders_price(self):
        return (
            round(
                self.config.price_low * (1 - (self.config.order_trigger / 100)),
                2,
            )
            if self.config.side == PositionSide.SHORT
            else round(
                self.config.price_high * (1 + (self.config.order_trigger / 100)),
                2,
            )
        )

    async def _get_minimum_order_values(self) -> Dict:
        exchange_info = await self.client.get_exchange_info()
        min_values = {}

        for symbol_info in exchange_info["symbols"]:
            filters = {f["filterType"]: f for f in symbol_info["filters"]}
            if "MIN_NOTIONAL" in filters:
                min_values[symbol_info["symbol"]] = {
                    "minNotional": filters["MIN_NOTIONAL"]["minNotional"]
                }

        return min_values

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.order_update.order_type
            in [
                ORDER_TYPE_LIMIT,
                ORDER_TYPE_MARKET,
            ]
            and self.order_update.status == ORDER_STATUS_NEW
        )
        self.logger.info(
            "New order confirmation: %s, order type: %s order status: %s",
            condition,
            self.order_update.order_type,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_CANCELED
        )
        self.logger.info(
            "Order cancelled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_expiration(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_EXPIRED
        )
        self.logger.info(
            "Order expired: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_FILLED
        )

        self.logger.info(
            "Order filled: %s, order status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_partially_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.info(
            "Order partially filled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_all_orders_filled(self, *args, **kwargs):
        self.logger.info("Entering conditions for all orders filled")
        condition = (
            self.state == State.OPEN
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.position_handler.orders
            )
            and self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_FILLED
        )

        self.logger.info(
            "All orders filled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_sending_long_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state in [State.NEW, State.STAGNATED]
            and self.config.side == PositionSide.LONG
            and self.ticker_update.last_price <= self.trigger_orders_price
        )

        self.logger.info(
            "Open basic long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_sending_short_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state in [State.NEW, State.STAGNATED]
            and self.config.side == PositionSide.SHORT
            and self.ticker_update.last_price >= self.trigger_orders_price
        )
        self.logger.info(
            "Open basic short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_cancelling_long_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.position_handler.side == PositionSide.LONG
            and self.position_handler.stagnation_counter == STAGNATION_LIMIT
            and self.ticker_update.last_price > self.trigger_orders_price
        )
        self.logger.info(
            "Cancel %s orders due to stagnation: %s, last price: %s",
            self.position_handler.side.value,
            condition,
            self.ticker_update.last_price,
        )

        return condition

    def conditions_for_cancelling_short_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.position_handler.side == PositionSide.SHORT
            and self.position_handler.stagnation_counter == STAGNATION_LIMIT
            and self.ticker_update.last_price < self.trigger_orders_price
        )
        self.logger.info(
            "Cancel %s orders due to stagnation: %s, last price: %s",
            self.position_handler.side.value,
            condition,
            self.ticker_update.last_price,
        )

        return condition

    async def open_long(self, *args, **kwargs) -> None:
        self.logger.debug("Opening %s", self.config.side.value)

        assert self.min_order_values

        await self.position_handler.open_position(
            side=self.config.side,
            budget=self.config.budget,
            price_high=self.config.price_high,
            price_low=self.config.price_low,
            symbol=self.config.symbol,
            min_notional=float(
                self.min_order_values[self.config.symbol]["minNotional"]
            ),
        )

    async def open_short(self, *args, **kwargs) -> None:
        self.logger.debug("Opening %s", self.config.side.value)

        assert self.min_order_values

        await self.position_handler.open_position(
            side=self.config.side,
            budget=self.config.budget,
            price_high=self.config.price_high,
            price_low=self.config.price_low,
            symbol=self.config.symbol,
            min_notional=float(
                self.min_order_values[self.config.symbol]["minNotional"]
            ),
        )

    async def cancel_long(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.position_handler.side)

        await self.position_handler.cancel_position()

    async def cancel_short(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.position_handler.side)
        await self.position_handler.cancel_position()

    async def handle_position_closure(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")

    async def handle_ticker(self, *args, **kwargs) -> None:
        date_time_now = datetime.now()

        if (
            self.state == State.OPEN
            and date_time_now > self.position_handler.next_monitor_position_time
        ):
            self.position_handler.stagnation_counter += 1
            self.logger.info(
                "Stagnation counter increase due to crossing stagnation timer: %s, time now: %s, stagnation counter: %s",
                self.position_handler.next_monitor_position_time,
                date_time_now,
                self.position_handler.stagnation_counter,
            )
            self.position_handler.next_monitor_position_time += timedelta(hours=1)

    async def confirm_new_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "New order confirmation: %s", self.order_update.order_id
                )

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Cancelled order confirmation: %s", self.order_update.order_id
                )

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Expired order confirmation: %s", self.order_update.order_id
                )
                # await self.gui_handler.update_order(
                #     order=order,
                #     symbol=self.position_handler.position.symbol,
                #     side=self.position_handler.position.side,
                # )

    async def handle_account(self, *args, **kwargs):
        self.logger.info("Account update: %s", self.account_update.account_update)

    async def enter_flat(self, *args, **kwargs):
        self.logger.info("Entering Flat")
        # self.df_handler.update_position_in_df(update=State.FLAT)

    async def handle_order_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order filled")

        self.position_handler.stagnation_counter = 0
        self.position_handler.next_monitor_position_time = datetime.now() + timedelta(
            hours=1
        )

        await self.position_handler.handle_order_filled(order_update=self.order_update)

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order partially filled")

        self.position_handler.stagnation_counter = 0
        self.position_handler.next_monitor_position_time = datetime.now() + timedelta(
            hours=1
        )

        await self.position_handler.handle_order_partially_filled(
            order_update=self.order_update
        )
