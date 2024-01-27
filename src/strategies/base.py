import asyncio
from typing import List, Union
import numpy
import pandas
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    FUTURE_ORDER_TYPE_LIMIT,
    FUTURE_ORDER_TYPE_MARKET,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
)
from logging_config import StrategyLogger
from src.common.common import signal_to_state
from src.common.identifiers import (
    AccountUpdate,
    Order,
    PositionMode,
    PositionSide,
    SignalUpdate,
    OrderUpdate,
    KlineUpdate,
    Signal,
    BinanceClient,
    State,
)
from src.gui.gui_handler import GuiHandler
from src.position_handler import PositionHandler


class BaseStrategy:
    def __init__(
        self,
        client: BinanceClient,
        df: pandas.DataFrame,
        balance: float,
        raw_data,
        symbol: str,
        budget: float,
        strategy_name: str,
        number_of_orders: int,
        gui_handler: GuiHandler,
        logger: StrategyLogger,
    ):
        self.client = client
        self.df = df
        self.balance = balance
        self.raw_data = raw_data
        self.symbol = symbol
        self.strategy_name = strategy_name
        self.gui_handler = gui_handler
        self.logger = logger
        self.position_handler: PositionHandler = PositionHandler(
            client=client,
            strategy_logger=logger,
            budget=budget,
            number_of_orders=number_of_orders,
            gui_handler=gui_handler,
        )
        self.queue: asyncio.Queue = asyncio.Queue()

        self.signals: List = [Signal.LONG, Signal.SHORT]
        self.conditions: List = []

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.order_update: OrderUpdate = OrderUpdate()
        self.kline_update: KlineUpdate = KlineUpdate()
        self.account_update: AccountUpdate = AccountUpdate(account_update={})
        self.state: State = State.FLAT
        self.mode = PositionMode.DCA
        self.states: List[State] = [State.LONG, State.SHORT]
        self.transitions = [
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_no_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_skipping_same_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_kline",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.FLAT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "after": "handle_kline",
            },
            {
                "trigger": "process_account",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.FLAT,
                    State.SHORT_SPECIAL,
                    State.LONG_SPECIAL,
                ],
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "log_new_order",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.FLAT,
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "handle_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "log_expired_order",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_partial_position_liquidation",
                "before": "handle_partial_liquidation",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": State.FLAT,
                "conditions": "conditions_for_position_liquidation",
                "before": "handle_liquidation",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_target_partially_reached",
                "before": "handle_target_partially_reached",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": State.FLAT,
                "conditions": "conditions_for_target_reached",
                "before": "handle_target_reached",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled",
                "before": "handle_market_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled_partially",
                "before": "handle_market_order_filled_partially",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled",
                "before": "handle_order_partially_filled",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.LONG,
                "conditions": "conditions_for_opening_basic_long",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.SHORT,
                "conditions": "conditions_for_opening_basic_short",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_to_short",
                "before": "close_long",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_to_long",
                "before": "close_short",
                "after": "open_dca_long",
            },
        ]

    @staticmethod
    def signals_from_features_generate(df, conditions, signals) -> pandas.DataFrame:
        df["Signal"] = numpy.select(conditions, signals)
        df["Position"] = State.FLAT.value
        return df

    def conditions_for_no_signal(self, *args, **kwargs) -> bool:
        condition = self.signal_update.signal == Signal.NULL

        self.logger.info(
            "Skip no signal: %s, signal: %s",
            condition,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_skipping_same_signal(self, *args, **kwargs) -> bool:
        condition = self.state == signal_to_state(self.signal_update.signal).value
        self.logger.info(
            "Skip same signal: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def conditions_for_position_liquidation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == "LIQUIDATION"
            and self.order_update.status == ORDER_STATUS_FILLED
        )
        self.logger.info(
            "Position liquidation: %s, order update type: %s",
            condition,
            self.order_update.order_type,
        )
        return condition

    def conditions_for_partial_position_liquidation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == "LIQUIDATION"
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )

        self.logger.info(
            "Partial position liquidation: %s, order update type: %s",
            condition,
            self.order_update.order_type,
        )
        return condition

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.order_update.order_type
            in [
                FUTURE_ORDER_TYPE_LIMIT,
                FUTURE_ORDER_TYPE_MARKET,
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
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
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
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_EXPIRED
        )
        self.logger.info(
            "Order expired: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position_handler.position.take_profit_order.price
            == self.order_update.price
            and self.order_update.status == ORDER_STATUS_FILLED
            and self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
        )
        self.logger.info(
            "Target reached: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_partially_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position_handler.position.take_profit_order.price
            == self.order_update.price
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
        )
        self.logger.info(
            "Target partially reached: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == ORDER_STATUS_FILLED
        )
        self.logger.info(
            "Market order filled: %s, state: %s order update status: %s",
            condition,
            self.position_handler.position.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled_partially(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.info(
            "Market order partially filled: %s, state: %s order update status: %s",
            condition,
            self.position_handler.position.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
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
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.info(
            "Order partially filled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_opening_basic_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.LONG
        )
        self.logger.info(
            "Open basic long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_opening_basic_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.SHORT
        )
        self.logger.info(
            "Open basic short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_switch_to_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.LONG and self.signal_update.signal == Signal.SHORT
        )
        self.logger.info(
            "Switch to short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def conditions_for_switch_to_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.SHORT and self.signal_update.signal == Signal.LONG
        )
        self.logger.info(
            "Switch to long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def update_position_in_df(self, update: Union[Signal, State]):
        self.df.at[self.df.index[-1], "Position"] = (
            signal_to_state(update) if isinstance(update, Signal) else update
        )

    def skip_signal(self, *args, **kwargs) -> None:
        self.logger.info("Skipping signal: %s", self.signal_update.signal)
        self.df.at[self.df.index[-1], "Position"] = self.df.at[
            self.df.index[-2], "Position"
        ]

    async def open_dca_long(self, *args, **kwargs):
        self.logger.debug("Opening %s", self.signal_update.signal)

        side = PositionSide.LONG

        await self.position_handler.open_position(
            side=side,
            strategy_name=self.strategy_name,
            number_of_orders=self.position_handler.number_of_orders,
            symbol=self.symbol,
            mode=self.mode,
            signal_update=self.signal_update,
        )

        await self.gui_handler.update_strategy(
            strategy_name=self.strategy_name, position=self.position_handler.position
        )

        await self.gui_handler.create_orders(
            orders=self.position_handler.position.orders, symbol=self.symbol, side=side
        )

        self.update_position_in_df(update=State(self.signal_update.signal.value))

    async def open_dca_short(self, *args, **kwargs):
        self.logger.info("Opening %s", self.signal_update.signal)

        side = PositionSide.SHORT

        await self.position_handler.open_position(
            side=side,
            strategy_name=self.strategy_name,
            number_of_orders=self.position_handler.number_of_orders,
            symbol=self.symbol,
            mode=self.mode,
            signal_update=self.signal_update,
        )

        await self.gui_handler.create_orders(
            orders=self.position_handler.position.orders, symbol=self.symbol, side=side
        )
        self.update_position_in_df(update=self.position_handler.position.state)

    async def close_long(self, *args, **kwargs):
        self.logger.info("Closing %s", self.position_handler.position.state)
        await self.position_handler.close_position()

        await self.gui_handler.update_position(
            position=self.position_handler.closed_positions[-1]
        )
        await self.gui_handler.update_strategy(
            strategy_name=self.strategy_name,
            position=self.position_handler.closed_positions[-1],
        )
        self.update_position_in_df(update=State(self.signal_update.signal.value))

    async def close_short(self, *args, **kwargs):
        self.logger.info("Closing %s", self.position_handler.position.state)
        await self.position_handler.close_position()

        await self.gui_handler.update_position(
            position=self.position_handler.closed_positions[-1]
        )
        await self.gui_handler.update_strategy(
            strategy_name=self.strategy_name,
            position=self.position_handler.closed_positions[-1],
        )

        self.update_position_in_df(update=State(self.signal_update.signal.value))

    async def log_new_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info("New order: %s", self.order_update.order_id)

    async def handle_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info("Cancelled order: %s", self.order_update.order_id)

    async def log_expired_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info("Expired order: %s", self.order_update.order_id)
                await self.gui_handler.update_order(
                    order=order,
                    symbol=self.position_handler.position.symbol,
                    side=self.position_handler.position.side,
                )

    async def handle_account(self, *args, **kwargs):
        self.logger.info("Account update: %s", self.account_update.account_update)

    async def handle_liquidation(self, *args, **kwargs):
        self.logger.info("Entering handle liquidation")
        self.balance = await self.position_handler.position_liquidation(
            balance=self.balance
        )
        self.position_handler.position.state = State.FLAT

        await self.gui_handler.update_position(
            position=self.position_handler.closed_positions[-1]
        )

    async def handle_partial_liquidation(self, *args, **kwargs):
        self.logger.info("Entering handle partial liquidation")
        await self.position_handler.partial_position_liquidation(
            order_update=self.order_update
        )

    async def enter_flat(self, *args, **kwargs):
        self.logger.info("Entering Flat")
        self.update_position_in_df(update=State.FLAT)

    async def handle_target_reached(self, *args, **kwargs):
        self.logger.info("Entering handle target order filled")
        self.balance = await self.position_handler.target_reached(
            order_update=self.order_update, balance=self.balance
        )

        self.position_handler.position.state = State.FLAT

        await self.gui_handler.update_position(
            position=self.position_handler.closed_positions[-1]
        )
        await self.gui_handler.update_strategy(
            position=self.position_handler.closed_positions[-1],
            strategy_name=self.strategy_name,
        )
        await self.gui_handler.update_order(
            order=self.position_handler.closed_positions[-1].take_profit_order,
            side=self.position_handler.closed_positions[-1].side,
            symbol=self.position_handler.position.symbol,
        )

    async def handle_target_partially_reached(self, *args, **kwargs):
        self.logger.info("Entering handle target order partially filled")

        self.balance = await self.position_handler.target_partially_reached(
            order_update=self.order_update,
            balance=self.balance,
        )

        await self.gui_handler.update_position(position=self.position_handler.position)
        await self.gui_handler.update_strategy(
            position=self.position_handler.position, strategy_name=self.strategy_name
        )
        await self.gui_handler.update_order(
            order=self.position_handler.position.take_profit_order,
            side=self.position_handler.position.side,
            symbol=self.position_handler.position.symbol,
        )

    async def handle_market_order_filled(self, *args, **kwargs):
        self.logger.info("Entering handle market order filled")
        await self.position_handler.market_order_filled(order_update=self.order_update)
        self.position_handler.position.state = State.FLAT

    async def handle_market_order_filled_partially(self, *args, **kwargs):
        self.logger.info("Entering handle market order partially filled")
        await self.position_handler.market_order_filled_partially(
            order_update=self.order_update
        )

    async def handle_order_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order filled")

        await self.position_handler.futures_get_position_info()

        # cancel take profit if exists
        if self.position_handler.position.take_profit_order.order_id:
            self.position_handler.position.take_profit_order = (
                await self.position_handler.order_handler.cancel_order(
                    order=self.position_handler.position.take_profit_order,
                    symbol=self.position_handler.position.symbol,
                )
            )
            self.logger.info(
                "Cancelled take profit order with id: %s",
                self.position_handler.position.take_profit_order.order_id,
            )

        self.position_handler.position.take_profit_order = (
            await self.position_handler.order_handler.create_take_profit_order(
                position=self.position_handler.position
            )
        )

        order = await self.position_handler.handle_order_filled(
            order_update=self.order_update
        )

        await self.gui_handler.update_order(
            order=order,
            symbol=self.position_handler.position.symbol,
            side=self.position_handler.position.side,
        )
        await self.gui_handler.update_position(position=self.position_handler.position)
        await self.gui_handler.update_strategy(
            strategy_name=self.strategy_name, position=self.position_handler.position
        )

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order partially filled")

        await self.position_handler.futures_get_position_info()

        # cancel take profit if exists
        if self.position_handler.position.take_profit_order.order_id:
            self.position_handler.position.take_profit_order = await self.cancel_order(
                order=self.position_handler.position.take_profit_order
            )
            self.logger.info(
                "Cancelled take profit order with id: %s",
                self.position_handler.position.take_profit_order.order_id,
            )

        self.position_handler.position.take_profit_order = (
            await self.position_handler.order_handler.create_take_profit_order(
                position=self.position_handler.position
            )
        )

        order = await self.position_handler.handle_order_partially_filled(
            order_update=self.order_update
        )

        await self.gui_handler.update_order(
            order=order,
            symbol=self.position_handler.position.symbol,
            side=self.position_handler.position.side,
        )
        await self.gui_handler.update_position(position=self.position_handler.position)
        await self.gui_handler.update_strategy(
            strategy_name=self.strategy_name, position=self.position_handler.position
        )

    async def cancel_order(self, order: Order) -> Order:
        order = await self.position_handler.order_handler.cancel_order(
            order=order, symbol=self.position_handler.position.symbol
        )

        await self.gui_handler.update_order(
            order=order,
            symbol=self.position_handler.position.symbol,
            side=self.position_handler.position.side,
        )

        return order
