from src.identifiers.futures import Signal, State
from tests.futures import (
    assert_dca_long_opened,
    assert_dca_short_opened,
    generate_signal,
    get_cancel_order,
    get_orders_long,
    get_orders_long_then_short,
    get_orders_short,
    get_orders_short_then_long,
    validation_orders,
)


async def test_signal_handle_long_when_flat(base):
    base.model.client.futures_create_order.side_effect = get_orders_long()

    base.model.signal_update = generate_signal(
        signal=Signal.LONG, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_long_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )


async def test_signal_handle_short_when_flat(base):
    base.model.client.futures_create_order.side_effect = get_orders_short()

    base.model.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_short_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )


async def test_signal_handle_null_when_flat(base):
    base.model.signal_update = generate_signal(
        signal=Signal.NULL, df=base.model.df_handler.df
    )

    df = base.model.df_handler.df

    await base.model.process_signal()

    assert 0 == len(base.model.position_handler.position.orders)
    assert 1000 == base.model.balance
    assert base.model.state == State.FLAT.value
    assert df.at[df.index[-1], "Position"] == df.at[df.index[-2], "Position"]


async def test_signal_handle_long_when_long(base):
    df = base.model.df_handler.df
    base.model.client.futures_create_order.side_effect = get_orders_long()

    base.model.signal_update = generate_signal(
        signal=Signal.LONG, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_long_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )
    assert df.at[df.index[-1], "Position"] != df.at[df.index[-2], "Position"]

    await base.model.process_signal()

    assert_dca_long_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )


async def test_signal_handle_short_when_long(base):
    df = base.model.df_handler.df
    base.model.client.futures_create_order.side_effect = get_orders_long_then_short()
    base.model.client.futures_cancel_order.return_value = get_cancel_order()
    base.model.client.futures_get_order.side_effect = validation_orders()

    base.model.signal_update = generate_signal(
        signal=Signal.LONG, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_long_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )

    assert df.at[df.index[-1], "Position"] != df.at[df.index[-2], "Position"]

    base.model.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_short_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )


async def test_signal_handle_null_when_long(base):
    base.model.client.futures_create_order.side_effect = get_orders_long()

    base.model.signal_update = generate_signal(
        signal=Signal.LONG, df=base.model.df_handler.df
    )
    await base.model.process_signal()

    assert_dca_long_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )

    base.model.signal_update = generate_signal(
        signal=Signal.NULL, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert base.model.position_handler.config.number_of_orders == len(
        base.model.position_handler.position.orders
    )
    assert 1000 == base.model.balance
    assert base.model.state == base.model.position_handler.position.state
    assert all(
        order.price <= base.model.signal_update.price
        for order in base.model.position_handler.position.orders
    )


async def test_signal_handle_long_when_short(base):
    base.model.client.futures_create_order.side_effect = get_orders_short_then_long()
    base.model.client.futures_cancel_order.return_value = get_cancel_order()
    base.model.client.futures_get_order.side_effect = validation_orders()

    base.model.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_short_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )

    base.model.signal_update = generate_signal(
        signal=Signal.LONG, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_long_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )


async def test_signal_handle_short_when_short(base):
    base.model.client.futures_create_order.side_effect = get_orders_short()

    base.model.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_short_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )

    await base.model.process_signal()

    assert_dca_short_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )


async def test_signal_handle_null_when_short(base):
    base.model.client.futures_create_order.side_effect = get_orders_short()
    base.model.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert_dca_short_opened(
        position=base.model.position_handler.position,
        balance=base.model.balance,
        state=base.model.state,
        signal_update=base.model.signal_update,
        df=base.model.df_handler.df,
        number_of_orders=base.model.position_handler.config.number_of_orders,
    )

    base.model.signal_update = generate_signal(
        signal=Signal.NULL, df=base.model.df_handler.df
    )

    await base.model.process_signal()

    assert base.model.position_handler.config.number_of_orders == len(
        base.model.position_handler.position.orders
    )
    assert 1000 == base.model.balance
    assert base.model.state == base.model.position_handler.position.state
    assert all(
        order.price >= base.model.signal_update.price
        for order in base.model.position_handler.position.orders
    )
