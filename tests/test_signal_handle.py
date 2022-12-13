from unittest.mock import patch

import binance
import pytest
import asyncio
from src import features
from tests.data.sample_dataframes import dataframe_gen
from src.orders import Position
from src.producers.producers import determine_start_position, Event
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
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_flat(mock_create_order, signal):
    mock_create_order.return_value = {"orderId": 1}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    event = await queue.get()
    assert isinstance(event, Event)
    assert event.content["last_signal"] == desired_signal
    assert queue.qsize() == 0

    entry_price = df.at[df.index[-1], "Close"]

    df, position = await when_flat(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price <= entry_price for order in position.orders)
    assert df.at[df.index[-1], "position"] == signal

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_flat(mock_create_order, signal):
    mock_create_order.return_value = {"orderId": 1}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    event = await queue.get()
    assert isinstance(event, Event)
    assert event.content["last_signal"] == desired_signal
    assert queue.qsize() == 0

    entry_price = round(df.at[df.index[-1], "Close"], 1)

    df, position = await when_flat(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price >= entry_price for order in position.orders)
    assert df.at[df.index[-1], "position"] == signal

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_flat(mock_create_order):
    mock_create_order.return_value = {"orderId": 1}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    event = await queue.get()
    assert isinstance(event, Event)
    assert event.content["last_signal"] == desired_signal
    assert queue.qsize() == 0

    entry_price = round(df.at[df.index[-1], "Close"], 1)

    df, position = await when_flat(
        signal=desired_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    assert 0 == len(position.orders)
    assert 1000 == position.saldo
    assert Signals.FLAT == position.status
    await client.close_connection()
    assert df.at[df.index[-1], "position"] == Signals.FLAT


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long(mock_create_order, signal):
    mock_create_order.return_value = {"orderId": 1}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.LONG
    entry_price = df.at[df.index[-1], "Close"]
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_long(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price <= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long(
    mock_create_order, mock_cancel_order, signal
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.LONG
    entry_price = df.at[df.index[-1], "Close"]
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_long(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price >= round(entry_price, 1) for order in position.orders)

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long(mock_create_order):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.LONG
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    position_status = position.status

    df, position = await when_long(
        signal=Signals.NULL,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price <= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short(
    mock_create_order, mock_cancel_order, signal
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.SHORT
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_short(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price <= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short(mock_create_order, signal):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.SHORT
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_short(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price >= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short(mock_create_order):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.SHORT
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    position_status = position.status

    df, position = await when_short(
        signal=Signals.NULL,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price >= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_long_twenty(mock_create_order, signal):
    mock_create_order.return_value = {"orderId": 1}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.LONG_20
    entry_price = df.at[df.index[-1], "Close"]
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_long_twenty(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price <= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_long_twenty(
    mock_create_order, mock_cancel_order, signal
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.LONG_20
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_long_twenty(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price >= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_long_twenty(mock_create_order):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.LONG_20
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    position_status = position.status

    df, position = await when_long_twenty(
        signal=Signals.NULL,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price <= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.LONG, Signals.LONG_20])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_long_when_short_eighty(
    mock_create_order, mock_cancel_order, signal
):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": "Cancelled"}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.SHORT_80
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_short_eighty(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert signal == position.status

    assert all(order.price <= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.parametrize("signal", [Signals.SHORT, Signals.SHORT_80])
@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_short_when_short_eighty(mock_create_order, signal):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL

    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.SHORT_80
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    df, position = await when_short_eighty(
        signal=signal, client=client, position=position, df=df, entry_price=entry_price
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert entry_signal == position.status

    assert all(order.price >= entry_price for order in position.orders)

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_signal_handle_null_when_short_eighty(mock_create_order):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = features.Signals.NULL
    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT

    symbol = "BTCUSDT"
    position = Position(symbol=symbol, saldo=1000)
    df = await determine_start_position(df=df, queue=queue)

    entry_signal = Signals.SHORT_80
    entry_price = round(df.at[df.index[-1], "Close"], 1)
    df, position = await when_flat(
        signal=entry_signal,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    event = await queue.get()
    assert event.content["last_signal"] == desired_signal

    position_status = position.status

    df, position = await when_short_eighty(
        signal=Signals.NULL,
        client=client,
        position=position,
        df=df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 900 == position.saldo
    assert position_status == position.status

    assert all(order.price >= entry_price for order in position.orders)

    await client.close_connection()
