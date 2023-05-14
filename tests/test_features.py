import pandas

from src.common.common import rsi_indicator_apply
from src.common.identifiers import Signal
import logging

logger = logging.getLogger("test_features")


def test_basic_rsi_signal_generate(basic_rsi):
    test_df = pandas.read_csv("tests/data/sample_data_for_rsi_calculactions.csv")
    test_df = test_df.set_index("Date")

    expected_data = [
        ["2022-10-18 10:30:00", 49.76, 0, 0, 0],
        ["2022-10-18 10:45:00", 30.98, 0, 0, 0],
        ["2022-10-18 11:00:00", 21.27, 1, 0, 0],
        ["2022-10-18 11:15:00", 19.13, 1, 0, 0],
        ["2022-10-18 11:30:00", 27.05, 1, 0, 0],
        ["2022-10-18 11:45:00", 34.04, 0, 0, 0],
        ["2022-10-18 12:00:00", 54.43, 0, 0, Signal.LONG],
        ["2022-10-18 12:15:00", 66.42, 0, 0, 0],
        ["2022-10-18 12:30:00", 74.24, 0, 1, 0],
        ["2022-10-18 12:45:00", 82.86, 0, 1, 0],
        ["2022-10-18 13:00:00", 70.23, 0, 1, 0],
        ["2022-10-18 13:15:00", 62.05, 0, 0, 0],
        ["2022-10-18 13:30:00", 70.39, 0, 1, 0],
        ["2022-10-18 13:45:00", 54.61, 0, 0, 0],
        ["2022-10-18 14:00:00", 48.25, 0, 0, Signal.SHORT],
        ["2022-10-18 14:15:00", 54.02, 0, 0, 0],
        ["2022-10-18 14:30:00", 51.93, 0, 0, 0],
        ["2022-10-18 14:45:00", 46.42, 0, 0, 0],
        ["2022-10-18 15:00:00", 46.16, 0, 0, 0],
    ]

    expected_df = pandas.DataFrame(data=expected_data)
    expected_df = expected_df.iloc[:, :5]
    expected_df.columns = [
        "Date",
        "RSI",
        "RsiBelowThirty",
        "RsiAboveSeventy",
        "Signal",
    ]
    expected_df = expected_df.set_index("Date")

    test_df = rsi_indicator_apply(df=test_df)
    assert "RSI" in test_df.columns
    test_df.RSI = test_df.RSI.round(2)

    logger.info("Test DF with RSI: %s", test_df)

    test_df = basic_rsi.signals_from_features_generate(test_df)

    logger.info("Test DF with signals: %s", test_df)

    assert "RsiBelowThirty" in test_df.columns
    assert "RsiAboveSeventy" in test_df.columns

    test_df_shortened = test_df[
        ["RSI", "RsiBelowThirty", "RsiAboveSeventy", "Signal"]
    ].copy()

    pandas.testing.assert_frame_equal(
        left=test_df_shortened, right=expected_df, check_dtype=False
    )


def test_rsi_signal_extended_generate(extended_rsi):
    test_df = pandas.read_csv("tests/data/sample_data_for_rsi_calculactions.csv")
    test_df = test_df.set_index("Date")

    expected_data = [
        ["2022-10-18 10:30:00", 49.76, 0, 0, 0, 0, 0],
        ["2022-10-18 10:45:00", 30.98, 0, 0, 0, 0, 0],
        ["2022-10-18 11:00:00", 21.27, 1, 0, 0, 0, 0],
        ["2022-10-18 11:15:00", 19.13, 1, 0, 1, 0, 0],
        ["2022-10-18 11:30:00", 27.05, 1, 0, 0, 0, Signal.LONG_EXT],
        ["2022-10-18 11:45:00", 34.04, 0, 0, 0, 0, 0],
        ["2022-10-18 12:00:00", 54.43, 0, 0, 0, 0, Signal.LONG],
        ["2022-10-18 12:15:00", 66.42, 0, 0, 0, 0, 0],
        ["2022-10-18 12:30:00", 74.24, 0, 1, 0, 0, 0],
        ["2022-10-18 12:45:00", 82.86, 0, 1, 0, 1, 0],
        ["2022-10-18 13:00:00", 70.23, 0, 1, 0, 0, Signal.SHORT_EXT],
        ["2022-10-18 13:15:00", 62.05, 0, 0, 0, 0, 0],
        ["2022-10-18 13:30:00", 70.39, 0, 1, 0, 0, 0],
        ["2022-10-18 13:45:00", 54.61, 0, 0, 0, 0, 0],
        ["2022-10-18 14:00:00", 48.25, 0, 0, 0, 0, Signal.SHORT],
        ["2022-10-18 14:15:00", 54.02, 0, 0, 0, 0, 0],
        ["2022-10-18 14:30:00", 51.93, 0, 0, 0, 0, 0],
        ["2022-10-18 14:45:00", 46.42, 0, 0, 0, 0, 0],
        ["2022-10-18 15:00:00", 46.16, 0, 0, 0, 0, 0],
    ]

    expected_df = pandas.DataFrame(data=expected_data)
    expected_df = expected_df.iloc[:, :7]
    expected_df.columns = [
        "Date",
        "RSI",
        "RsiBelowThirty",
        "RsiAboveSeventy",
        "RsiBelowTwenty",
        "RsiAboveEighty",
        "Signal",
    ]
    expected_df = expected_df.set_index("Date")

    test_df = rsi_indicator_apply(df=test_df)
    assert "RSI" in test_df.columns
    test_df.RSI = test_df.RSI.round(2)

    test_df = extended_rsi.signals_from_features_generate(test_df)

    test_df_shortened = test_df[
        [
            "RSI",
            "RsiBelowThirty",
            "RsiAboveSeventy",
            "RsiBelowTwenty",
            "RsiAboveEighty",
            "Signal",
        ]
    ].copy()

    pandas.testing.assert_frame_equal(left=test_df_shortened, right=expected_df)
