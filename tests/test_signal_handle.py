from unittest.mock import patch

import pytest
import logging

from src.common.identifiers import Signal, SignalUpdate, State

logger = logging.getLogger("test_signal_handle")


@pytest.mark.parametrize("signal", [Signal.LONG, Signal.LONG_20])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long_twenty(
    mock_create_order, mock_get_order, signal, basic_rsi
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signal.LONG_20
    entry_price = round(float(basic_rsi.df.at[basic_rsi.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await basic_rsi.process_signal()

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    await basic_rsi.process_signal()

    assert 4 == len(current_position.orders)
    assert 1000 == basic_rsi.position.balance
    assert signal == current_position.status

    assert all(order.entry_price <= entry_price for order in current_position.orders)
    assert basic_rsi.df.iloc[-1]["position"] == signal


@pytest.mark.parametrize("signal", [Signal.SHORT, Signal.SHORT_80])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long_twenty(
    mock_create_order, mock_cancel_order, mock_get_order, signal, basic_rsi
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signal.LONG_20
    entry_price = round(float(basic_rsi.df.at[basic_rsi.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await basic_rsi.process_signal()

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    await basic_rsi.process_signal()

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    await basic_rsi.process_signal()

    assert 4 == len(current_position.orders)
    assert 1000 == basic_rsi.position.balance
    assert signal == current_position.status

    assert all(order.entry_price >= entry_price for order in current_position.orders)
    assert basic_rsi.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long_twenty(
    mock_create_order, mock_get_order, basic_rsi
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signal.LONG_20
    entry_price = round(float(basic_rsi.df.at[basic_rsi.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await basic_rsi.process_signal()

    position_status = current_position.status
    signal = Signal.NULL
    signal_update = SignalUpdate(signal=signal, price=entry_price)

    await basic_rsi.process_signal()

    assert 4 == len(current_position.orders)
    assert 1000 == basic_rsi.position.balance
    assert position_status == current_position.status

    assert all(order.entry_price <= entry_price for order in current_position.orders)
    assert basic_rsi.df.iloc[-1]["position"] == entry_signal


@pytest.mark.parametrize("signal", [Signal.LONG, Signal.LONG_20])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short_eighty(
    mock_create_order, mock_cancel_order, mock_get_order, signal, basic_rsi
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    mock_cancel_order.return_value = {"status": "CANCELED"}

    entry_signal = Signal.SHORT_80
    entry_price = round(float(basic_rsi.df.at[basic_rsi.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await basic_rsi.process_signal()

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    await basic_rsi.process_signal()

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    await basic_rsi.process_signal()

    assert 4 == len(current_position.orders)
    assert 1000 == basic_rsi.position.balance
    assert signal == current_position.status

    assert all(order.entry_price <= entry_price for order in current_position.orders)
    assert basic_rsi.df.iloc[-1]["position"] == signal


@pytest.mark.parametrize("signal", [Signal.SHORT, Signal.SHORT_80])
@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short_eighty(
    mock_create_order, mock_get_order, signal, basic_rsi
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }

    entry_signal = Signal.SHORT_80
    entry_price = round(float(basic_rsi.df.at[basic_rsi.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await basic_rsi.process_signal()

    signal_update = SignalUpdate(signal=signal, price=entry_price)

    await basic_rsi.process_signal()

    assert 4 == len(current_position.orders)
    assert 1000 == basic_rsi.position.balance
    assert signal == current_position.status

    assert all(order.entry_price >= entry_price for order in current_position.orders)
    assert basic_rsi.df.iloc[-1]["position"] == signal


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short_eighty(
    mock_create_order, mock_get_order, basic_rsi
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
    }

    mock_get_order.return_value = {
        "orderId": 1,
        "price": 19567.72,
        "status": basic_rsi.client.ORDER_STATUS_NEW,
        "executedQty": 0.0,
    }
    entry_signal = Signal.SHORT_80
    entry_price = round(float(basic_rsi.df.at[basic_rsi.df.index[-1], "Close"]), 1)
    signal_update = SignalUpdate(signal=entry_signal, price=entry_price)

    await basic_rsi.process_signal()

    position_status = current_position.status

    signal_update = SignalUpdate(signal=Signal.NULL, price=entry_price)

    await basic_rsi.process_signal()

    assert 4 == len(current_position.orders)
    assert 1000 == basic_rsi.position.balance
    assert position_status == current_position.status

    logger.info("Entry: %s", entry_price)

    for order in current_position.orders:
        logger.info(order)

    assert all(order.entry_price >= entry_price for order in current_position.orders)
    assert basic_rsi.df.iloc[-1]["position"] == entry_signal
