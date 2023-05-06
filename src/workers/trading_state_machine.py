from typing import List, Union, Optional
import binance
import numpy
import pandas
from transitions.extensions.asyncio import (
    AsyncMachine,
    AsyncState,
    AsyncEvent,
    AsyncEventData,
)
import logging

from src.common.common import insert_to_pandas
from src.common.identifiers import (
    Position,
    State,
    SignalUpdate,
    OrderUpdate,
    Signal,
    KlineUpdate,
    AccountUpdate,
    PositionMode,
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
)

logger = logging.getLogger("trading_state_machine")


class TradingStateMachine:
    def __init__(
        self,
        client: binance.AsyncClient,
        position: Position,
        df: pandas.DataFrame,
        balance: float,
        order_quantity_list,
        raw_data,
    ):
        self.state: State = State.FLAT
        self.client: binance.AsyncClient = client
        self.position: Position = position
        self.position_old: Optional[Position] = None
        self.raw_data: List = raw_data
        self.df: pandas.DataFrame = df
        self.balance: float = balance
        self.order_quantity_list = order_quantity_list

        self.signal_update: SignalUpdate = SignalUpdate(signal=Signal.NULL, price=0)
        self.order_update: OrderUpdate = OrderUpdate(
            status=self.client.ORDER_STATUS_NEW
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
                "conditions": "conditions_for_skipping_same_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_kline",
                "source": "*",
                "dest": "=",
                "after": "handle_kline",
            },
            {
                "trigger": "process_account",
                "source": "*",
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "log_new_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "log_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "log_expired_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": "=",
                "conditions": "conditions_for_partial_position_liquidation",
                "before": "handle_partial_liquidation",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": State.FLAT,
                "conditions": "conditions_for_position_liquidation",
                "before": "handle_liquidation",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": "=",
                "conditions": "conditions_for_target_partially_reached",
                "before": "handle_target_partially_reached",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": State.FLAT,
                "conditions": "conditions_for_target_reached",
                "before": "handle_target_reached",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": State.FLAT,
                "conditions": "conditions_for_market_order_filled",
                "before": "handle_market_order_filled",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled_partially",
                "before": "handle_market_order_filled_partially",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.LONG_20, State.SHORT, State.SHORT_80],
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

    def signals_from_features_generate(self, df) -> pandas.DataFrame:
        df["Signal"] = numpy.select(self.conditions, self.signals)
        df["Position"] = State.FLAT
        return df

    def import_feature_configuration(self, feature):
        self.machine.add_states(feature.states)
        self.signals.extend(feature.signals)
        self.conditions.extend(feature.conditions)

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
                signal = row["signal"]
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

        signal = Signal.NULL if signal == 0 else signal
        signal_update = SignalUpdate(signal=signal, price=round(float(price), 2))
        if signal_update.signal == Signal.NULL:
            logger.info("No signal created, starting flat and awaiting new signal.")
        else:
            logger.info("Processing signal: %s, price: %s", signal, price)
            self.signal_update = signal_update
            await self.process_signal()

    def conditions_for_skipping_same_signal(self, *args, **kwargs) -> bool:

        condition = self.state.value == self.signal_update.signal.value

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
            and self.order_update.status == self.client.ORDER_STATUS_FILLED
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
            and self.order_update.status == self.client.ORDER_STATUS_PARTIALLY_FILLED
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
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_NEW
        )
        logger.info(
            "New order confirmation: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_CANCELED
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
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_EXPIRED
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
            and self.order_update.status == self.client.ORDER_STATUS_FILLED
            and self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
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
            and self.order_update.status == self.client.ORDER_STATUS_PARTIALLY_FILLED
            and self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
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
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == self.client.ORDER_STATUS_FILLED
        )
        logger.info(
            "Market order filled: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled_partially(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == self.client.ORDER_STATUS_PARTIALLY_FILLED
        )
        logger.info(
            "Market order partially filled: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_FILLED
        )
        logger.info(
            "Order filled: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_partially_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_PARTIALLY_FILLED
        )
        logger.info(
            "Order partially filled: %s, state: %s order update status: %s",
            condition,
            self.state,
            self.order_update.status,
        )
        return condition

    def update_position_in_df(self, update: Union[Signal, State]):
        self.df.at[self.df.index[-1], "Position"] = update

    def skip_signal(self, *args, **kwargs) -> None:
        logger.info("Skipping signal: %s", self.signal_update.signal)
        self.df.at[self.df.index[-1], "Position"] = self.df.at[
            self.df.index[-2], "Position"
        ]

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

    async def handle_kline(self, *args, **kwargs):

        expected_index = int(self.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.kline[0])
        self.raw_data.append(self.kline_update.kline)
        temp_df = insert_to_pandas(data=self.raw_data)
        temp_df = self.signals_from_features_generate(df=temp_df)
        self.df = self.df.append(temp_df.iloc[-1])

        signal_update = SignalUpdate(
            signal=self.df.iloc[-1]["signal"],
            price=round(float(self.df.iloc[-1]["Close"]), 2),
        )

        if signal_update.signal == 0:
            logger.info("Kline did not produce new signal")
            self.df.at[self.df.index[-1], "Position"] = self.df.at[
                self.df.index[-2], "Position"
            ]
        else:
            logger.info(
                "New signal produced by Kline, processing signal: %s, price: %s",
                signal_update.signal,
                signal_update.price,
            )
            await self.process_signal(
                signal_update=signal_update, position=self.position
            )

    async def handle_account(self, *args, **kwargs):

        logger.info("Entering account handle")
        logger.info("Account update: %s", self.account_update.account_update)
        logger.info("Exiting account handle")

    async def handle_liquidation(self, *args, **kwargs):
        self.position, self.balance = await position_liquidation(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_partial_liquidation(self, *args, **kwargs):
        await partial_position_liquidation(
            order_update=self.order_update,
        )

    async def enter_flat(self, *args, **kwargs):
        self.position = Position()

    async def handle_target_reached(self, *args, **kwargs):
        self.position, self.balance = await target_reached(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_target_partially_reached(self, *args, **kwargs):
        logger.info("Entering handle market order partially filled")
        self.position.market_order = await target_partially_reached(
            order_update=self.order_update,
        )

    async def handle_market_order_filled(self, *args, **kwargs):
        logger.info("Entering handle market order filled")
        self.position, self.balance = await market_order_filled(
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
        )

    async def handle_order_partially_filled(self, *args, **kwargs):
        logger.info("Entering handle order partially filled")
        self.position = await handle_order_partially_filled(
            client=self.client,
            order_update=self.order_update,
            position=self.position,
        )
