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
    validation_orders,
)


async def test_signal_handle_long_when_flat(basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )


async def test_signal_handle_short_when_flat(basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = get_orders_short()

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )


async def test_signal_handle_null_when_flat(basic_rsi):
    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert 0 == len(basic_rsi.strategy.position.orders)
    assert 1000 == basic_rsi.strategy.balance
    assert basic_rsi.strategy.state == State.FLAT.value


async def test_signal_handle_long_when_long(basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_when_long(mock_save_to_file, basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = (
        get_orders_long_then_short()
    )
    basic_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    basic_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )


async def test_signal_handle_null_when_long(basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=basic_rsi.strategy.df
    )
    await basic_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert 4 == len(basic_rsi.strategy.position.orders)
    assert 1000 == basic_rsi.strategy.balance
    assert basic_rsi.strategy.state == basic_rsi.strategy.position.state
    assert all(
        order.price <= basic_rsi.strategy.signal_update.price
        for order in basic_rsi.strategy.position.orders
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_when_short(mock_save_to_file, basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = (
        get_orders_short_then_long()
    )
    basic_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    basic_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_long_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )


async def test_signal_handle_short_when_short(basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = get_orders_short()

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )


async def test_signal_handle_null_when_short(basic_rsi):
    basic_rsi.strategy.client.futures_create_order.side_effect = get_orders_short()
    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.strategy.position,
        balance=basic_rsi.strategy.balance,
        state=basic_rsi.strategy.state,
        signal_update=basic_rsi.strategy.signal_update,
        df=basic_rsi.strategy.df,
    )

    basic_rsi.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=basic_rsi.strategy.df
    )

    await basic_rsi.strategy.process_signal()

    assert 4 == len(basic_rsi.strategy.position.orders)
    assert 1000 == basic_rsi.strategy.balance
    assert basic_rsi.strategy.state == basic_rsi.strategy.position.state
    assert all(
        order.price >= basic_rsi.strategy.signal_update.price
        for order in basic_rsi.strategy.position.orders
    )
