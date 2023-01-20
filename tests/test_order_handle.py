from typing import Tuple
from unittest.mock import patch
from src.features import Signals
from src.orders import Position
from src.producers.producers import OrderUpdate
from src.workers.handle_signal import when_flat
from src.workers.handle_order import order_handle
import logging
import pandas

logger = logging.getLogger("TEST")


async def first_order_filled(base, entry_price: float) -> Position:

    price = entry_price
    quantity = base.position.orders[0].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=base.position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
    )

    return position


async def second_order_filled(base: pandas.DataFrame, position: Position) -> Position:
    price = position.orders[1].price
    quantity = position.orders[1].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

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

    return position


async def third_and_fourth_order_filled(base, position: Position) -> Position:
    price = position.orders[2].price
    quantity = position.orders[2].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None

    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
    )

    price = position.orders[3].price
    quantity = position.orders[3].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity
        + position.orders[1].quantity
        + position.orders[2].quantity
        + position.orders[3].quantity
    )

    return position


async def target_reached(base, position: Position):

    price = position.current_position.take_profit_order.price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None

    return position


async def start_long(base) -> Tuple[pandas.DataFrame, Position, float]:

    entry_signal = Signals.LONG
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=base.position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo

    assert all(order.price <= entry_price for order in position.orders)

    return base.df, position, entry_price


async def start_short(base) -> Tuple[pandas.DataFrame, Position, float]:

    entry_signal = Signals.SHORT
    entry_price = round(base.df.at[base.df.index[-1], "Close"], 1)
    base.df, position = await when_flat(
        signal=entry_signal,
        client=base.client,
        position=base.position,
        df=base.df,
        entry_price=entry_price,
    )

    assert 4 == len(position.orders)
    assert 1000 == position.saldo
    assert all(order.price >= entry_price for order in position.orders)

    return base.df, position, entry_price


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }

    base.df, base.position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }

    base.df, base.position, entry_price = await start_long(base=base)

    realized_quantity = base.position.orders[0].quantity / 2

    price = entry_price
    quantity = realized_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    base.position = await order_handle(
        client=base.client, position=base.position, order_update=order_update
    )

    for order in base.position.orders:
        logger.info("ORDER: %s", order)

    logger.info("tpo: %s", base.position.current_position.take_profit_order)

    assert base.position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert base.position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert base.position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert base.position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert base.position.current_position.take_profit_order is not None
    assert (
        base.position.current_position.take_profit_order.quantity == realized_quantity
    )


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially_twice(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    realized_quantity = position.orders[0].quantity / 2

    price = entry_price
    quantity = realized_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

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

    price = entry_price
    quantity = another_realized_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
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
async def test_long_two_orders_filled(mock_create_order, mock_cancel_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)

    position = await second_order_filled(base=base, position=position)


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_new(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    base.df, position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_NEW

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_expired(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    base.df, position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_EXPIRED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_canceled(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    base.df, position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_CANCELED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_two_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20350.4

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20299.6

    position = await target_reached(base=base, position=position)

    assert position.saldo == 1049.97


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20350.4

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20299.6

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20197.8

    price = position.current_position.take_profit_order.price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1099.43


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20350.4

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20299.6

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20197.8

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    price = position.current_position.take_profit_order.price
    quantity = partial_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20197.8
    assert position.current_position.take_profit_order.quantity == partial_quantity
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1049.72


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20350.4

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20299.6

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20197.8

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    price = position.current_position.take_profit_order.price
    quantity = partial_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20197.8
    assert position.current_position.take_profit_order.quantity == partial_quantity
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1049.72

    price = position.current_position.take_profit_order.price
    quantity = partial_quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1099.44


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_liquidation(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20350.4

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20299.6

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20197.8

    price = position.current_position.liquidation_price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 900.56


# ------------------------------ SHORT -------------------------------------#


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled_partially(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }

    base.df, position, entry_price = await start_short(base=base)

    realized_quantity = position.orders[0].quantity / 2

    price = entry_price
    quantity = realized_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

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
async def test_short_first_order_filled_partially_twice(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_short(base=base)

    realized_quantity = position.orders[0].quantity / 2

    price = entry_price
    quantity = realized_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

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

    price = entry_price
    quantity = another_realized_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
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
async def test_short_two_orders_filled(mock_create_order, mock_cancel_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)

    position = await second_order_filled(base=base, position=position)


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_new(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    base.df, position, entry_price = await start_short(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_NEW

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_expired(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    base.df, position, entry_price = await start_short(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_EXPIRED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_canceled(mock_create_order, base):
    mock_create_order.return_value = {
        "orderId": 1,
        "price": 21000,
        "status": base.client.ORDER_STATUS_NEW,
    }
    base.df, position, entry_price = await start_short(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_CANCELED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_two_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 18785

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18831.9

    position = await target_reached(base=base, position=position)

    assert position.saldo == 1050.22


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 18785

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18831.9

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18924.8

    price = position.current_position.take_profit_order.price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1100.14


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 18785

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18831.9

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18924.8

    whole_quantity = position.current_position.take_profit_order.quantity

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = position.current_position.take_profit_order.price
    quantity = partial_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 18924.8
    assert (
        position.current_position.take_profit_order.quantity == rest_of_order_quantity
    )
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1050.46


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 20000.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19900.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19800.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19700.8, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 18785

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18831.9

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18924.8

    whole_quantity = position.current_position.take_profit_order.quantity

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = position.current_position.take_profit_order.price
    quantity = partial_quantity
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    for order in position.orders:
        logger.info("Order status: %s", order.status)

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 18924.8
    assert (
        position.current_position.take_profit_order.quantity == rest_of_order_quantity
    )
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1050.46

    price = position.current_position.take_profit_order.price
    quantity = rest_of_order_quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1100.14


@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_liquidation(
    mock_create_order, mock_cancel_order, base
):
    mock_create_order.side_effect = [
        {"orderId": 1, "price": 19567.72, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 2, "price": 19665.54, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 3, "price": 19763.38, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 4, "price": 19861.22, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20800.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20748.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 5, "price": 20696.83, "status": base.client.ORDER_STATUS_NEW},
        {"orderId": 6, "price": 20644.83, "status": base.client.ORDER_STATUS_NEW},
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 18785.0

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18831.9

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 18924.8

    price = position.current_position.liquidation_price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(price=price, quantity=quantity, status=status)

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 899.86
