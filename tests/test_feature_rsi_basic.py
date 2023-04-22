from unittest.mock import patch

import pandas

from src.common.identifiers import Signal, SignalUpdate, State, Position


def generate_signal(signal: Signal, df: pandas.DataFrame) -> SignalUpdate:
    entry_price = round(float(df.at[df.index[-1], "Close"]), 1)
    return SignalUpdate(signal=signal, price=entry_price)


def assert_dca_long_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert state == position.status
    assert all(order.price <= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


def assert_dca_short_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert state == position.status
    assert all(order.price >= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_flat(mock_create_orders_long, basic_rsi):

    basic_rsi.signal_update = generate_signal(signal=Signal.LONG, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_flat(mock_create_orders_short, basic_rsi):

    basic_rsi.signal_update = generate_signal(signal=Signal.SHORT, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )


async def test_signal_handle_null_when_flat(basic_rsi):

    basic_rsi.signal_update = generate_signal(signal=Signal.NULL, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert 0 == len(basic_rsi.position.orders)
    assert 1000 == basic_rsi.balance
    assert basic_rsi.state == State.FLAT


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long(mock_create_orders_long, basic_rsi):

    basic_rsi.signal_update = generate_signal(signal=Signal.LONG, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )

    await basic_rsi.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long(
    mock_create_orders_long_then_short, mock_cancel_order, basic_rsi
):
    basic_rsi.signal_update = generate_signal(signal=Signal.LONG, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )

    basic_rsi.signal_update = generate_signal(signal=Signal.SHORT, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long(mock_create_orders_long, basic_rsi):
    basic_rsi.signal_update = generate_signal(signal=Signal.LONG, df=basic_rsi.df)
    await basic_rsi.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )

    basic_rsi.signal_update = generate_signal(signal=Signal.NULL, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert 4 == len(basic_rsi.position.orders)
    assert 1000 == basic_rsi.balance
    assert basic_rsi.state == basic_rsi.position.status


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short(
    mock_create_orders_short_then_long, mock_cancel_order, basic_rsi
):

    basic_rsi.signal_update = generate_signal(signal=Signal.SHORT, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )

    basic_rsi.signal_update = generate_signal(signal=Signal.LONG, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short(mock_create_orders_short, basic_rsi):
    basic_rsi.signal_update = generate_signal(signal=Signal.SHORT, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )

    await basic_rsi.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short(mock_create_orders_short, basic_rsi):
    basic_rsi.signal_update = generate_signal(signal=Signal.SHORT, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )

    basic_rsi.signal_update = generate_signal(signal=Signal.NULL, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert 4 == len(basic_rsi.position.orders)
    assert 1000 == basic_rsi.balance
    assert basic_rsi.state == basic_rsi.position.status
