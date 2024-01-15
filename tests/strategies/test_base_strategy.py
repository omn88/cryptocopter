from unittest.mock import patch
from src.common.constants import NUMBER_OF_DCA_ORDERS

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
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )


async def test_signal_handle_short_when_flat(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )


async def test_signal_handle_null_when_flat(base):
    base.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert 0 == len(base.strategy.position.orders)
    assert 1000 == base.strategy.balance
    assert base.strategy.state == State.FLAT.value


async def test_signal_handle_long_when_long(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long()

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_when_long(mock_save_to_file, base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long_then_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )


async def test_signal_handle_null_when_long(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long()

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )
    await base.strategy.process_signal()

    assert_dca_long_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )

    base.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert NUMBER_OF_DCA_ORDERS == len(base.strategy.position.orders)
    assert 1000 == base.strategy.balance
    assert base.strategy.state == base.strategy.position.state
    assert all(
        order.price <= base.strategy.signal_update.price
        for order in base.strategy.position.orders
    )


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_when_short(mock_save_to_file, base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short_then_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    import logging

    logger = logging.getLogger("test")
    logger.info(
        "expect flat, State: %s, type: %s",
        base.strategy.state,
        type(base.strategy.state),
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )

    base.strategy.signal_update = generate_signal(
        signal=Signal.LONG, df=base.strategy.df
    )

    await base.strategy.process_signal()

    logger.info("State: %s, type: %s", base.strategy.state, type(base.strategy.state))

    assert_dca_long_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )


async def test_signal_handle_short_when_short(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )


async def test_signal_handle_null_when_short(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df,
    )

    base.strategy.signal_update = generate_signal(
        signal=Signal.NULL, df=base.strategy.df
    )

    await base.strategy.process_signal()

    assert NUMBER_OF_DCA_ORDERS == len(base.strategy.position.orders)
    assert 1000 == base.strategy.balance
    assert base.strategy.state == base.strategy.position.state
    assert all(
        order.price >= base.strategy.signal_update.price
        for order in base.strategy.position.orders
    )
