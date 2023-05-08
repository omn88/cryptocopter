import logging
import numpy

from src.common.identifiers import State, Signal, PositionSide
from src.workers import handle_order
from src.workers.handle_order import prepare_and_send_orders, signal_to_state

logger = logging.getLogger("feature_rsi_basic")


class FeatureRsiBasic:
    def __init__(self, df):

        self.df = self.add_columns_for_rsi_basic(df=df)
        self.signals = [Signal.LONG, Signal.SHORT]
        self.conditions = [
            (self.df.RsiBelowThirty.diff() == 0)
            & (self.df.RsiBelowThirty.diff(periods=2) == -1),
            (self.df.RsiAboveSeventy.diff() == 0)
            & (self.df.RsiAboveSeventy.diff(periods=2) == -1),
        ]

        self.states = [State.LONG, State.SHORT]
        self.transitions = [
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
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_no_signal",
                "after": "skip_signal",
            },
        ]

    @staticmethod
    def add_columns_for_rsi_basic(df):
        df["RsiBelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
        df["RsiAboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)
        return df

    def conditions_for_opening_basic_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT and self.signal_update.signal == Signal.LONG
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
            self.state == State.FLAT and self.signal_update.signal == Signal.SHORT
        )
        logger.info(
            "Open basic short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_no_signal(self, *args, **kwargs) -> bool:
        condition = (
            self.state in [State.LONG, State.SHORT, State.FLAT]
            and self.signal_update.signal == Signal.NULL
        )
        logger.info(
            "Skip no signal (NULL): %s, state: %s signal: %s",
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
