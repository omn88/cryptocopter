import asyncio
import logging
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
from src.common.identifiers import (
    AccountUpdate,
    Order,
    Position,
    PositionMode,
    PositionSide,
    SignalUpdate,
    OrderUpdate,
    KlineUpdate,
    Signal,
    BinanceClient,
    State,
)
from src.common.orders import cancel_order
from src.gui.identifiers import OrderData, PositionData, StrategyData, PositionStatus
from src.workers.handle_order import (
    position_liquidation,
    target_reached,
    partial_position_liquidation,
    target_partially_reached,
    market_order_filled,
    market_order_partially_filled,
    handle_order_filled,
    handle_order_partially_filled,
    signal_to_state,
    prepare_and_send_orders,
    close_long,
    close_short,
)


logger = logging.getLogger("base_strategy")


class BaseStrategy:
    def __init__(
        self,
        client: BinanceClient,
        df: pandas.DataFrame,
        balance: float,
        order_quantity_list: List,
        raw_data,
        symbol: str,
        strategy_name: str,
    ):
        self.client = client
        self.df = df
        self.balance = balance
        self.order_quantity_list = order_quantity_list
        self.raw_data = raw_data
        self.symbol = symbol
        self.strategy_name = strategy_name
        self.queue: asyncio.Queue = asyncio.Queue()
        self.ui_queue: asyncio.Queue = asyncio.Queue()
        self.main_ui_queue: asyncio.Queue = asyncio.Queue()
        self.position: Position = Position()
        self.position_old: Position = Position()

        self.signals: List = [Signal.LONG, Signal.SHORT]
        self.conditions: List = []

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate(signal=Signal.NULL, price=0)
        self.order_update: OrderUpdate = OrderUpdate(status=ORDER_STATUS_NEW)
        self.kline_update: KlineUpdate = KlineUpdate(kline=[])
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
        logger.info("Finished base init")

    @staticmethod
    def signals_from_features_generate(df, conditions, signals) -> pandas.DataFrame:
        df["Signal"] = numpy.select(conditions, signals)
        df["Position"] = State.FLAT.value
        return df

    def conditions_for_no_signal(self, *args, **kwargs) -> bool:
        condition = self.signal_update.signal == Signal.NULL

        logger.info(
            "Skip no signal: %s, signal: %s",
            condition,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_skipping_same_signal(self, *args, **kwargs) -> bool:
        condition = self.state == signal_to_state(self.signal_update.signal).value
        logger.info(
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
        logger.info(
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

        logger.info(
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
        logger.info(
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
        logger.info(
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
        logger.info(
            "Order expired: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position.take_profit_order.price == self.order_update.price
            and self.order_update.status == ORDER_STATUS_FILLED
            and self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
        )
        logger.info(
            "Target reached: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_partially_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position.take_profit_order.price == self.order_update.price
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
        )
        logger.info(
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
        logger.info(
            "Market order filled: %s, state: %s order update status: %s",
            condition,
            self.position_old.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled_partially(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        logger.info(
            "Market order partially filled: %s, state: %s order update status: %s",
            condition,
            self.position_old.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_FILLED
        )

        logger.info(
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
        logger.info(
            "Order partially filled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_opening_basic_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.LONG
        )
        logger.info(
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
        logger.info(
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
        logger.info(
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
        logger.info(
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
        logger.info("Skipping signal: %s", self.signal_update.signal)
        self.df.at[self.df.index[-1], "Position"] = self.df.at[
            self.df.index[-2], "Position"
        ]

    async def open_dca_long(self, *args, **kwargs):
        logger.debug("Opening %s", self.signal_update.signal)

        self.position.side = PositionSide.LONG

        self.position = await prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            mode=self.mode,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
        )

        self.update_position_in_df(update=State(self.signal_update.signal.value))

    async def open_dca_short(self, *args, **kwargs):
        logger.info("Opening %s", self.signal_update.signal)

        self.position.side = PositionSide.SHORT

        self.position = await prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            mode=self.mode,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
        )

        self.update_position_in_df(
            update=signal_to_state(signal=self.signal_update.signal)
        )

    async def close_long(self, *args, **kwargs):
        logger.info("Closing %s", self.position.state)
        self.position_old = await close_long(
            client=self.client,
            position=self.position,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
            main_ui_queue=self.main_ui_queue,
            strategy_name=self.strategy_name,
        )

    async def close_short(self, *args, **kwargs):
        logger.info("Closing %s", self.position.state)
        self.position_old = await close_short(
            client=self.client,
            position=self.position,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
            main_ui_queue=self.main_ui_queue,
            strategy_name=self.strategy_name,
        )

    async def send_close_position_to_ui(self, symbol: str):
        data = PositionData(
            symbol=symbol,
            quantity=self.position_old.quantity,
            entry_price=self.position_old.entry_price,
            mark_price=0,
            liquidation_price=self.position_old.liquidation_price,
            pnl=0,
            status=PositionStatus.CLOSED,
            state=self.position.state,
        )
        await self.ui_queue.put(data)
        await self.main_ui_queue.put(
            StrategyData(strategy_name=self.strategy_name, position_data=data)
        )

    async def send_order_update_to_ui(self, order: Order, open_time, symbol: str):
        order_data = OrderData(
            symbol=symbol,
            order_id=order.order_id,
            order_type=order.order_type,
            side=self.position.side,
            price=order.price,
            quantity=order.quantity,
            realized_quantity=order.realized_quantity,
            status=order.status,
            open_time=open_time,
        )

        await self.ui_queue.put(order_data)

    async def log_new_order(self, *args, **kwargs) -> None:
        for order in self.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                logger.info("New order: %s", self.order_update.order_id)

    async def handle_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                logger.info("Cancelled order: %s", self.order_update.order_id)

    async def log_expired_order(self, symbol: str, *args, **kwargs) -> None:
        for order in self.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                logger.info("Expired order: %s", self.order_update.order_id)
                await self.send_order_update_to_ui(
                    order=order, open_time=order.open_time, symbol=symbol
                )

    async def handle_account(self, *args, **kwargs):
        logger.info("Account update: %s", self.account_update.account_update)

    async def handle_liquidation(self, *args, **kwargs):
        logger.info("Entering handle liquidation")
        self.position_old, self.balance = await position_liquidation(
            position=self.position,
            balance=self.balance,
        )

        await self.send_close_position_to_ui(symbol=self.symbol)

    async def handle_partial_liquidation(self, *args, **kwargs):
        logger.info("Entering handle partial liquidation")
        await partial_position_liquidation(
            order_update=self.order_update,
        )

    async def enter_flat(self, *args, **kwargs):
        logger.info("Entering Flat")
        self.position = Position()
        self.update_position_in_df(update=self.position.state)

    async def handle_target_reached(self, *args, **kwargs):
        logger.info("Entering handle target order filled")
        self.position_old, self.balance = await target_reached(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
        )

        await self.send_close_position_to_ui(symbol=self.symbol)

    async def handle_target_partially_reached(self, *args, **kwargs):
        logger.info("Entering handle target order partially filled")
        self.position, self.balance = await target_partially_reached(
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_market_order_filled(self, *args, **kwargs):
        logger.info("Entering handle market order filled")
        self.position_old, self.balance = await market_order_filled(
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_market_order_partially_filled(self, *args, **kwargs):
        logger.info("Entering handle market order partially filled")
        self.position, self.balance = await market_order_partially_filled(
            position=self.position,
            order_update=self.order_update,
        )

    async def handle_order_filled(self, *args, **kwargs):
        logger.info("Entering handle order filled")
        self.position = await handle_order_filled(
            client=self.client,
            order_update=self.order_update,
            position=self.position,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
        )

        position_data = PositionData(
            symbol=self.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            status=PositionStatus.ACTIVE,
            state=self.position.state,
        )
        await self.ui_queue.put(position_data)

        await self.main_ui_queue.put(
            StrategyData(strategy_name=self.strategy_name, position_data=position_data)
        )

        self.update_position_in_df(update=self.position.state)
        order = next(
            (
                order
                for order in self.position.orders
                if order.order_id == self.order_update.order_id
            ),
            None,
        )

        if order is not None:
            await self.send_order_update_to_ui(
                order=order, open_time=order.open_time, symbol=self.symbol
            )
        else:
            logger.info(
                "No UI update, unknown order ID: %s", self.order_update.order_id
            )

    async def handle_order_partially_filled(self, *args, **kwargs):
        logger.info("Entering handle order partially filled")
        self.position = await handle_order_partially_filled(
            client=self.client,
            order_update=self.order_update,
            position=self.position,
            ui_queue=self.ui_queue,
            symbol=self.symbol,
        )

        position_data = PositionData(
            symbol=self.symbol,
            quantity=self.position.quantity,
            entry_price=self.position.entry_price,
            mark_price=0,
            liquidation_price=self.position.liquidation_price,
            pnl=0,
            status=PositionStatus.ACTIVE,
            state=self.position.state,
        )

        await self.ui_queue.put(position_data)

        await self.main_ui_queue.put(
            StrategyData(strategy_name=self.strategy_name, position_data=position_data)
        )

        order = next(
            (
                order
                for order in self.position.orders
                if order.order_id == self.order_update.order_id
            ),
            None,
        )

        if order is not None:
            await self.send_order_update_to_ui(
                order=order, open_time=order.open_time, symbol=self.symbol
            )
        else:
            logger.info(
                "No UI update, unknown order ID: %s", self.order_update.order_id
            )

    async def cancel_order(
        self, order, side: str, ui_queue: asyncio.Queue, symbol: str
    ):
        await cancel_order(
            client=self.client, order=order, side=side, ui_queue=ui_queue, symbol=symbol
        )
