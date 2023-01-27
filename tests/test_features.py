import pandas

from src.features import (
    rsi_indicator_apply,
    rsi_signal_extended_generate,
    rsi_signal_basic_generate,
    Signals,
    combined_signals_generate,
)


def test_basic_rsi_signal_generate():
    test_df = pandas.read_csv("tests/data/sample_data_for_rsi_calculactions.csv")
    test_df = test_df.set_index("Date")

    expected_data = [
        ["2022-10-18 10:30:00", 49.76, 0, 0, 0],
        ["2022-10-18 10:45:00", 30.98, 0, 0, 0],
        ["2022-10-18 11:00:00", 21.27, 1, 0, 0],
        ["2022-10-18 11:15:00", 19.13, 1, 0, 0],
        ["2022-10-18 11:30:00", 27.05, 1, 0, 0],
        ["2022-10-18 11:45:00", 34.04, 0, 0, 0],
        ["2022-10-18 12:00:00", 54.43, 0, 0, Signals.LONG],
        ["2022-10-18 12:15:00", 66.42, 0, 0, 0],
        ["2022-10-18 12:30:00", 74.24, 0, 1, 0],
        ["2022-10-18 12:45:00", 82.86, 0, 1, 0],
        ["2022-10-18 13:00:00", 70.23, 0, 1, 0],
        ["2022-10-18 13:15:00", 62.05, 0, 0, 0],
        ["2022-10-18 13:30:00", 70.39, 0, 1, 0],
        ["2022-10-18 13:45:00", 54.61, 0, 0, 0],
        ["2022-10-18 14:00:00", 48.25, 0, 0, Signals.SHORT],
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
        "signal",
    ]
    expected_df = expected_df.set_index("Date")

    test_df = rsi_indicator_apply(df=test_df)
    assert "RSI" in test_df.columns
    test_df.RSI = test_df.RSI.round(2)

    test_df, conditions_basic, signals_basic = rsi_signal_basic_generate(df=test_df)
    assert "RsiBelowThirty" in test_df.columns
    assert "RsiAboveSeventy" in test_df.columns

    test_df = combined_signals_generate(
        df=test_df, condition_lists=[conditions_basic], choice_lists=[signals_basic]
    )

    test_df_shortened = test_df[
        ["RSI", "RsiBelowThirty", "RsiAboveSeventy", "signal"]
    ].copy()

    pandas.testing.assert_frame_equal(
        left=test_df_shortened, right=expected_df, check_dtype=False
    )


def test_rsi_signal_extended_generate():
    test_df = pandas.read_csv("tests/data/sample_data_for_rsi_calculactions.csv")
    test_df = test_df.set_index("Date")

    expected_data = [
        ["2022-10-18 10:30:00", 49.76, 0, 0, 0, 0, 0],
        ["2022-10-18 10:45:00", 30.98, 0, 0, 0, 0, 0],
        ["2022-10-18 11:00:00", 21.27, 1, 0, 0, 0, 0],
        ["2022-10-18 11:15:00", 19.13, 1, 0, 1, 0, 0],
        ["2022-10-18 11:30:00", 27.05, 1, 0, 0, 0, Signals.LONG_20],
        ["2022-10-18 11:45:00", 34.04, 0, 0, 0, 0, 0],
        ["2022-10-18 12:00:00", 54.43, 0, 0, 0, 0, Signals.LONG],
        ["2022-10-18 12:15:00", 66.42, 0, 0, 0, 0, 0],
        ["2022-10-18 12:30:00", 74.24, 0, 1, 0, 0, 0],
        ["2022-10-18 12:45:00", 82.86, 0, 1, 0, 1, 0],
        ["2022-10-18 13:00:00", 70.23, 0, 1, 0, 0, Signals.SHORT_80],
        ["2022-10-18 13:15:00", 62.05, 0, 0, 0, 0, 0],
        ["2022-10-18 13:30:00", 70.39, 0, 1, 0, 0, 0],
        ["2022-10-18 13:45:00", 54.61, 0, 0, 0, 0, 0],
        ["2022-10-18 14:00:00", 48.25, 0, 0, 0, 0, Signals.SHORT],
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
        "signal",
    ]
    expected_df = expected_df.set_index("Date")

    test_df = rsi_indicator_apply(df=test_df)
    assert "RSI" in test_df.columns
    test_df.RSI = test_df.RSI.round(2)

    test_df, conditions_basic, choices_basic = rsi_signal_basic_generate(df=test_df)
    assert "RsiBelowThirty" in test_df.columns
    assert "RsiAboveSeventy" in test_df.columns

    test_df, conditions_extended, choices_extended = rsi_signal_extended_generate(
        df=test_df
    )
    assert "RsiBelowTwenty" in test_df.columns
    assert "RsiAboveEighty" in test_df.columns

    test_df = combined_signals_generate(
        df=test_df,
        condition_lists=[conditions_basic, conditions_extended],
        choice_lists=[choices_basic, choices_extended],
    )

    test_df_shortened = test_df[
        [
            "RSI",
            "RsiBelowThirty",
            "RsiAboveSeventy",
            "RsiBelowTwenty",
            "RsiAboveEighty",
            "signal",
        ]
    ].copy()

    pandas.testing.assert_frame_equal(left=test_df_shortened, right=expected_df)
