import asyncio
from typing import Tuple, List

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
    def __init__(self, client, df, balance, order_quantity_list, queue):
        self.client: binance.AsyncClient = client
        self.balance: float = balance
        self.order_quantity_list = order_quantity_list
        self.queue: asyncio.Queue = queue
        self.df: pandas.DataFrame = df

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

    @staticmethod
    def conditions_for_opening_long(status: State, signal: Signal) -> bool:
        return status == State.FLAT and signal in [
            Signal.LONG,
            Signal.LONG_20,
        ]

    @staticmethod
    def conditions_for_opening_short(status: State, signal: Signal) -> bool:
        return status == State.FLAT and signal in [
            Signal.SHORT,
            Signal.SHORT_80,
        ]

    @staticmethod
    def conditions_for_skipping_signal(status: State, signal: Signal) -> bool:
        long_signals = [Signal.LONG, Signal.LONG_20]
        short_signals = [Signal.SHORT, Signal.SHORT_80]

        return (
            (status == State.LONG and signal in long_signals)
            or (status == State.LONG_20 and signal == Signal.LONG_20)
            or (status == State.SHORT and signal in short_signals)
            or (status == State.SHORT_80 and signal == Signal.SHORT_80)
            or (
                status in [State.SHORT_SPECIAL, State.LONG_SPECIAL]
                and signal in [long_signals, short_signals]
            )
        )

    @staticmethod
    def conditions_for_switch_to_short(status: State, signal: Signal) -> bool:
        valid_signals = [Signal.SHORT, Signal.SHORT_80]
        return status in [State.LONG, State.LONG_20] and signal in valid_signals

    @staticmethod
    def conditions_for_switch_to_long(status: State, signal: Signal) -> bool:
        valid_signals = [Signal.LONG, Signal.LONG_20]
        return status in [State.SHORT, State.SHORT_80] and signal in valid_signals

    # ToDo: Skip signal may need to be created per strategy as some fuckups might happen, so skip_extended_signal
    def skip_signal(
        self, df: pandas.DataFrame, signal: Signal, status: State
    ) -> pandas.DataFrame:
        logger.info("Skipping signal: %s", signal)
        df.at[df.index[-1], "position"] = status

        return df

    async def open_position(
        self,
        signal_update: SignalUpdate,
    ) -> Position:
        logger.info("Opening %s", signal_update.signal)
        current_position = await handle_order.futures_position_open(
            client=self.client,
            entry_price=signal_update.price,
            signal=signal_update.signal,
            side=PositionSide.LONG
            if signal_update.signal
            in [Signal.LONG, Signal.LONG_20, Signal.LONG_SPECIAL]
            else PositionSide.SHORT,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            df=self.df,
        )
        self.df.at[self.df.index[-1], "position"] = signal_update.signal

        return current_position

    async def send_market_order_and_signal(
        self,
        current_position: Position,
        signal_update: SignalUpdate,
    ) -> Position:
        # Close current position
        current_position = await handle_order.futures_position_close(
            client=self.client, current_position=current_position, balance=self.balance
        )
        self.df.at[self.df.index[-1], "position"] = State.FLAT
        await log_signal_change(df=self.df, signal=signal_update.signal)

        logger.info(
            "Market order send, remaining orders cancelled, adding %s to queue",
            signal_update,
        )
        # Add new signal to queue
        await self.queue.put(Event(name=EventName.SIGNAL, content=signal_update))

        return current_position

    async def futures_close_special_position(
        position: Position,
        client: binance.AsyncClient,
        signal_update: SignalUpdate,
        df: pandas.DataFrame,
        balance: float,
    ) -> Tuple[Position, pandas.DataFrame]:
        logger.info("Got signal: %s", signal_update.signal)
        position = await handle_order.futures_position_close(
            client=client, position=position, balance=balance
        )

        df.at[df.index[-1], "position"] = State.FLAT

        return position, df

    # async def on_enter(self, event):
    #     signal = event.kwargs.get("signal_update")
    #     df = event.kwargs.get("df")
    #     current_position = event.kwargs.get("current_position")
    #
    #     if self.machine.state == signal.signal:
    #         return
    #
    #     await log_signal_change(df, signal.signal)
    #     self.machine.set_state(signal.signal)

    async def process_signal(self, signal_update, position):
        await self.machine.trigger(
            "process_signal",
            signal_update=signal_update,
            current_position=position,
        )

    async def process_kline(self, kline_update, position):
        await self.machine.trigger(
            "process_kline", kline_update=kline_update, position=position
        )


# class TradingStateMachine:
#     def __init__(self, client, balance, order_quantity_list, queue):
#         self.client = client
#         self.balance = balance
#         self.order_quantity_list = order_quantity_list
#         self.queue = queue
#
#         self.states = list(Signals)
#         self.transitions = [
#
#             {
#                 "trigger": "process_signal",
#                 "source": [Signals.LONG_20, Signals.SHORT_80],
#                 "dest": "=",
#                 "conditions": "conditions_for_changing_status",
#                 "after": "futures_change_status_long20_short80",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": [Signals.LONG, Signals.LONG_20],
#                 "dest": Signals.FLAT,
#                 "conditions": "conditions_for_switch_from_long_to_short",
#                 "after": "market_close_and_send_signal",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": [Signals.SHORT, Signals.SHORT_80],
#                 "dest": Signals.FLAT,
#                 "conditions": "conditions_for_switch_from_short_to_long",
#                 "after": "market_close_and_send_signal",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.SHORT,
#                 "dest": Signals.FLAT,
#                 "conditions": "conditions_for_special_long_close_short",
#                 "after": "market_close_and_send_signal",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.LONG,
#                 "dest": Signals.FLAT,
#                 "conditions": "conditions_for_special_short_close_long",
#                 "after": "market_close_and_send_signal",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.FLAT,
#                 "dest": Signals.LONG_SPECIAL,
#                 "conditions": "conditions_for_special_long",
#                 "after": "futures_signal_position_open",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.FLAT,
#                 "dest": Signals.SHORT_SPECIAL,
#                 "conditions": "conditions_for_special_short",
#                 "after": "futures_signal_position_open",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.LONG_SPECIAL,
#                 "dest": Signals.FLAT,
#                 "conditions": "conditions_for_closing_special_long",
#                 "after": "market_close_and_send_signal",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.SHORT_SPECIAL,
#                 "dest": Signals.FLAT,
#                 "conditions": "conditions_for_closing_special_short",
#                 "after": "market_close_and_send_signal",
#             }
#             # ... (other transitions defined similarly)
#         ]
#
#         self.machine = AsyncMachine(
#             model=self,
#             states=self.states,
#             transitions=self.transitions,
#             initial=Signals.FLAT,
#             send_event=True,
#             queued=True,
#         )
