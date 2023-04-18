from typing import List, Union, Optional, Dict
import binance
import numpy
import pandas
from transitions.extensions.asyncio import AsyncMachine
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
    handle_order_update,
)

logger = logging.getLogger("trading_state_machine")


class TradingStateMachine:
    def __init__(self, client, position, df, balance, order_quantity_list, raw_data):
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
        self.conditions = []
        self.signals = []
        self.columns = []
        self.states: List[State] = [self.state]
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
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "log_new_order",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "log_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_new_order_expiration",
                "after": "log_expired_order",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_partial_position_liquidation",
                "before": "handle_partial_liquidation",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": State.FLAT,
                "conditions": "conditions_for_position_liquidation",
                "before": "handle_liquidation",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_target_partially_reached",
                "before": "handle_target_partially_reached",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": State.FLAT,
                "conditions": "conditions_for_target_reached",
                "before": "handle_target_reached",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": State.FLAT,
                "conditions": "conditions_for_market_order_filled",
                "before": "handle_market_order_filled",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_market_order_filled_partially",
                "before": "handle_market_order_filled_partially",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_order_update",
                "before": "handle_order_update",
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

    def add_states_and_transitions(
        self, new_states: List[State], new_transitions: List[Dict]
    ):
        self.states.extend(new_states)
        logger.info("New states: %s", new_states)
        self.transitions.extend(new_transitions)
        logger.info("New transitions: %s", new_transitions)
        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=State.FLAT,
            send_event=True,
            queued=True,
        )

    async def determine_start_position(self):

        signal = Signal.NULL
        price = 0
        signal_index = 0

        for index, row in self.df[::-1].iterrows():
            if row["signal"] != 0:
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

        signal_update = SignalUpdate(signal=signal, price=round(float(price), 2))
        if signal_update.signal == 0:
            logger.info("No signal created, starting flat and awaiting new signal.")
        else:
            await self.process_signal(
                signal_update=signal_update, position=self.position
            )
            logger.info("Processing signal: %s, price: %s", signal, price)

    def conditions_for_skipping_same_signal(self, event_data) -> bool:
        logger.info("EVENT DATA: %s", event_data)
        logger.info(
            "Entering conditions for skipping same signal, state: %s, signal: %s",
            self.state,
            self.signal_update.signal,
        )
        return self.state == self.signal_update.signal

    def conditions_for_position_liquidation(self) -> bool:
        return (
            self.order_update.order_type == "LIQUIDATION"
            and self.order_update.status == self.client.ORDER_STATUS_FILLED
        )

    def conditions_for_partial_position_liquidation(self) -> bool:
        return (
            self.order_update.order_type == "LIQUIDATION"
            and self.order_update.status == self.client.ORDER_STATUS_PARTIALLY_FILLED
        )

    def conditions_for_new_order_confirmation(self) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?
        return (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_NEW
        )

    def conditions_for_order_cancellation(self) -> bool:
        return (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_CANCELED
        )

    def conditions_for_order_expiration(self) -> bool:
        return (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == self.client.ORDER_STATUS_EXPIRED
        )

    def conditions_for_target_reached(self) -> bool:
        return (
            self.position.take_profit_order.price == self.order_update.price
            and self.order_update.status == self.client.ORDER_STATUS_FILLED
            and self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
        )

    def conditions_for_target_partially_reached(self) -> bool:
        return (
            self.position.take_profit_order.price == self.order_update.price
            and self.order_update.status == self.client.ORDER_STATUS_PARTIALLY_FILLED
            and self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
        )

    def conditions_for_market_order_filled(self) -> bool:
        return (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == self.client.ORDER_STATUS_FILLED
        )

    def conditions_for_market_order_filled_partially(self) -> bool:
        return (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == self.client.ORDER_STATUS_PARTIALLY_FILLED
        )

    def conditions_for_order_update(self):
        return (
            self.order_update.order_type == self.client.FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status
            in [
                self.client.ORDER_STATUS_FILLED,
                self.client.ORDER_STATUS_PARTIALLY_FILLED,
            ]
        )

    def update_position_in_df(self, update: Union[Signal, State]):
        self.df.at[self.df.index[-1], "Position"] = update

    def skip_signal(self) -> None:
        logger.info("Skipping signal: %s", self.signal_update.signal)
        self.df.at[self.df.index[-1], "Position"] = self.df.at[
            self.df.index[-2], "Position"
        ]

    def log_new_order(self) -> None:
        logger.info("New order: %s", self.order_update.order_id)

    def log_cancelled_order(self) -> None:
        logger.info("Cancelled order: %s", self.order_update.order_id)

    def log_expired_order(self) -> None:
        logger.info("Expired order: %s", self.order_update.order_id)

    async def handle_kline(self):

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

    async def handle_account(self):

        logger.info("Entering account handle")
        logger.info("Account update: %s", self.account_update.account_update)
        logger.info("Exiting account handle")

    async def handle_liquidation(self):
        self.position, self.balance = await position_liquidation(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_partial_liquidation(self):
        await partial_position_liquidation(
            order_update=self.order_update,
        )

    async def enter_flat(self):
        self.position = Position()

    async def handle_target_reached(self):
        self.position, self.balance = await target_reached(
            client=self.client,
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_target_partially_reached(self):
        self.position.market_order = await target_partially_reached(
            order_update=self.order_update,
        )

    async def handle_market_order_filled(self):
        self.position, self.balance = await market_order_filled(
            position=self.position,
            order_update=self.order_update,
            balance=self.balance,
        )

    async def handle_market_order_filled_partially(self):
        self.position, self.balance = await market_order_partially_filled(
            position=self.position,
            order_update=self.order_update,
        )

    async def handle_order_update(self):
        self.position = await handle_order_update(
            client=self.client,
            order_update=self.order_update,
            position=self.position,
        )

    # async def process_signal(self, signal_update, position) -> Position:
    #     await self.process_signal(
    #         signal_update=signal_update,
    #         position=position,
    #     )
    #     return self.position
    #
    # async def process_order(self, order_update, position) -> Position:
    #     await self.process_order(
    #         order_update=order_update,
    #         position=position,
    #     )
    #     return self.position
    #
    # async def process_kline(self, kline_update, position) -> Position:
    #     await self.process_kline(
    #         kline_update=kline_update,
    #         position=position,
    #     )
    #     return self.position
    #
    # async def process_account(self, account_update, position) -> Position:
    #     await self.process_account(
    #         account_update=account_update,
    #         position=position,
    #     )
    #     return self.position
