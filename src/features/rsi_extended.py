import logging
import numpy

from src.common.identifiers import State

logger = logging.getLogger("feature_rsi_extended")


class FeatureRsiExtended:
    def __init__(self, df):
        self.df = self.add_columns_for_rsi_extended(df=df)
        self.signals = [State.LONG_20, State.SHORT_80]
        self.conditions = [
            (df.RsiBelowTwenty.diff() == -1),
            (df.RsiAboveEighty.diff() == -1),
        ]
        self.states = [State.LONG_20, State.SHORT_80]
        self.transitions = [
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.LONG_20,
                "conditions": "conditions_for_opening_extended_long",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.SHORT_80,
                "conditions": "conditions_for_opening_extended_short",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_20,
                "dest": State.SHORT_80,
                "conditions": "conditions_for_switch_from_extended_long_to_extended_short",
                "before": "close_long",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_80,
                "dest": State.LONG_20,
                "conditions": "conditions_for_switch_from_extended_short_to_extended_long",
                "before": "close_short",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_20,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_from_extended_long_to_basic_short",
                "before": "close_long",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_80,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_from_extended_short_to_basic_long",
                "before": "close_short",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_20,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_from_extended_long_to_basic_long",
                "before": "change_position_state",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_80,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_from_extended_short_to_basic_short",
                "before": "change_position_state",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.LONG_20,
                "conditions": "conditions_for_skipping_extended_signal",
                "before": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.SHORT_80,
                "conditions": "conditions_for_skipping_extended_signal",
                "before": "skip_signal",
            },
        ]

    @staticmethod
    def add_columns_for_rsi_extended(df):
        df["RsiBelowTwenty"] = numpy.where(df["RSI"] < 20, 1, 0)
        df["RsiAboveEighty"] = numpy.where(df["RSI"] > 80, 1, 0)
        return df
