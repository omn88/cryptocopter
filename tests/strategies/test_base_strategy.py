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


async def test_signal_handle_long_when_flat(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long()

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )


async def test_signal_handle_short_when_flat(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )


async def test_signal_handle_null_when_flat(base):
    base.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=base.strategy.df
    )

    df = base.strategy.df

    await base.strategy.process_signal()

    assert 0 == len(base.strategy.position_handler.position.orders)
    assert 1000 == base.strategy.balance
    assert base.strategy.state == State.FLAT.value
    assert df.at[df.index[-1], "Position"] == df.at[df.index[-2], "Position"]


async def test_signal_handle_long_when_long(base):
    df = base.strategy.df
    base.strategy.client.futures_create_order.side_effect = get_orders_long()

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )
    assert df.at[df.index[-1], "Position"] != df.at[df.index[-2], "Position"]

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )


async def test_signal_handle_short_when_long(base):
    df = base.strategy.df
    base.strategy.client.futures_create_order.side_effect = get_orders_long_then_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )

    assert df.at[df.index[-1], "Position"] != df.at[df.index[-2], "Position"]

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )


async def test_signal_handle_null_when_long(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long()

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )
    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )

    base.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert base.strategy.position_handler.config.number_of_orders == len(
        base.strategy.position_handler.position.orders
    )
    assert 1000 == base.strategy.balance
    assert base.strategy.state == base.strategy.position_handler.position.state
    assert all(
        order.price <= base.strategy.signal_update.price
        for order in base.strategy.position_handler.position.orders
    )


async def test_signal_handle_long_when_short(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short_then_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )


async def test_signal_handle_short_when_short(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )


async def test_signal_handle_null_when_short(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )

    base.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert base.strategy.position_handler.config.number_of_orders == len(
        base.strategy.position_handler.position.orders
    )
    assert 1000 == base.strategy.balance
    assert base.strategy.state == base.strategy.position_handler.position.state
    assert all(
        order.price >= base.strategy.signal_update.price
        for order in base.strategy.position_handler.position.orders
    )
