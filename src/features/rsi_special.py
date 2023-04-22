import logging
from typing import Optional, List

import binance
import numpy
import pandas

from src.common.identifiers import Position, State, SignalUpdate, PositionMode, Signal
from src.workers import handle_order

logger = logging.getLogger("feature_rsi_extended")


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
            "dest": [State.SHORT, State.SHORT_80],
            "conditions": "conditions_for_skipping_when_long_special",
            "before": "skip_signal",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT_SPECIAL,
            "dest": [State.LONG, State.LONG_20],
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
        self.df["CloseSpecialLong_RsiCrossesFiftyFromAbove"] = numpy.where(
            (self.df["RSI"] < 50)
            & (self.df["RSI"].shift(1) >= 50)
            & (self.df["Position"].shift(1) == Signal.LONG_SPECIAL),
            1,
            0,
        )
        self.df["CloseSpecialShort_RsiCrossesFiftyFromBelow"] = numpy.where(
            (self.df["RSI"] > 50)
            & (self.df["RSI"].shift(1) <= 50)
            & (self.df["Position"].shift(1) == Signal.SHORT_SPECIAL),
            1,
            0,
        )

        self.special_signal_conditions = [
            (self.df.RsiBelowEighteen.diff() == 1),
            (self.df.RsiAboveEightyTwo.diff() == 1),
            # Conditions for closing special LONG_SPECIAL and SHORT_SPECIAL positions
            (self.df.CloseSpecialLong_RsiCrossesFiftyFromAbove.diff() == 1)
            or (self.df.CloseSpecialShort_RsiCrossesFiftyFromBelow.diff() == 1),
        ]
