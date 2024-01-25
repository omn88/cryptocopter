from unittest.mock import patch
import logging
import pandas
from src.common.common import rsi_indicator_apply

from src.common.identifiers import KlineUpdate, Signal, State
from src.strategies.rsi_extended import RsiExtended
from src.workers.trading_state_machine import TradingStateMachine
from tests.common import (
    generate_signal,
    assert_dca_long_opened,
    assert_dca_short_opened,
    get_orders_long,
    get_orders_short,
    get_orders_long_then_short,
    get_cancel_order,
    get_orders_short_then_long,
    validation_orders,
)


logger = logging.getLogger("test_rsi_extended")


def test_rsi_signal_extended_generate(extended_rsi: TradingStateMachine):
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

    assert isinstance(extended_rsi.strategy, RsiExtended)

    test_df = rsi_indicator_apply(df=test_df)
    assert "RSI" in test_df.columns
    test_df.RSI = test_df.RSI.round(2)
    test_df = extended_rsi.strategy.add_columns_for_rsi_basic(df=test_df)
    test_df = extended_rsi.strategy.add_columns_for_rsi_extended(df=test_df)
    extended_rsi.strategy.conditions = (
        extended_rsi.strategy.get_conditions_for_rsi_basic(df=test_df)
        + extended_rsi.strategy.get_conditions_for_rsi_extended(df=test_df)
    )
    test_df = extended_rsi.strategy.signals_from_features_generate(
        test_df,
        conditions=extended_rsi.strategy.conditions,
        signals=extended_rsi.strategy.signals,
    )

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


async def test_signal_handle_long_twenty_when_flat(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_eighty_when_flat(mock_save_to_file, extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_short()
    mock_save_to_file.return_value = True

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_twenty_when_long_twenty(
    mock_save_to_file, extended_rsi
):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    mock_save_to_file.return_value = True
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_eighty_when_long_twenty(
    mock_save_to_file, extended_rsi
):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    extended_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


async def test_signal_handle_null_when_long_twenty(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.strategy.df
    )
    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert (
        extended_rsi.strategy.state
        == extended_rsi.strategy.position_handler.position.state
    )
    assert all(
        order.price <= extended_rsi.strategy.signal_update.price
        for order in extended_rsi.strategy.position_handler.position.orders
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_twenty_when_short_eighty(
    mock_save_to_file, extended_rsi
):
    extended_rsi.strategy.client.futures_create_order.side_effect = (
        get_orders_short_then_long()
    )
    extended_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


async def test_signal_handle_short_eighty_when_short_eighty(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_short()
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


async def test_signal_handle_null_when_short_eighty(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_short()
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert (
        extended_rsi.strategy.state
        == extended_rsi.strategy.position_handler.position.state
    )
    assert all(
        order.price >= extended_rsi.strategy.signal_update.price
        for order in extended_rsi.strategy.position_handler.position.orders
    )


async def test_signal_handle_long_when_long_twenty(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=extended_rsi.strategy.df
    )

    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_when_long_twenty(mock_save_to_file, extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    extended_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.strategy.df
    )
    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=extended_rsi.strategy.df
    )
    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_when_short_eighty(mock_save_to_file, extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = (
        get_orders_short_then_long()
    )
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    extended_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.strategy.df
    )
    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=extended_rsi.strategy.df
    )
    await extended_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


async def test_signal_handle_short_when_short_eighty(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_short()
    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.strategy.df
    )
    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )

    extended_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=extended_rsi.strategy.df
    )
    await extended_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.strategy.position_handler.position,
        balance=extended_rsi.strategy.balance,
        state=extended_rsi.strategy.state,
        signal_update=extended_rsi.strategy.signal_update,
        df=extended_rsi.strategy.df,
        number_of_orders=extended_rsi.strategy.position_handler.number_of_orders,
    )


async def test_rsi_basic_handle_kline_long_ext(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()

    # NO SIGNAL THEN NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672306200000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="17160.1",
        close_price="16700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()

    assert len(extended_rsi.strategy.position_handler.position.orders) == 0
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.FLAT

    # NO SIGNAL THEN NULL LONG EXT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672307100000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="18500.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert (
        len(extended_rsi.strategy.position_handler.position.orders)
        == extended_rsi.strategy.position_handler.number_of_orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG_EXT


async def test_rsi_basic_handle_kline_long_ext_long(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()

    # NO SIGNAL THEN NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672306200000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="17160.1",
        close_price="16700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()

    assert len(extended_rsi.strategy.position_handler.position.orders) == 0
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.FLAT

    # NO SIGNAL THEN NULL LONG EXT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672307100000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="18500.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert (
        len(extended_rsi.strategy.position_handler.position.orders)
        == extended_rsi.strategy.position_handler.number_of_orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG_EXT

    # NO SIGNAL THEN NULL LONG EXT LONG
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308000000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="27000.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG


async def test_rsi_basic_handle_kline_long_ext_long_null(extended_rsi):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()

    # NO SIGNAL THEN NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672306200000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="17160.1",
        close_price="16700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()

    assert len(extended_rsi.strategy.position_handler.position.orders) == 0
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.FLAT

    # NO SIGNAL THEN NULL LONG EXT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672307100000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="18500.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert (
        len(extended_rsi.strategy.position_handler.position.orders)
        == extended_rsi.strategy.position_handler.number_of_orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG_EXT

    # NO SIGNAL THEN NULL LONG EXT LONG
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308000000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="27000.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308900000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="29700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG


@patch("src.workers.handle_order.save_to_file")
async def test_rsi_basic_handle_kline_long_ext_long_null_short_ext(
    mock_save_to_file, extended_rsi
):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    extended_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    # NO SIGNAL THEN NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672306200000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="17160.1",
        close_price="16700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()

    assert len(extended_rsi.strategy.position_handler.position.orders) == 0
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.FLAT

    # NO SIGNAL THEN NULL LONG EXT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672307100000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="18500.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert (
        len(extended_rsi.strategy.position_handler.position.orders)
        == extended_rsi.strategy.position_handler.number_of_orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG_EXT

    # NO SIGNAL THEN NULL LONG EXT LONG
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308000000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="27000.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308900000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="29700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG_EXT LONG NULL SHORT_EXT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672309800000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="26200.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.SHORT_EXT


@patch("src.workers.handle_order.save_to_file")
async def test_rsi_basic_handle_kline_long_ext_long_null_short_ext_short(
    mock_save_to_file,
    extended_rsi,
):
    extended_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    extended_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    # NO SIGNAL THEN NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672306200000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="17160.1",
        close_price="16700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()

    assert len(extended_rsi.strategy.position_handler.position.orders) == 0
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.FLAT

    # NO SIGNAL THEN NULL LONG EXT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672307100000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="18500.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert (
        len(extended_rsi.strategy.position_handler.position.orders)
        == extended_rsi.strategy.position_handler.number_of_orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG_EXT

    # NO SIGNAL THEN NULL LONG EXT LONG
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308000000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="27000.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308900000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="29700.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG_EXT LONG NULL SHORT_EXT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672309800000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="26200.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.SHORT_EXT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT
    extended_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672310700000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="22200.72",
        volume="0",
        open_interest="0",
    )

    await extended_rsi.strategy.process_kline()
    await extended_rsi.strategy.process_signal()

    assert extended_rsi.strategy.position_handler.number_of_orders == len(
        extended_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == extended_rsi.strategy.balance
    assert extended_rsi.strategy.position_handler.position.state == State.SHORT
