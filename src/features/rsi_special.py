import logging
import numpy

from src.common.identifiers import State, Signal

logger = logging.getLogger("feature_rsi_special")


class FeatureRsiSpecial:
    def __init__(self):
        self.signals = [Signal.SHORT_SPECIAL, Signal.LONG_SPECIAL]
        self.states = [State.LONG_SPECIAL, State.SHORT_SPECIAL]
        self.transitions = [
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT_SPECIAL,
                "conditions": "conditions_for_opening_special_short",
                "before": "close_long",
                "after": "open_special_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.LONG_SPECIAL,
                "conditions": "conditions_for_opening_special_long",
                "before": "close_short",
                "after": "open_special_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_SPECIAL,
                "dest": State.FLAT,
                "conditions": "conditions_for_closing_special_position",
                "before": "close_special_position",
                "after": "enter_flat",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_SPECIAL,
                "dest": State.FLAT,
                "conditions": "conditions_for_closing_special_position",
                "before": "close_special_position",
                "after": "enter_flat",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_SPECIAL,
                "dest": [State.SHORT, State.SHORT_EXT],
                "conditions": "conditions_for_skipping_when_long_special",
                "before": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_SPECIAL,
                "dest": [State.LONG, State.LONG_EXT],
                "conditions": "conditions_for_skipping_when_short_special",
                "before": "skip_signal",
            },
        ]

    @staticmethod
    def add_columns_for_rsi_special(df):
        df["RsiBelowEighteen"] = numpy.where(df["RSI"] < 18, 1, 0)
        df["RsiAboveEightyTwo"] = numpy.where(df["RSI"] > 82, 1, 0)

        return df

    @staticmethod
    def get_conditions_for_rsi_special(df):
        conditions = [
            (df.RsiBelowEighteen.diff() == 1),
            (df.RsiAboveEightyTwo.diff() == 1),
        ]
        return conditions

    def conditions_for_opening_special_short(self, *args, **kwargs) -> bool:
        return (
            self.state == State.LONG
            and self.signal_update.signal == Signal.SHORT_SPECIAL
        )

    def conditions_for_opening_special_long(self, *args, **kwargs) -> bool:
        return (
            self.state == State.SHORT
            and self.signal_update.signal == Signal.LONG_SPECIAL
        )

    def conditions_for_skipping_when_long_special(self, *args, **kwargs) -> bool:
        return self.state == State.LONG_SPECIAL and self.signal_update.signal in [
            Signal.SHORT,
            Signal.SHORT_EXT,
        ]

    def conditions_for_skipping_when_short_special(self, *args, **kwargs) -> bool:
        return self.state == State.SHORT_SPECIAL and self.signal_update.signal in [
            Signal.LONG,
            Signal.LONG_EXT,
        ]

    def conditions_for_closing_special_position(self, *args, **kwargs) -> bool:
        return (
            self.state in [State.SHORT_SPECIAL, State.LONG_SPECIAL]
            and self.signal_update.signal == Signal.CLOSE_SPECIAL
        )
