import logging
import numpy

from src.common.identifiers import State, Signal

logger = logging.getLogger("feature_rsi_extended")


class FeatureRsiExtended:
    def __init__(self):
        self.signals = [Signal.LONG_20, Signal.SHORT_80]
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
                "source": State.SHORT,
                "dest": State.LONG_20,
                "conditions": "conditions_for_switch_from_basic_short_to_extended_long",
                "before": "close_short",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT_80,
                "conditions": "conditions_for_switch_from_basic_long_to_extended_short",
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

    @staticmethod
    def get_conditions_for_rsi_extended(df):
        conditions = [
            (df.RsiBelowTwenty.diff() == -1),
            (df.RsiAboveEighty.diff() == -1),
        ]
        return conditions

    def conditions_for_opening_extended_long(self, *args, **kwargs) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.LONG_20

    def conditions_for_opening_extended_short(self, *args, **kwargs) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.SHORT_80

    def conditions_for_switch_from_extended_long_to_extended_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.LONG_20 and self.signal_update.signal == Signal.SHORT_80
        )

    def conditions_for_switch_from_extended_short_to_extended_long(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT_80 and self.signal_update.signal == Signal.LONG_20
        )

    def conditions_for_switch_from_extended_long_to_basic_short(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.LONG_20 and self.signal_update.signal == Signal.SHORT

    def conditions_for_switch_from_basic_long_to_extended_short(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.LONG and self.signal_update.signal == Signal.SHORT_80

    def conditions_for_switch_from_basic_short_to_extended_long(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.SHORT and self.signal_update.signal == Signal.LONG_20

    def conditions_for_switch_from_extended_short_to_basic_long(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.SHORT_80 and self.signal_update.signal == Signal.LONG

    def conditions_for_switch_from_extended_long_to_basic_long(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.LONG_20 and self.signal_update.signal == Signal.LONG

    def conditions_for_switch_from_extended_short_to_basic_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT_80 and self.signal_update.signal == Signal.SHORT
        )

    def conditions_for_skipping_extended_signal(self, *args, **kwargs) -> bool:
        return (
            self.state == State.LONG
            and self.signal_update.signal == Signal.LONG_20
            or self.state == State.SHORT
            and self.signal_update.signal == Signal.SHORT_80
        )

    async def change_position_state(self, *args, **kwargs):
        logger.info("Changing status to %s", self.signal_update.signal)
        self.position.status = State(self.signal_update.signal.value)
        self.update_position_in_df(self.position.status)
