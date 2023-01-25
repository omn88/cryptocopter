from typing import Tuple
from unittest.mock import patch
from src.features import Signals
from src.orders import Position
from src.producers.producers import OrderUpdate
from src.workers.handle_signal import when_flat
from src.workers.handle_order import order_handle
import logging
import pandas
import binance

logger = logging.getLogger("TEST")


def mock_create_order_side_effect_long():
    return [
        {
            "orderId": "1",
            "price": "20000.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "2",
            "price": "19900.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "3",
            "price": "19800.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "4",
            "price": "19700.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "5",
            "price": "20800.0",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "6",
            "price": "20748.0",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "7",
            "price": "20696.0",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "8",
            "price": "20644.8",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
    ]


def mock_create_order_side_effect_short():
    return [
        {
            "orderId": "1",
            "price": "20000",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "2",
            "price": "20100",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "3",
            "price": "20200",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "4",
            "price": "20300",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "5",
            "price": "19200",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "6",
            "price": "20748.83",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "7",
            "price": "20696.83",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
        {
            "orderId": "8",
            "price": "20644.83",
            "status": binance.AsyncClient.ORDER_STATUS_NEW,
        },
    ]


async def first_order_filled(base, entry_price: float) -> Position:

    quantity = base.position.orders[0].quantity

    order_update = OrderUpdate(
        price=entry_price,
        quantity=quantity,
        status=base.client.ORDER_STATUS_FILLED,
        order_id=1,
        last_filled_quantity=quantity,
        realized_quantity=quantity,
    )

    position = await order_handle(
        client=base.client, position=base.position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.price == entry_price
    assert position.current_position.quantity == quantity
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == position.orders[0].quantity
    )
    assert position.orders[0].realized_quantity == quantity

    return position


async def second_order_filled(base: pandas.DataFrame, position: Position) -> Position:
    price = position.orders[1].price
    quantity = position.orders[1].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=2,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.price == round(
        (position.orders[0].price + position.orders[1].price) / 2, 1
    )
    assert position.current_position.quantity == round(
        (position.orders[0].realized_quantity + position.orders[1].realized_quantity), 3
    )
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == (
        position.orders[0].quantity + position.orders[1].quantity
    )

    return position


async def third_and_fourth_order_filled(base, position: Position) -> Position:
    price = position.orders[2].price
    quantity = position.orders[2].quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=3,
    )

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

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=4,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.price == round(
        (
            position.orders[0].price
            + position.orders[1].price
            + position.orders[2].price
            + position.orders[3].price
        )
        / 4,
        1,
    )
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

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=5,
    )

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


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled(
    mock_create_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]

    base.df, base.position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially(
    mock_create_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.015"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]

    base.df, base.position, entry_price = await start_long(base=base)

    realized_quantity = round(float(base.position.orders[0].quantity / 2), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=base.position.orders[0].quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

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


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially_twice(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.015"}],
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.023"}],
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    realized_quantity = round(float(position.orders[0].quantity / 2), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=base.position.orders[0].quantity,
        status=status,
        realized_quantity=realized_quantity,
        last_filled_quantity=realized_quantity,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity

    another_realized_quantity = round(float(position.orders[0].quantity / 4), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=position.orders[0].quantity,
        status=status,
        last_filled_quantity=another_realized_quantity,
        realized_quantity=(realized_quantity + another_realized_quantity),
        order_id=1,
    )

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


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_two_orders_filled(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20800.0
    assert position.current_position.liquidation_price == 19200

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20748.0
    assert position.current_position.liquidation_price == 19152


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_new(mock_create_order, mock_position_information, base):
    mock_create_order.side_effect = mock_create_order_side_effect_long()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]
    base.df, position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_NEW

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_expired(
    mock_create_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]
    base.df, position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_EXPIRED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_canceled(
    mock_create_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]
    base.df, position, entry_price = await start_long(base=base)

    price = entry_price
    quantity = position.orders[0].quantity
    status = base.client.ORDER_STATUS_CANCELED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_two_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
    ]

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20800.0
    assert position.current_position.liquidation_price == 19200

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20748.0
    assert position.current_position.liquidation_price == 19152

    position = await target_reached(base=base, position=position)

    assert position.saldo == 1049.48


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.094"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.126"}],
    ]

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20800.0
    assert position.current_position.liquidation_price == 19200

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20748.0
    assert position.current_position.liquidation_price == 19152

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20644.0
    assert position.current_position.liquidation_price == 19056

    position = await target_reached(base=base, position=position)

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1100.04


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.094"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.126"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.063"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.126"}],
    ]

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20800.0
    assert position.current_position.liquidation_price == 19200

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20748.0
    assert position.current_position.liquidation_price == 19152

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20644.0
    assert position.current_position.liquidation_price == 19056

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    price = position.current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=position.current_position.take_profit_order.quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 20644.0
    assert position.current_position.take_profit_order.quantity == partial_quantity
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1050.02


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.094"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.126"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.063"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0"}],
    ]

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20800.0
    assert position.current_position.liquidation_price == 19200

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20748.0
    assert position.current_position.liquidation_price == 19152

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20644.0
    assert position.current_position.liquidation_price == 19056

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    order_update = OrderUpdate(
        price=position.current_position.take_profit_order.price,
        quantity=position.current_position.quantity,
        status=base.client.ORDER_STATUS_PARTIALLY_FILLED,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    try:

        assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
        assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
        assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
        assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
        assert position.current_position.take_profit_order is not None
        assert position.current_position.take_profit_order.price == 20644.0
        assert position.current_position.take_profit_order.quantity == partial_quantity
        assert (
            position.current_position.take_profit_order.realized_quantity
            == partial_quantity
        )
        assert position.saldo == 1050.02
    except AssertionError as error:
        logger.info(error)
        raise error

    order_update = OrderUpdate(
        price=position.current_position.take_profit_order.price,
        quantity=position.current_position.quantity,
        status=base.client.ORDER_STATUS_FILLED,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=7,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1100.04


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_liquidation(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_long()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.094"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.126"}],
    ]

    base.df, position, entry_price = await start_long(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 20800.0
    assert position.current_position.liquidation_price == 19200

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20748.0
    assert position.current_position.liquidation_price == 19152

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 20644.0
    assert position.current_position.liquidation_price == 19056

    price = position.current_position.liquidation_price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        order_id=6,
        order_type="LIQUIDATION",
        realized_quantity=quantity,
        last_filled_quantity=quantity,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 899.96


# ------------------------------ SHORT -------------------------------------#


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled(
    mock_create_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled_partially(
    mock_create_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.015"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    realized_quantity = round(float(position.orders[0].quantity / 2), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=position.orders[0].quantity,
        status=status,
        realized_quantity=realized_quantity,
        last_filled_quantity=realized_quantity,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled_partially_twice(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.015"}],
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.023"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    realized_quantity = round(float(position.orders[0].quantity / 2), 3)

    price = entry_price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=position.orders[0].quantity,
        status=status,
        realized_quantity=realized_quantity,
        last_filled_quantity=realized_quantity,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.quantity == realized_quantity

    another_realized_quantity = round(float(position.orders[0].quantity / 4), 3)

    price = entry_price

    order_update = OrderUpdate(
        price=price,
        quantity=position.orders[0].quantity,
        status=base.client.ORDER_STATUS_PARTIALLY_FILLED,
        realized_quantity=realized_quantity + another_realized_quantity,
        last_filled_quantity=another_realized_quantity,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_PARTIALLY_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW
    assert position.current_position.take_profit_order is not None
    assert (
        position.current_position.take_profit_order.quantity
        == realized_quantity + another_realized_quantity
    )


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_two_orders_filled(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)

    position = await second_order_filled(base=base, position=position)


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_new(mock_create_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()

    base.df, position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_NEW,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_expired(mock_create_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()

    base.df, position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_EXPIRED,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_canceled(mock_create_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()

    base.df, position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_CANCELED,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert position.orders[3].status == base.client.ORDER_STATUS_NEW


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_two_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 19200.0
    assert position.current_position.liquidation_price == 20800.0

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19248.0
    assert position.current_position.liquidation_price == 20852.0

    position = await target_reached(base=base, position=position)

    assert position.saldo == 1049.72


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 19200.0
    assert position.current_position.liquidation_price == 20800.0

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19248.0
    assert position.current_position.liquidation_price == 20852.0

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19344.0
    assert position.current_position.liquidation_price == 20956.0

    price = position.current_position.take_profit_order.price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=quantity,
        order_id=6,
        realized_quantity=quantity,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1099.94


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 19200.0
    assert position.current_position.liquidation_price == 20800.0

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19248.0
    assert position.current_position.liquidation_price == 20852.0

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19344.0
    assert position.current_position.liquidation_price == 20956.0

    whole_quantity = position.current_position.take_profit_order.quantity

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = position.current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=whole_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert position.current_position.take_profit_order is not None
    assert position.current_position.take_profit_order.price == 19344.0
    assert (
        position.current_position.take_profit_order.quantity == rest_of_order_quantity
    )
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1049.97


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 19200.0
    assert position.current_position.liquidation_price == 20800.0

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19248.0
    assert position.current_position.liquidation_price == 20852.0

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19344.0
    assert position.current_position.liquidation_price == 20956.0

    whole_quantity = position.current_position.take_profit_order.quantity

    partial_quantity = round(
        position.current_position.take_profit_order.quantity / 2, 3
    )

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = position.current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=whole_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

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
    assert position.current_position.take_profit_order.price == 19344.0
    assert (
        position.current_position.take_profit_order.quantity == rest_of_order_quantity
    )
    assert (
        position.current_position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert position.saldo == 1049.97

    price = position.current_position.take_profit_order.price
    quantity = rest_of_order_quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=whole_quantity,
        last_filled_quantity=quantity,
        order_id=7,
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 1099.94


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_liquidation(
    mock_create_order, mock_cancel_order, mock_position_information, base
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.093"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.124"}],
    ]

    base.df, position, entry_price = await start_short(base=base)

    position = await first_order_filled(base=base, entry_price=entry_price)
    assert position.current_position.take_profit_order.price == 19200.0
    assert position.current_position.liquidation_price == 20800.0

    position = await second_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19248.0
    assert position.current_position.liquidation_price == 20852.0

    position = await third_and_fourth_order_filled(base=base, position=position)
    assert position.current_position.take_profit_order.price == 19344.0
    assert position.current_position.liquidation_price == 20956.0

    price = position.current_position.liquidation_price
    quantity = position.current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=6,
        order_type="LIQUIDATION",
    )

    position = await order_handle(
        client=base.client, position=position, order_update=order_update
    )

    assert position.orders == []
    assert position.current_position.take_profit_order is None
    assert position.saldo == 900.06
