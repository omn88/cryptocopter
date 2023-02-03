from enum import Enum
from typing import Tuple, List

import btalib
import numpy
import pandas


class Signals(Enum):
    LONG = "LONG"
    LONG_20 = "LONG_20"
    SHORT = "SHORT"
    SHORT_80 = "SHORT_80"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"
    CLOSE_SPECIAL = "CLOSE_SPECIAL"
    FLAT = "FLAT"
    NULL = "NULL"


def rsi_indicator_apply(df: pandas.DataFrame) -> pandas.DataFrame:
    rsi = btalib.rsi(df, period=14)
    df["RSI"] = rsi.df
    df.dropna(inplace=True)

    return df


def rsi_signal_basic_generate(
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, List, List[Signals]]:
    assert "RSI" in df.columns

    df["RsiBelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
    df["RsiAboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)

    conditions = [
        (df.RsiBelowThirty.diff() == 0) & (df.RsiBelowThirty.diff(periods=2) == -1),
        (df.RsiAboveSeventy.diff() == 0) & (df.RsiAboveSeventy.diff(periods=2) == -1),
    ]

    signals = [Signals.LONG, Signals.SHORT]

    return df, conditions, signals


def rsi_signal_extended_generate(
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, List, List[Signals]]:
    assert "RSI" in df.columns

    df["RsiBelowTwenty"] = numpy.where(df["RSI"] < 20, 1, 0)
    df["RsiAboveEighty"] = numpy.where(df["RSI"] > 80, 1, 0)

    conditions = [
        (df.RsiBelowTwenty.diff() == -1),
        (df.RsiAboveEighty.diff() == -1),
    ]

    signals = [Signals.LONG_20, Signals.SHORT_80]

    return df, conditions, signals


def rsi_signal_special_generate(
    df: pandas.DataFrame,
) -> Tuple[pandas.DataFrame, List, List[Signals]]:
    assert "RSI" in df.columns

    df["RsiBelowEighteen"] = numpy.where(df["RSI"] < 18, 1, 0)
    df["RsiAboveEightyTwo"] = numpy.where(df["RSI"] > 82, 1, 0)

    conditions = [
        (df.RsiBelowEighteen.diff() == 1),
        (df.RsiAboveEightyTwo.diff() == 1),
    ]

    signals = [Signals.SHORT_SPECIAL, Signals.LONG_SPECIAL]

    return df, conditions, signals


def combined_signals_generate(
    df: pandas.DataFrame, condition_lists: List, choice_lists: List
):
    conditions = []
    choices = []

    for condition_list in condition_lists:
        for condition in condition_list:
            conditions.append(condition)

    for choice_list in choice_lists:
        for choice in choice_list:
            choices.append(choice)

    df["signal"] = numpy.select(conditions, choices)

    return df


def signals_from_features_generate(df: pandas.DataFrame) -> pandas.DataFrame:
    df = rsi_indicator_apply(df=df)
    df, conditions_basic, signals_basic = rsi_signal_basic_generate(df=df)
    df, conditions_extended, signals_extended = rsi_signal_extended_generate(df=df)
    df, conditions_special, signals_special = rsi_signal_special_generate(df=df)

    return combined_signals_generate(
        df=df,
        condition_lists=[conditions_basic, conditions_extended, conditions_special],
        choice_lists=[signals_basic, signals_extended, signals_special],
    )
