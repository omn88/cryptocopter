from typing import List
import logging
import numpy
import pandas
from transitions.extensions.asyncio import AsyncMachine

from src.common.common import signal_to_state
from src.common.identifiers import State, SignalUpdate, Signal, Event, EventName
from src.strategies.base import BaseStrategy

logger = logging.getLogger("trading_state_machine")


class TradingStateMachine:
    def __init__(self, strategy: BaseStrategy):
        self.state: State = State.FLAT
        self.strategy = strategy
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

    def conditions_for_skipping_same_signal(self, *args, **kwargs) -> bool:
        condition = self.state == signal_to_state(self.strategy.signal_update.signal)

        logger.info(
            "Skip same signal: %s, state: %s signal: %s",
            condition,
            self.state,
            self.strategy.signal_update.signal,
        )

        return condition
