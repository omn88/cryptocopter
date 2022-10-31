from enum import Enum, auto
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
    FLAT = "FLAT"


def rsi_indicator_apply(df: pandas.DataFrame) -> pandas.DataFrame:
    rsi = btalib.rsi(df, period=14)
    df["RSI"] = rsi.df
    df.dropna(inplace=True)

    return df


def rsi_signal_basic_generate(df: pandas.DataFrame) -> pandas.DataFrame:
    assert "RSI" in df.columns

    df["RSIbelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
    df["RSIaboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)

    conditions = [
        (df.RSIbelowThirty.diff() == 0) & (df.RSIbelowThirty.diff(periods=2) == -1),
        (df.RSIaboveSeventy.diff() == 0) & (df.RSIaboveSeventy.diff(periods=2) == -1),
    ]

    signals = [Signals.LONG, Signals.SHORT]
    df["signal"] = numpy.select(conditions, signals)
    df.dropna(inplace=True)

    return df


def rsi_signal_extended_generate(df: pandas.DataFrame) -> pandas.DataFrame:
    assert "RSI" in df.columns

    df["RSIbelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
    df["RSIaboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)
    df["RSIbelowTwenty"] = numpy.where(df["RSI"] < 20, 1, 0)
    df["RSIaboveEighty"] = numpy.where(df["RSI"] > 80, 1, 0)

    conditions = [
        (df.RSIbelowThirty.diff() == 0) & (df.RSIbelowThirty.diff(periods=2) == -1),
        (df.RSIaboveSeventy.diff() == 0) & (df.RSIaboveSeventy.diff(periods=2) == -1),
        (df.RSIbelowTwenty.diff() == -1),
        (df.RSIaboveEighty.diff() == -1),
    ]

    signals = [Signals.LONG, Signals.SHORT, Signals.LONG_20, Signals.SHORT_80]
    df["signal"] = numpy.select(conditions, signals)
    df.dropna(inplace=True)

    return df
