from unittest.mock import patch

from src.common.identifiers import Signal
from tests.common import (
    generate_signal,
    assert_dca_long_opened,
    assert_dca_short_opened,
    get_orders_long,
    get_orders_short,
    get_orders_long_then_short,
    get_cancel_order,
    get_orders_short_then_long,
)


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_twenty_when_flat(
    mock_create_orders_long, extended_rsi
):

    mock_create_orders_long.side_effect = get_orders_long(base=extended_rsi)

    extended_rsi.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_eighty_when_flat(
    mock_create_orders_short, extended_rsi
):
    mock_create_orders_short.side_effect = get_orders_short(base=extended_rsi)

    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_twenty_when_long_twenty(
    mock_create_orders_long, extended_rsi
):
    mock_create_orders_long.side_effect = get_orders_long(base=extended_rsi)

    extended_rsi.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_eighty_when_long_twenty(
    mock_create_orders_long_then_short, mock_cancel_order, extended_rsi
):
    mock_create_orders_long_then_short.side_effect = get_orders_long_then_short(
        base=extended_rsi
    )
    mock_cancel_order.return_value = get_cancel_order()

    extended_rsi.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long_twenty(
    mock_create_orders_long, extended_rsi
):
    mock_create_orders_long.side_effect = get_orders_long(base=extended_rsi)

    extended_rsi.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.df
    )
    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(signal=Signal.NULL, df=extended_rsi.df)

    await extended_rsi.process_signal()

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.state == extended_rsi.position.status
    assert all(
        order.price <= extended_rsi.signal_update.price
        for order in extended_rsi.position.orders
    )


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_twenty_when_short_eighty(
    mock_create_orders_short_then_long, mock_cancel_order, extended_rsi
):

    mock_create_orders_short_then_long.side_effect = get_orders_short_then_long(
        base=extended_rsi
    )
    mock_cancel_order.return_value = get_cancel_order()

    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_eighty_when_short_eighty(
    mock_create_orders_short, extended_rsi
):
    mock_create_orders_short.side_effect = get_orders_short(base=extended_rsi)
    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short_eighty(
    mock_create_orders_short, extended_rsi
):
    mock_create_orders_short.side_effect = get_orders_short(base=extended_rsi)
    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(signal=Signal.NULL, df=extended_rsi.df)

    await extended_rsi.process_signal()

    assert 4 == len(extended_rsi.position.orders)
    assert 1000 == extended_rsi.balance
    assert extended_rsi.state == extended_rsi.position.status
    assert all(
        order.price >= extended_rsi.signal_update.price
        for order in extended_rsi.position.orders
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long_twenty(
    mock_create_orders_long, extended_rsi
):
    mock_create_orders_long.side_effect = get_orders_long(base=extended_rsi)
    extended_rsi.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.df
    )

    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(signal=Signal.LONG, df=extended_rsi.df)

    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long_twenty(
    mock_create_orders_long, mock_cancel_order, extended_rsi
):
    mock_create_orders_long.side_effect = get_orders_long(base=extended_rsi)
    mock_cancel_order.return_value = get_cancel_order()

    extended_rsi.signal_update = generate_signal(
        signal=Signal.LONG_EXT, df=extended_rsi.df
    )
    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT, df=extended_rsi.df
    )
    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short_eighty(
    mock_create_orders_short_then_long, mock_cancel_order, extended_rsi
):
    mock_create_orders_short_then_long.side_effect = get_orders_short_then_long(
        base=extended_rsi
    )
    mock_cancel_order.return_value = get_cancel_order()
    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.df
    )
    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(signal=Signal.LONG, df=extended_rsi.df)
    await extended_rsi.process_signal()

    assert_dca_long_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short_eighty(
    mock_create_orders_short, extended_rsi
):
    mock_create_orders_short.side_effect = get_orders_short(base=extended_rsi)
    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT_EXT, df=extended_rsi.df
    )
    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )

    extended_rsi.signal_update = generate_signal(
        signal=Signal.SHORT, df=extended_rsi.df
    )
    await extended_rsi.process_signal()

    assert_dca_short_opened(
        position=extended_rsi.position,
        balance=extended_rsi.balance,
        state=extended_rsi.state,
        signal_update=extended_rsi.signal_update,
        df=extended_rsi.df,
    )
