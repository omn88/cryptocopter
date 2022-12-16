import pytest
from unittest.mock import patch
import binance
import asyncio

from tests.data.sample_dataframes import dataframe_gen
from src.producers.producers import determine_start_position
from src.features import Signals
from src.orders import Position
from src.workers.signal import when_flat
from src.workers.order import order_handle


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_filled(mock_create_order):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = Signals.NULL
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

    assert 4 == len(position.orders)
    assert 900 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=client, position=position, order_update=order_update
    )

    assert position.orders[0].status == client.ORDER_STATUS_FILLED
    assert position.orders[1].status == client.ORDER_STATUS_NEW
    assert position.orders[2].status == client.ORDER_STATUS_NEW
    assert position.orders[3].status == client.ORDER_STATUS_NEW

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_filled_partially(mock_create_order):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    desired_signal = Signals.NULL
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

    assert 4 == len(position.orders)
    assert 900 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    realized_quantity = position.orders[0].quantity / 2

    order_update = {
        "o": {
            "X": client.ORDER_STATUS_PARTIALLY_FILLED,
            "p": entry_price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=client, position=position, order_update=order_update
    )

    assert position.orders[0].status == client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == client.ORDER_STATUS_NEW
    assert position.orders[2].status == client.ORDER_STATUS_NEW
    assert position.orders[3].status == client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_filled_partially_twice(mock_create_order, mock_cancel_order):
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": client.ORDER_STATUS_CANCELED}

    desired_signal = Signals.NULL
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

    assert 4 == len(position.orders)
    assert 900 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    realized_quantity = position.orders[0].quantity / 2

    order_update = {
        "o": {
            "X": client.ORDER_STATUS_PARTIALLY_FILLED,
            "p": entry_price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=client, position=position, order_update=order_update
    )

    assert position.orders[0].status == client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == client.ORDER_STATUS_NEW
    assert position.orders[2].status == client.ORDER_STATUS_NEW
    assert position.orders[3].status == client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity

    another_realized_quantity = position.orders[0].quantity / 4

    another_order_update = {
        "o": {
            "X": client.ORDER_STATUS_PARTIALLY_FILLED,
            "p": entry_price,
            "q": another_realized_quantity,
        }
    }

    position = await order_handle(
        client=client, position=position, order_update=another_order_update
    )

    assert position.orders[0].status == client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == client.ORDER_STATUS_NEW
    assert position.orders[2].status == client.ORDER_STATUS_NEW
    assert position.orders[3].status == client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == (
        realized_quantity + another_realized_quantity
    )

    await client.close_connection()


@pytest.mark.asyncio
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_two_orders_filled(mock_create_order, mock_cancel_order):
    client = binance.AsyncClient()
    queue = asyncio.Queue()

    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": client.ORDER_STATUS_CANCELED}

    desired_signal = Signals.NULL
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

    assert 4 == len(position.orders)
    assert 900 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    realized_quantity = position.orders[0].quantity

    order_update = {
        "o": {
            "X": client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=client, position=position, order_update=order_update
    )

    assert position.orders[0].status == client.ORDER_STATUS_FILLED
    assert position.orders[1].status == client.ORDER_STATUS_NEW
    assert position.orders[2].status == client.ORDER_STATUS_NEW
    assert position.orders[3].status == client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity

    realized_quantity = position.orders[1].quantity

    order_update = {
        "o": {
            "X": client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=client, position=position, order_update=order_update
    )

    assert position.orders[0].status == client.ORDER_STATUS_FILLED
    assert position.orders[1].status == client.ORDER_STATUS_FILLED
    assert position.orders[2].status == client.ORDER_STATUS_NEW
    assert position.orders[3].status == client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity + position.orders[1].quantity
    )

    await client.close_connection()
