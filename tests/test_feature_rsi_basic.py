from unittest.mock import patch

from src.common.identifiers import Signal, State
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


async def test_signal_handle_long_when_flat(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

    basic_rsi.signal_update = generate_signal(signal=Signal.LONG, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )


async def test_signal_handle_short_when_flat(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()

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


async def test_signal_handle_long_when_long(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

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


async def test_signal_handle_short_when_long(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long_then_short()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()

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


async def test_signal_handle_null_when_long(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

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
    assert all(
        order.price <= basic_rsi.signal_update.price
        for order in basic_rsi.position.orders
    )


async def test_signal_handle_long_when_short(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_short_then_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()

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


async def test_signal_handle_short_when_short(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()

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


async def test_signal_handle_null_when_short(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
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
    assert all(
        order.price >= basic_rsi.signal_update.price
        for order in basic_rsi.position.orders
    )
