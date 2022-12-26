from unittest.mock import patch
from src.features import Signals
from src.orders import Position
from src.workers.signal import when_flat
from src.workers.order import order_handle
import logging

logger = logging.getLogger("TEST")


@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_filled(mock_create_order, base):
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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_filled_partially(mock_create_order, base):
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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    realized_quantity = position.orders[0].quantity / 2

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_PARTIALLY_FILLED,
            "p": entry_price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_filled_partially_twice(
    mock_create_order, mock_cancel_order, base
):

    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    realized_quantity = position.orders[0].quantity / 2

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_PARTIALLY_FILLED,
            "p": entry_price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity

    another_realized_quantity = position.orders[0].quantity / 4

    another_order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_PARTIALLY_FILLED,
            "p": entry_price,
            "q": another_realized_quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=another_order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == (
        realized_quantity + another_realized_quantity
    )


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_two_orders_filled(mock_create_order, mock_cancel_order, base):
    mock_create_order.return_value = {"orderId": 1, "price": 21000}
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    realized_quantity = position.orders[0].quantity

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity

    realized_quantity = position.orders[1].quantity

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": realized_quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity + position.orders[1].quantity
    )


@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_new(mock_create_order, base):
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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_NEW,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_expired(mock_create_order, base):
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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_EXPIRED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_first_order_canceled(mock_create_order, base):
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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_CANCELED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_two_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8},
        {"orderId": 2, "price": 19900.8},
        {"orderId": 3, "price": 19800.8},
        {"orderId": 4, "price": 19700.8},
        {"orderId": 5, "price": 20800.83},
        {"orderId": 6, "price": 20748.83},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20800.83
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20748.83
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity + position.orders[1].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.current_position.take_profit_order.price,
            "q": position.current_position.take_profit_order.quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1049.48


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_all_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8},
        {"orderId": 2, "price": 19900.8},
        {"orderId": 3, "price": 19800.8},
        {"orderId": 4, "price": 19700.8},
        {"orderId": 5, "price": 20800.83},
        {"orderId": 6, "price": 20748.83},
        {"orderId": 5, "price": 20696.83},
        {"orderId": 6, "price": 20644.83},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20800.83
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20748.83
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity + position.orders[1].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[2].price,
            "q": position.orders[2].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20695.73
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[3].price,
            "q": position.orders[3].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20643.18
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
        + position.orders[3].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.current_position.take_profit_order.price,
            "q": position.current_position.take_profit_order.quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1100.04


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_all_orders_filled_then_target_reached_partially(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8},
        {"orderId": 2, "price": 19900.8},
        {"orderId": 3, "price": 19800.8},
        {"orderId": 4, "price": 19700.8},
        {"orderId": 5, "price": 20800.83},
        {"orderId": 6, "price": 20748.83},
        {"orderId": 5, "price": 20696.83},
        {"orderId": 6, "price": 20644.83},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20800.83
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20748.83
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity + position.orders[1].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[2].price,
            "q": position.orders[2].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20695.73
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[3].price,
            "q": position.orders[3].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20643.18
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
        + position.orders[3].quantity
    )

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_PARTIALLY_FILLED,
            "p": position.current_position.take_profit_order.price,
            "q": partial_quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20643.18
    assert position.current_position.take_profit_order.quantity == partial_quantity
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1050.02


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8},
        {"orderId": 2, "price": 19900.8},
        {"orderId": 3, "price": 19800.8},
        {"orderId": 4, "price": 19700.8},
        {"orderId": 5, "price": 20800.83},
        {"orderId": 6, "price": 20748.83},
        {"orderId": 5, "price": 20696.83},
        {"orderId": 6, "price": 20644.83},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

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

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": entry_price,
            "q": position.orders[0].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20800.83
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[1].price,
            "q": position.orders[1].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20748.83
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity + position.orders[1].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[2].price,
            "q": position.orders[2].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20695.73
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.orders[3].price,
            "q": position.orders[3].quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20643.18
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
        + position.orders[3].quantity
    )

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.current_position.take_profit_order.price,
            "q": partial_quantity,
        }
    }

    logger.info("Order update: %s", order_update)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20643.18
    assert position.current_position.take_profit_order.quantity == partial_quantity
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1050.02

    order_update = {
        "o": {
            "X": base.client.ORDER_STATUS_FILLED,
            "p": position.current_position.take_profit_order.price,
            "q": partial_quantity,
        }
    }

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1100.04
