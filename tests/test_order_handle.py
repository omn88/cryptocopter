from unittest.mock import patch
from src.features import Signals
from src.orders import Position
from src.workers.signal import when_flat
from src.workers.order import order_handle


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
    assert 900 == position.saldo

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
    assert 900 == position.saldo

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
    assert 900 == position.saldo

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
    assert 900 == position.saldo

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
    assert 900 == position.saldo

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
    assert 900 == position.saldo

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
    assert 900 == position.saldo

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
