from enum import Enum
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


def basic_rsi_signal_generate(df: pandas.DataFrame) -> pandas.DataFrame:
    assert "RSI" in df.columns

    df["RSIbelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
    df["RSIaboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)

    df["RSIBuy"] = numpy.where(df.RSIbThirty.diff() == 0, 1, 0) & numpy.where(
        df.RSIbThirty.diff(periods=2) == -1, 1, 0
    )
    df["RSISell"] = numpy.where(df.RSIaSeventy.diff() == 0, 1, 0) & numpy.where(
        df.RSIaSeventy.diff(periods=2) == -1, 1, 0
    )

    conditions = [
        (df.RSIbelowThirty.diff() == 0) & (df.RSIbelowThirty.diff(periods=2) == -1),
        (df.RSIaboveSeventy.diff() == 0) & (df.RSIaboveSeventy.diff(periods=2) == -1),
    ]

    signals = [Signals.LONG, Signals.SHORT]
    df["signal"] = numpy.select(conditions, signals)

    return df


def rsi_signal_extended_generate(df: pandas.DataFrame) -> pandas.DataFrame:
    assert "RSI" in df.columns
    assert "RSIbelowThirty" in df.columns
    assert "RSIaboveSeventy" in df.columns
    assert "RSIBuy" in df.columns
    assert "RSISell" in df.columns

    df["RSIbelowTwenty"] = numpy.where(df["RSI"] < 20, 1, 0)
    df["RSIaboveEighty"] = numpy.where(df["RSI"] > 80, 1, 0)

    df["RSIBuyTwenty"] = numpy.where(df.RSIbTwenty.diff() == -1, 1, 0)
    df["RSISellEighty"] = numpy.where(df.RSIaEighty.diff() == -1, 1, 0)

    conditions = [
        (df.RSIbelowThirty.diff() == 0) & (df.RSIbelowThirty.diff(periods=2) == -1),
        (df.RSIaboveSeventy.diff() == 0) & (df.RSIaboveSeventy.diff(periods=2) == -1),
    ]

    signals = [Signals.LONG_20, Signals.SHORT_80]
    df["signal"] = numpy.select(conditions, signals)

    return df
