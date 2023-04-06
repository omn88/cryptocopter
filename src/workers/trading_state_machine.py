import asyncio
from typing import Tuple, List, Union

import binance
import pandas
from transitions.extensions.asyncio import AsyncMachine
import logging
from src.common.common import log_signal_change
from src.features.features import State, Signal
from src.orders import Position, PositionSide
from src.producers.producers import SignalUpdate, Event, EventName
from src.workers import handle_order

logger = logging.getLogger("state_actions")


class TradingStateMachine:
    def __init__(self, client, queue, position, df, balance, order_quantity_list):
        self.client: binance.AsyncClient = client
        self.queue: asyncio.Queue = queue
        self.position: Position = position
        self.df: pandas.DataFrame = df
        self.balance: float = balance
        self.order_quantity_list = order_quantity_list
        self.state: State = State.FLAT
        self.signal_update: SignalUpdate = SignalUpdate(signal=Signal.NULL, price=0)
        self.states: List[State] = list(State)
        self.transitions = []

        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=State.FLAT,
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

    def conditions_for_opening_long(self) -> bool:
        return self.state == State.FLAT and self.signal_update.signal in [
            Signal.LONG,
            Signal.LONG_20,
        ]

    def conditions_for_opening_short(self) -> bool:
        return self.state == State.FLAT and self.signal_update.signal in [
            Signal.SHORT,
            Signal.SHORT_80,
        ]

    def conditions_for_skipping_signal(self) -> bool:
        long_signals = [Signal.LONG, Signal.LONG_20]
        short_signals = [Signal.SHORT, Signal.SHORT_80]

        return (
            (self.state == State.LONG and self.signal_update.signal in long_signals)
            or (
                self.state == State.LONG_20
                and self.signal_update.signal == Signal.LONG_20
            )
            or (
                self.state == State.SHORT and self.signal_update.signal in short_signals
            )
            or (
                self.state == State.SHORT_80
                and self.signal_update.signal == Signal.SHORT_80
            )
            or (
                self.state in [State.SHORT_SPECIAL, State.LONG_SPECIAL]
                and self.signal_update.signal in [long_signals, short_signals]
            )
        )

    def conditions_for_switch_to_short(self) -> bool:
        valid_signals = [Signal.SHORT, Signal.SHORT_80]
        return (
            self.state in [State.LONG, State.LONG_20]
            and self.signal_update.signal in valid_signals
        )

    def conditions_for_switch_to_long(self) -> bool:
        valid_signals = [Signal.LONG, Signal.LONG_20]
        return (
            self.state in [State.SHORT, State.SHORT_80]
            and self.signal_update.signal in valid_signals
        )

    # ToDo: Skip signal may need to be created per strategy as some fuckups might happen, so skip_extended_signal
    def skip_signal(self) -> None:
        logger.info("Skipping signal: %s", self.signal_update.signal)
        self.update_position_in_df(update=self.state)

    def update_position_in_df(self, update: Union[Signal, State]):
        self.df.at[self.df.index[-1], "position"] = update

    async def open_dca_long(self):
        logger.info("Opening %s", self.signal_update.signal)
        self.update_position_in_df(update=self.signal_update.signal)

        self.position = await handle_order.prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            df=self.df,
        )

    async def open_dca_short(self):
        logger.info("Opening %s", self.signal_update.signal)
        self.update_position_in_df(update=self.signal_update.signal)

        self.position = await handle_order.prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            df=self.df,
        )

    async def close_long(self):
        logger.info("Closing %s", self.signal_update.signal)
        self.position = await handle_order.close_long(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            df=self.df,
        )

        self.update_position_in_df(update=self.signal_update.signal)

    # async def send_market_order_and_signal(
    #     self,
    #     position: Position,
    # ) -> Position:
    #     # Close current position
    #     position = await handle_order.futures_position_close(
    #         client=self.client, position=position, balance=self.balance
    #     )
    #     self.df.at[self.df.index[-1], "position"] = State.FLAT
    #     await log_signal_change(df=self.df, signal=self.signal_update.signal)
    #
    #     logger.info(
    #         "Market order send, remaining orders cancelled, adding %s to queue",
    #         self.signal_update,
    #     )
    #     # Add new signal to queue
    #     await self.queue.put(Event(name=EventName.SIGNAL, content=self.signal_update))
    #
    #     return position

    # async def futures_close_special_position(
    #     self,
    #     position: Position,
    #     client: binance.AsyncClient,
    #     df: pandas.DataFrame,
    #     balance: float,
    # ) -> Tuple[Position, pandas.DataFrame]:
    #     logger.info("Got signal: %s", self.signal_update.signal)
    #     position = await handle_order.futures_position_close(
    #         client=client, position=position, balance=balance
    #     )
    #
    #     df.at[df.index[-1], "position"] = State.FLAT
    #
    #     return position, df

    async def process_signal(self, signal_update, position):
        await self.machine.trigger(
            "process_signal",
            signal_update=signal_update,
            position=position,
        )

    # async def process_kline(self, kline_update, position):
    #     await self.machine.trigger(
    #         "process_kline", kline_update=kline_update, position=position
    #     )
