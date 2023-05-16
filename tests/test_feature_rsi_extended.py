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


async def test_signal_handle_long_twenty_when_flat(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()

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


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_eighty_when_flat(mock_save_to_file, extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_short()
    mock_save_to_file.return_value = True

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


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_twenty_when_long_twenty(
    mock_save_to_file, extended_rsi
):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    mock_save_to_file.return_value = True
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


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_eighty_when_long_twenty(
    mock_save_to_file, extended_rsi
):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True
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


async def test_signal_handle_null_when_long_twenty(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()

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


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_twenty_when_short_eighty(
    mock_save_to_file, extended_rsi
):
    extended_rsi.client.futures_create_order.side_effect = get_orders_short_then_long()
    mock_save_to_file.return_value = True

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


async def test_signal_handle_short_eighty_when_short_eighty(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_short()
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


async def test_signal_handle_null_when_short_eighty(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_short()
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


async def test_signal_handle_long_when_long_twenty(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
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


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_short_when_long_twenty(mock_save_to_file, extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True
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


@patch("src.workers.handle_order.save_to_file")
async def test_signal_handle_long_when_short_eighty(mock_save_to_file, extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_short_then_long()
    extended_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True
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


async def test_signal_handle_short_when_short_eighty(extended_rsi):
    extended_rsi.client.futures_create_order.side_effect = get_orders_short()
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
