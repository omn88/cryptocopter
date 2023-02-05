from unittest.mock import patch

import pytest
from src.producers.producers import SignalUpdate
from src.workers.handle_signal import signal_handle
from src.features import Signals
import logging


logger = logging.getLogger("test_signal_handle")


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_flat(
    mock_create_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status
    assert all(order.price <= entry_price for order in current_position.orders)
    assert base.df.at[base.df.index[-1], "position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_flat(
    mock_create_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status
    assert all(order.price >= entry_price for order in current_position.orders)
    assert base.df.at[base.df.index[-1], "position"] == signal


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_flat(mock_create_order, mock_get_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    entry_signal = Signals.NULL

    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert len(current_position.orders) == 0
    assert 1000 == base.position.balance
    assert Signals.FLAT == current_position.status
    assert base.df.at[base.df.index[-1], "position"] == Signals.FLAT


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long(
    mock_create_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signals.LONG
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert entry_signal == current_position.status

    assert all(order.price <= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long(
    mock_create_order, mock_cancel_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.LONG
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status

    assert all(
        order.price >= round(entry_price, 1) for order in current_position.orders
    )
    assert base.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long(mock_create_order, mock_get_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signals.LONG
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    position_status = current_position.status
    signal = Signals.NULL

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert position_status == current_position.status

    assert all(order.price <= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short(
    mock_create_order, mock_cancel_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.SHORT
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status

    assert all(order.price <= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_get_order")
@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short(
    mock_create_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signals.SHORT
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert entry_signal == current_position.status

    assert all(order.price >= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short(mock_create_order, mock_get_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signals.SHORT
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    position_status = current_position.status
    signal = Signals.NULL
    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert position_status == current_position.status

    assert all(order.price >= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long_twenty(
    mock_create_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signals.LONG_20
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status

    assert all(order.price <= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long_twenty(
    mock_create_order, mock_cancel_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.LONG_20
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status

    assert all(order.price >= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long_twenty(
    mock_create_order, mock_get_order, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signals.LONG_20
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    position_status = current_position.status
    signal = Signals.NULL
    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert position_status == current_position.status

    assert all(order.price <= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short_eighty(
    mock_create_order, mock_cancel_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signals.SHORT_80
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status

    assert all(order.price <= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short_eighty(
    mock_create_order, mock_get_order, signal, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signals.SHORT_80
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert signal == current_position.status

    assert all(order.price >= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short_eighty(
    mock_create_order, mock_get_order, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": base.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    entry_signal = Signals.SHORT_80
    entry_price = round(float(base.df.at[base.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=base.position.current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    position_status = current_position.status

    signal_update = SignalUpdate(signal=Signals.NULL, price=entry_price)

    current_position, base.df = await signal_handle(
        signal_update=signal_update,
        client=base.client,
        current_position=current_position,
        df=base.df,
        balance=base.position.balance,
        symbol=base.symbol,
        leverage=base.position.leverage,
        number_of_dca_orders=base.position.number_of_dca_orders,
        order_quantity_list=base.position.order_quantity_list,
    )

    assert 4 == len(current_position.orders)
    assert 1000 == base.position.balance
    assert position_status == current_position.status

    logger.info("Entry: %s", entry_price)

    for order in current_position.orders:
        logger.info(order)

    assert all(order.price >= entry_price for order in current_position.orders)
    assert base.df.iloc[-1]["position"] == entry_signal
