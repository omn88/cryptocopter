from unittest.mock import patch

import pytest
from src.orders import Position
from src.producers.producers import determine_start_position
from src.workers.signal import (
    when_flat,
    when_long,
    when_short,
    when_long_twenty,
    when_short_eighty,
)
from src.features import Signals
import logging


logger = logging.getLogger("test_signal_handle")


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_flat(mock_create_order, signal, base):
    mock_create_order.return_value = {"orderId": 1}
    position = Position(symbol=base.symbol, saldo=1000)
    entry_price = base.df.at[base.df.index[-1], "Close"]

    base.df, position = await when_flat(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status
    assert all(order.price <= entry_price for order in position.orders)
    assert base.df.at[base.df.index[-1], "position"] == signal


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_flat(mock_create_order, signal, base):
    mock_create_order.return_value = {"orderId": 1}

    position = Position(symbol=base.symbol, saldo=1000)
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)

    base.df, position = await when_flat(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status
    assert all(order.price >= entry_price for order in position.orders)
    assert base.df.at[base.df.index[-1], "position"] == signal


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_flat(mock_create_order, base):
    mock_create_order.return_value = {"orderId": 1}

    position = Position(symbol=base.symbol, saldo=1000)
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)

    base.df, position = await when_flat(
        signal=Signals.NULL,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 0 == len(position.orders)
    assert 1000 == position.saldo
    assert Signals.FLAT == position.status
    assert base.df.at[base.df.index[-1], "position"] == Signals.FLAT


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long(mock_create_order, signal, base):
    mock_create_order.return_value = {"orderId": 1}
    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.LONG
    entry_price = base.df.at[base.df.index[-1], "Close"]

    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    base.df, position = await when_long(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price <= entry_price for order in position.orders)


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.LONG
    entry_price = base.df.at[base.df.index[-1], "Close"]
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    base.df, position = await when_long(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price >= round(entry_price, 1) for order in position.orders)


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long(mock_create_order, base):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.LONG
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    position_status = position.status

    base.df, position = await when_long(
        signal=Signals.NULL,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price <= entry_price for order in position.orders)


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.SHORT
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    base.df, position = await when_short(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price <= entry_price for order in position.orders)


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short(mock_create_order, signal, base):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.SHORT
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    base.df, position = await when_short(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price >= entry_price for order in position.orders)


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short(mock_create_order, base):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.SHORT
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    position_status = position.status

    base.df, position = await when_short(
        signal=Signals.NULL,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price >= entry_price for order in position.orders)


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long_twenty(mock_create_order, signal, base):
    mock_create_order.return_value = {"orderId": 1}
    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.LONG_20
    entry_price = base.df.at[base.df.index[-1], "Close"]
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    base.df, position = await when_long_twenty(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price <= entry_price for order in position.orders)


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long_twenty(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.LONG_20
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    base.df, position = await when_long_twenty(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price >= entry_price for order in position.orders)


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long_twenty(mock_create_order, base):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.LONG_20
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    position_status = position.status

    base.df, position = await when_long_twenty(
        signal=Signals.NULL,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price <= entry_price for order in position.orders)


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short_eighty(
    mock_create_order, mock_cancel_order, signal, base
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.SHORT_80
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    base.df, position = await when_short_eighty(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price <= entry_price for order in position.orders)


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short_eighty(mock_create_order, signal, base):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.SHORT_80
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    df, position = await when_short_eighty(
        signal=signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price >= entry_price for order in position.orders)


@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short_eighty(mock_create_order, base):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}

    position = Position(symbol=base.symbol, saldo=1000)

    entry_signal = Signals.SHORT_80
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    position_status = position.status

    base.df, position = await when_short_eighty(
        signal=Signals.NULL,
        client=base.client,
        position=position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price >= entry_price for order in position.orders)
