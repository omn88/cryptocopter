from unittest.mock import patch

import pytest
from src.producers.producers import SignalUpdate
from src.workers.handle_signal import signal_handle
from src.features import Signals
import logging


logger = logging.getLogger("test_signal_handle")


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_flat(mock_create_order, signal, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status
    assert all(order.price <= entry_price for order in position.current_position.orders)
    assert base.df.at[base.df.index[-1], "position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_flat(mock_create_order, signal, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status
    assert all(order.price >= entry_price for order in position.current_position.orders)
    assert base.df.at[base.df.index[-1], "position"] == signal


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_flat(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    entry_signal = Signals.NULL

    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert len(position.current_position.orders) == 0
    assert 1000 == position.balance
    assert Signals.FLAT == position.current_position.status
    assert base.df.at[base.df.index[-1], "position"] == Signals.FLAT


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long(mock_create_order, signal, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_signal = Signals.LONG
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert entry_signal == position.current_position.status

    assert all(order.price <= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.LONG
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status

    assert all(
        order.price >= round(entry_price, 1)
        for order in position.current_position.orders
    )
    assert base.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_signal = Signals.LONG
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    position_status = position.current_position.status
    signal = Signals.NULL

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert position_status == position.current_position.status

    assert all(order.price <= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.SHORT
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status

    assert all(order.price <= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short(mock_create_order, signal, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_signal = Signals.SHORT
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert entry_signal == position.current_position.status

    assert all(order.price >= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_signal = Signals.SHORT
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    position_status = position.current_position.status
    signal = Signals.NULL
    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert position_status == position.current_position.status

    assert all(order.price >= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long_twenty(mock_create_order, signal, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_signal = Signals.LONG_20
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status

    assert all(order.price <= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long_twenty(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.LONG_20
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status

    assert all(order.price >= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long_twenty(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_signal = Signals.LONG_20
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    position_status = position.current_position.status
    signal = Signals.NULL
    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert position_status == position.current_position.status

    assert all(order.price <= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short_eighty(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.SHORT_80
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status

    assert all(order.price <= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short_eighty(mock_create_order, signal, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    entry_signal = Signals.SHORT_80
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert signal == position.current_position.status

    assert all(order.price >= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short_eighty(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }
    entry_signal = Signals.SHORT_80
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=base.position,
        df=base.df,
    )

    position_status = position.current_position.status
    signal_update = SignalUpdate(signal=Signals.NULL, price=entry_price)
    base.df, position = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        position=position,
        df=base.df,
    )

    assert 4 == len(position.current_position.orders)
    assert 1000 == position.balance
    assert position_status == position.current_position.status

    logger.info("Entry: %s", entry_price)

    for order in position.current_position.orders:
        logger.info(order)

    assert all(order.price >= entry_price for order in position.current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal
