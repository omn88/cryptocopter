import asyncio
import signal
from typing import List, Union, Optional
import binance
import numpy
import pandas
from transitions.extensions.asyncio import AsyncMachine
import logging


from src.common.identifiers import (
    Position,
    State,
    SignalUpdate,
    OrderUpdate,
    Signal,
    KlineUpdate,
    AccountUpdate,
    PositionMode,
    PositionSide,
    Event,
    EventName,
)
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
    futures_position_close,
)

logger = logging.getLogger("trading_state_machine")


class TradingStateMachine:
    def __init__(
        self,
        client: binance.AsyncClient,
        queue: asyncio.Queue,
        position: Position,
        df: pandas.DataFrame,
        balance: float,
        order_quantity_list,
        raw_data,
    ):
        self.state: State = State.FLAT
        self.client: binance.AsyncClient = client
        self.queue: asyncio.Queue = queue
        self.position: Position = position
        self.position_old: Position = position
        self.raw_data: List = raw_data
        self.df: pandas.DataFrame = df
        self.balance: float = balance
        self.order_quantity_list = order_quantity_list

        self.signal_update: SignalUpdate = SignalUpdate(signal=Signal.NULL, price=0)
        self.order_update: OrderUpdate = OrderUpdate(
            status=binance.AsyncClient.ORDER_STATUS_NEW
        )
        self.kline_update: KlineUpdate = KlineUpdate(kline=[])
        self.account_update: Optional[AccountUpdate] = None
        self.mode: PositionMode = PositionMode.DCA
        self.states: List[State] = [self.state]
        self.signals: List[Signal] = []
        self.conditions: List = []
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
                ],
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "log_new_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "log_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "log_expired_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_partial_position_liquidation",
                "before": "handle_partial_liquidation",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": State.FLAT,
                "conditions": "conditions_for_position_liquidation",
                "before": "handle_liquidation",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_target_partially_reached",
                "before": "handle_target_partially_reached",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": State.FLAT,
                "conditions": "conditions_for_target_reached",
                "before": "handle_target_reached",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": State.FLAT,
                "conditions": "conditions_for_market_order_filled",
                "before": "handle_market_order_filled",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled_partially",
                "before": "handle_market_order_filled_partially",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_EXT, State.SHORT, State.SHORT_EXT],
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled",
                "before": "handle_order_partially_filled",
            },
        ]

        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=self.state,
            send_event=True,
            queued=True,
        )

    @staticmethod
    def signals_from_features_generate(
        df: pandas.DataFrame, conditions, signals
    ) -> pandas.DataFrame:
        df["Signal"] = numpy.select(conditions, signals)
        df["Position"] = State.FLAT
        return df

    def import_feature_configuration(self, feature):
        self.machine.add_states(feature.states)
        self.signals.extend(feature.signals)

        updated_transitions = []
        for transition in feature.transitions:
            updated_transition = transition.copy()
            updated_transitions.append(updated_transition)

            self.machine.add_transition(**updated_transition)

    async def determine_start_position(self):
        signal = Signal.NULL
        price = 0
        signal_index = 0

        for index, row in self.df[::-1].iterrows():
            if row["Signal"] != 0:
                signal = row["Signal"]
                price = row["Close"]
                # Adding extra lines to see what happened before signal
                signal_index += 4
                break

            price = row["Close"]
            signal_index += 1

        try:
            assert signal_index <= len(self.df.index)
            self.df = self.df.iloc[len(self.df.index) - signal_index : :]
            logger.debug(
                "New DF shortened to last signal + 3 rows: \n%s", self.df.to_string()
            )
        except AssertionError as e:
            logger.debug(
                "Last signal almost on top of df, leaving df as is: \n%s",
                self.df.to_string(),
            )

        signal_update = SignalUpdate(signal=signal, price=round(float(price), 2))
        await self.queue.put(Event(name=EventName.SIGNAL, content=signal_update))

    def conditions_for_no_signal(self, *args, **kwargs) -> bool:
        condition = self.signal_update.signal == Signal.NULL

        logger.info(
            "Skip no signal: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_skipping_same_signal(self, *args, **kwargs) -> bool:
        condition = self.state == signal_to_state(self.signal_update.signal)

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
            and self.order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED
        )
        logger.info(
            "Position liquidation: %s, state: %s order update type: %s",
            condition,
            self.state,
            self.order_update.order_type,
        )
        return condition

    def conditions_for_partial_position_liquidation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == "LIQUIDATION"
            and self.order_update.status
            == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
        )

        logger.info(
            "Partial position liquidation: %s, state: %s order update type: %s",
            condition,
            self.state,
            self.order_update.order_type,
        )
        return condition

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.order_update.order_type
            in [
                binance.AsyncClient.FUTURE_ORDER_TYPE_LIMIT,
                binance.AsyncClient.FUTURE_ORDER_TYPE_MARKET,
            ]
            and self.order_update.status == binance.AsyncClient.ORDER_STATUS_NEW
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
            self.order_update.order_type == binance.AsyncClient.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == binance.AsyncClient.ORDER_STATUS_CANCELED
        )
        logger.info(
            "Order cancelled: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_expiration(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == binance.AsyncClient.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == binance.AsyncClient.ORDER_STATUS_EXPIRED
        )
        logger.info(
            "Order expired: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position.take_profit_order.price == self.order_update.price
            and self.order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED
            and self.order_update.order_type
            == binance.AsyncClient.FUTURE_ORDER_TYPE_LIMIT
        )
        logger.info(
            "Target reached: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_partially_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position.take_profit_order.price == self.order_update.price
            and self.order_update.status
            == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
            and self.order_update.order_type
            == binance.AsyncClient.FUTURE_ORDER_TYPE_LIMIT
        )
        logger.info(
            "Target partially reached: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == binance.AsyncClient.FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED
        )
        logger.info(
            "Market order filled: %s, state: %s order update status: %s",
            condition,
            self.position_old.status,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled_partially(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == binance.AsyncClient.FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status
            == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
        )
        logger.info(
            "Market order partially filled: %s, state: %s order update status: %s",
            condition,
            self.position_old.status,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == binance.AsyncClient.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED
        )

        logger.info(
            "Order filled: %s, state: %s order status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_partially_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == binance.AsyncClient.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status
            == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
        )
        logger.info(
            "Order partially filled: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
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
        )

        self.update_position_in_df(
            update=signal_to_state(signal=self.signal_update.signal)
        )

    async def close_long(self, *args, **kwargs):
        logger.info("Closing %s", self.position.status)
        self.position_old = await close_long(
            client=self.client, balance=self.balance, position=self.position
        )

    async def close_short(self, *args, **kwargs):
        logger.info("Closing %s", self.position.status)
        self.position_old = await close_short(
            client=self.client, balance=self.balance, position=self.position
        )

    def log_new_order(self, *args, **kwargs) -> None:
        for order in self.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                logger.info("New order: %s", self.order_update.order_id)

    def log_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                logger.info("Cancelled order: %s", self.order_update.order_id)

    def log_expired_order(self, *args, **kwargs) -> None:
        for order in self.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                logger.info("Expired order: %s", self.order_update.order_id)

    async def handle_account(self, *args, **kwargs):
        logger.info("Account update: %s", self.account_update.account_update)

    async def handle_liquidation(self, *args, **kwargs):
        logger.info("Entering handle liquidation")
        self.position_old, self.balance = await position_liquidation(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_partial_liquidation(self, *args, **kwargs):
        logger.info("Entering handle partial liquidation")
        await partial_position_liquidation(
            order_update=self.order_update,
        )

    async def enter_flat(self, *args, **kwargs):
        logger.info("Entering Flat")
        self.position = Position()
        self.update_position_in_df(update=self.position.status)

    async def handle_target_reached(self, *args, **kwargs):
        logger.info("Entering handle target order filled")
        self.position_old, self.balance = await target_reached(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_target_partially_reached(self, *args, **kwargs):
        logger.info("Entering handle target order partially filled")
        self.position, self.balance = await target_partially_reached(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_market_order_filled(self, *args, **kwargs):
        logger.info("Entering handle market order filled")
        self.position_old, self.balance = await market_order_filled(
            position=self.position_old,
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
        )

        self.update_position_in_df(update=self.position.status)

    async def handle_order_partially_filled(self, *args, **kwargs):
        logger.info("Entering handle order partially filled")
        self.position = await handle_order_partially_filled(
            client=self.client,
            order_update=self.order_update,
            position=self.position,
        )
