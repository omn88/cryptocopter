import binance
import pandas
from transitions.extensions.asyncio import AsyncMachine
import logging
from src.features import Signals
from src.features.features import State
from src.orders import CurrentPosition
from src.producers.producers import SignalUpdate
from src.workers.state_conditions import conditions_for_opening_long

logger = logging.getLogger("state_actions")


class TradingStateMachine:
    def __init__(self, client, balance, order_quantity_list, queue):
        self.client = client
        self.balance = balance
        self.order_quantity_list = order_quantity_list
        self.queue = queue

        self.states = list(State)
        self.transitions = []

        self.machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=Signals.FLAT,
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
            initial=Signals.FLAT,
            send_event=True,
            queued=True,
        )

    # async def on_enter(self, event):
    #     signal = event.kwargs.get("signal_update")
    #     df = event.kwargs.get("df")
    #     current_position = event.kwargs.get("current_position")
    #
    #     if self.machine.state == signal.signal:
    #         return
    #
    #     if self.machine.state in [Signals.LONG, Signals.SHORT]:
    #         current_position, df = await market_close_and_send_signal(
    #             self.client,
    #             signal,
    #             df,
    #             current_position,
    #             self.balance,
    #             self.queue,
    #         )
    #
    #     await log_signal_change(df, signal.signal)
    #     self.machine.set_state(signal.signal)

    async def process_signal(self, signal_update, df, current_position):
        await self.machine.trigger(
            "process_signal",
            signal_update=signal_update,
            df=df,
            current_position=current_position,
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
#             {
#                 "trigger": "process_signal",
#                 "source": "*",
#                 "dest": "=",
#                 "conditions": "conditions_for_skipping_signal",
#                 "after": "futures_skip_signal",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.FLAT,
#                 "dest": Signals.LONG,
#                 "conditions": "conditions_for_opening_long",
#                 "after": "futures_signal_position_open",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": Signals.FLAT,
#                 "dest": Signals.SHORT,
#                 "conditions": "conditions_for_opening_short",
#                 "after": "futures_signal_position_open",
#             },
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
