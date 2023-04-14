import asyncio
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
)
from src.producers.producers import determine_start_position
from src.workers.handle_account import account_handle
from src.workers.handle_order import (
    position_liquidation,
    target_reached,
    partial_position_liquidation,
    target_partially_reached,
    market_order_filled,
    market_order_partially_filled,
    handle_order_update,
)
from src.workers.kline_handle import kline_handle

logger = logging.getLogger("trading_state_machine")


class TradingStateMachine:
    def __init__(
        self, client, queue, position, df, balance, order_quantity_list, raw_data
    ):
        self.state: State = State.FLAT
        self.client: binance.AsyncClient = client
        self.queue: asyncio.Queue = queue
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

    def add_states_and_transitions(self, new_states, new_transitions):
        self.states.extend(new_states)
        self.transitions.extend(new_transitions)
        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=State.FLAT,
            send_event=True,
            queued=True,
        )

    def add_conditions_and_signals(self, condition_lists: List, signal_lists: List):
        for condition_list in condition_lists:
            for condition in condition_list:
                self.conditions.append(condition)

        for signal_list in signal_lists:
            for choice in signal_list:
                self.signals.append(choice)

    def signals_from_features_generate(self):
        self.df["signal"] = numpy.select(self.conditions, self.signals)

    async def determine_start_position(self):
        self.df = await determine_start_position(df=self.df, queue=self.queue)

    def conditions_for_skipping_same_signal(self) -> bool:
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
        self.df.at[self.df.index[-1], "position"] = update

    def skip_signal(self) -> None:
        logger.info("Skipping signal: %s", self.signal_update.signal)
        self.update_position_in_df(update=self.state)

    def log_new_order(self) -> None:
        logger.info("New order: %s", self.order_update.order_id)

    def log_cancelled_order(self) -> None:
        logger.info("Cancelled order: %s", self.order_update.order_id)

    def log_expired_order(self) -> None:
        logger.info("Expired order: %s", self.order_update.order_id)

    async def handle_kline(self):

        self.position, self.raw_data, self.df = await kline_handle(
            df=self.df,
            kline=self.kline_update.kline,
            queue=self.queue,
            position=self.position,
            raw_data=self.raw_data,
        )

    async def handle_account(self):

        self.df, self.position = await account_handle(
            df=self.df, position=self.position, account_update=self.account_update
        )

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

    async def process_signal(self, signal_update, position) -> Position:
        await self.machine.trigger(
            "process_signal",
            signal_update=signal_update,
            position=position,
        )
        return self.position

    async def process_order(self, order_update, position) -> Position:
        await self.machine.trigger(
            "process_order",
            order_update=order_update,
            position=position,
        )
        return self.position

    async def process_kline(self, kline_update, position) -> Position:
        await self.machine.trigger(
            "process_kline",
            kline_update=kline_update,
            position=position,
        )
        return self.position

    async def process_account(self, account_update, position) -> Position:
        await self.machine.trigger(
            "process_account",
            account_update=account_update,
            position=position,
        )
        return self.position
