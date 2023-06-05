import logging
import numpy

from src.common.identifiers import State, Signal

logger = logging.getLogger("feature_rsi_special")


class FeatureRsiSpecial:
    def __init__(self, df):
        self.df = df

    states = [State.LONG_SPECIAL, State.SHORT_SPECIAL]
    transitions = [
        {
            "trigger": "process_signal",
            "source": State.LONG,
            "dest": State.SHORT_SPECIAL,
            "conditions": "conditions_for_opening_special_short",
            "after": "open_special_short",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT,
            "dest": State.LONG_SPECIAL,
            "conditions": "conditions_for_opening_special_long",
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

    def rsi_signal_special_generate(self):
        assert "RSI" in self.df.columns
        self.special_signals_list = [
            Signal.SHORT_SPECIAL,
            Signal.LONG_SPECIAL,
            Signal.CLOSE_SPECIAL,
        ]

        self.df["RsiBelowEighteen"] = numpy.where(self.df["RSI"] < 18, 1, 0)
        self.df["RsiAboveEightyTwo"] = numpy.where(self.df["RSI"] > 82, 1, 0)

        # Updated column names
        self.df["CloseSpecialLong"] = numpy.where(
            (self.df["RSI"] < 50)
            & (self.df["RSI"].shift(1) >= 50)
            & (self.df["Position"].shift(1) == State.LONG_SPECIAL),
            1,
            0,
        )
        self.df["CloseSpecialShort"] = numpy.where(
            (self.df["RSI"] > 50)
            & (self.df["RSI"].shift(1) <= 50)
            & (self.df["Position"].shift(1) == State.SHORT_SPECIAL),
            1,
            0,
        )

        self.special_signal_conditions = [
            (self.df.RsiBelowEighteen.diff() == 1),
            (self.df.RsiAboveEightyTwo.diff() == 1),
            # Conditions for closing special LONG_SPECIAL and SHORT_SPECIAL positions
            (self.df.CloseSpecialLong.diff() == 1)
            or (self.df.CloseSpecialShort.diff() == 1),
        ]
