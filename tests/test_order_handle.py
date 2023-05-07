import logging
from unittest.mock import patch

import binance

from src.common.identifiers import State, OrderUpdate, Order
from tests.common import (
    start_long,
    first_order_filled,
    get_position_information,
    get_position_information_for_order_partially_filled,
    second_order_filled,
    get_cancel_order,
    target_reached,
    third_and_fourth_order_filled, get_orders_long, get_orders_short, start_short,
)

logger = logging.getLogger("TEST")


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled(
    mock_create_orders_long, mock_position_information, basic_rsi
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially(
    mock_create_orders_long, mock_position_information, basic_rsi
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = (
        get_position_information_for_order_partially_filled()
    )

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await basic_rsi.process_order()

    assert (
        basic_rsi.position.orders[0].status
        == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.quantity == realized_quantity
    assert basic_rsi.position.orders[0].realized_quantity == realized_quantity

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_filled_partially_twice(
    mock_create_orders_long, mock_position_information, basic_rsi
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = (
        get_position_information_for_order_partially_filled()
    )

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await basic_rsi.process_order()

    assert (
        basic_rsi.position.orders[0].status
        == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.quantity == realized_quantity
    assert basic_rsi.position.orders[0].realized_quantity == realized_quantity

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    another_realized_quantity = round(float(quantity / 4), 3)

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=another_realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity + another_realized_quantity,
    )

    await basic_rsi.process_order()

    assert (
        basic_rsi.position.orders[0].status
        == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == another_realized_quantity + realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert (
        basic_rsi.position.take_profit_order.quantity
        == realized_quantity + another_realized_quantity
    )
    assert (
        basic_rsi.position.orders[0].realized_quantity
        == realized_quantity + another_realized_quantity
    )

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_two_orders_filled(
    mock_create_orders_long,
    mock_cancel_order,
    mock_position_information,
    basic_rsi,
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()
    mock_cancel_order.return_value = get_cancel_order()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    assert basic_rsi.position.take_profit_order.price == 20800.0
    assert basic_rsi.position.liquidation_price == 19200

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20748.0
    assert basic_rsi.position.liquidation_price == 19152
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_new(mock_create_orders_long, basic_rsi):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = basic_rsi.client.ORDER_STATUS_NEW

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[1].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_expired(mock_create_orders_long, basic_rsi):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = basic_rsi.client.ORDER_STATUS_EXPIRED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == basic_rsi.client.ORDER_STATUS_EXPIRED
    assert basic_rsi.position.orders[1].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_create_order")
async def test_long_first_order_canceled(mock_create_orders_long, basic_rsi):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = basic_rsi.client.ORDER_STATUS_CANCELED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == basic_rsi.client.ORDER_STATUS_CANCELED
    assert basic_rsi.position.orders[1].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == basic_rsi.client.ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_two_orders_filled_then_target_reached(
    mock_create_orders_long,
    mock_cancel_order,
    mock_position_information,
    basic_rsi,
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()
    mock_cancel_order.return_value = get_cancel_order()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    assert basic_rsi.position.take_profit_order.price == 20800.0
    assert basic_rsi.position.liquidation_price == 19200

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20748.0
    assert basic_rsi.position.liquidation_price == 19152
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    await target_reached(base=basic_rsi)

    assert basic_rsi.balance == 1099.75
    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached(
    mock_create_orders_long,
    mock_cancel_order,
    mock_position_information,
    basic_rsi,
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()
    mock_cancel_order.return_value = get_cancel_order()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    assert basic_rsi.position.take_profit_order.price == 20800.0
    assert basic_rsi.position.liquidation_price == 19200

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20748.0
    assert basic_rsi.position.liquidation_price == 19152
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.liquidation_price == 19056

    await target_reached(base=basic_rsi)

    assert basic_rsi.position.orders == []
    assert basic_rsi.position.take_profit_order == Order(price=0, quantity=0)
    assert basic_rsi.balance == 1199.29
    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially(
    mock_create_orders_long,
    mock_cancel_order,
    mock_position_information,
    basic_rsi,
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()
    mock_cancel_order.return_value = get_cancel_order()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    assert basic_rsi.position.take_profit_order.price == 20800.0
    assert basic_rsi.position.liquidation_price == 19200

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20748.0
    assert basic_rsi.position.liquidation_price == 19152
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.liquidation_price == 19056

    partial_quantity = round(basic_rsi.position.take_profit_order.quantity / 2, 3)

    remaining_quantity = (
        basic_rsi.position.take_profit_order.quantity - partial_quantity
    )

    price = basic_rsi.position.take_profit_order.price
    status = basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=partial_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[1].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[2].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[3].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.take_profit_order is not None
    assert (
        basic_rsi.position.take_profit_order.status
        == basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.take_profit_order.quantity == remaining_quantity
    assert basic_rsi.position.take_profit_order.realized_quantity == partial_quantity
    assert basic_rsi.balance == 1100.04
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_target_reached_partially_then_filled_completely(
        mock_create_orders_long,
        mock_cancel_order,
        mock_position_information,
        basic_rsi,
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()
    mock_cancel_order.return_value = get_cancel_order()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    assert basic_rsi.position.take_profit_order.price == 20800.0
    assert basic_rsi.position.liquidation_price == 19200

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20748.0
    assert basic_rsi.position.liquidation_price == 19152
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.liquidation_price == 19056

    quantity = basic_rsi.position.take_profit_order.quantity

    partial_quantity = round(quantity / 2, 3)

    remaining_quantity = (
            quantity - partial_quantity
    )

    price = basic_rsi.position.take_profit_order.price
    status = basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=8,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[1].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[2].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[3].status == basic_rsi.client.ORDER_STATUS_FILLED
    assert basic_rsi.position.take_profit_order is not None
    assert (
            basic_rsi.position.take_profit_order.status
            == basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.take_profit_order.quantity == remaining_quantity
    assert basic_rsi.position.take_profit_order.realized_quantity == partial_quantity
    assert basic_rsi.balance == 1100.04
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    status = basic_rsi.client.ORDER_STATUS_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity + remaining_quantity,
        last_filled_quantity=remaining_quantity,
        order_id=8,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders == []
    assert basic_rsi.position.take_profit_order == Order(price=0, quantity=0)
    assert basic_rsi.balance == 1199.29
    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_long_all_orders_filled_then_liquidation(
        mock_create_orders_long,
        mock_cancel_order,
        mock_position_information,
        basic_rsi,
):
    mock_create_orders_long.side_effect = get_orders_long(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()
    mock_cancel_order.return_value = get_cancel_order()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    assert basic_rsi.position.take_profit_order.price == 20800.0
    assert basic_rsi.position.liquidation_price == 19200

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20748.0
    assert basic_rsi.position.liquidation_price == 19152
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.liquidation_price == 19056

    price = basic_rsi.position.liquidation_price
    quantity = basic_rsi.position.take_profit_order.quantity
    status = basic_rsi.client.ORDER_STATUS_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        order_id=6,
        order_type="LIQUIDATION",
        realized_quantity=quantity,
        last_filled_quantity=quantity,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders == []
    assert basic_rsi.position.take_profit_order == Order(price=0, quantity=0)
    assert basic_rsi.balance == 800.00
    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT


# ------------------------------ SHORT -------------------------------------#


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled(
    mock_create_orders_short, mock_position_information, basic_rsi
):
    mock_create_orders_short.side_effect = get_orders_short(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information()

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled_partially(
    mock_create_orders_short, mock_position_information, basic_rsi
):
    mock_create_orders_short.side_effect = get_orders_short(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information_for_order_partially_filled()

    await start_short(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await basic_rsi.process_order()

    assert (
            basic_rsi.position.orders[0].status
            == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.quantity == realized_quantity
    assert basic_rsi.position.orders[0].realized_quantity == realized_quantity

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_filled_partially_twice(
        mock_create_orders_short, mock_position_information, basic_rsi
):
    mock_create_orders_short.side_effect = get_orders_short(
        base=basic_rsi
    )
    mock_position_information.side_effect = get_position_information_for_order_partially_filled()

    await start_short(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = basic_rsi.client.ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await basic_rsi.process_order()

    assert (
            basic_rsi.position.orders[0].status
            == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.quantity == realized_quantity
    assert basic_rsi.position.orders[0].realized_quantity == realized_quantity

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    another_realized_quantity = round(float(quantity / 4), 3)

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=another_realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity + another_realized_quantity,
    )

    await basic_rsi.process_order()

    assert (
        basic_rsi.position.orders[0].status
        == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED
    )
    assert basic_rsi.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == another_realized_quantity + realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert (
        basic_rsi.position.take_profit_order.quantity
        == realized_quantity + another_realized_quantity
    )
    assert (
        basic_rsi.position.orders[0].realized_quantity
        == realized_quantity + another_realized_quantity
    )

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_two_orders_filled(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_new(mock_create_order, mock_get_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    base.df, current_position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_NEW,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_expired(mock_create_order, mock_get_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    base.df, current_position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_EXPIRED,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_EXPIRED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_first_order_canceled(mock_create_order, mock_get_order, base):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    base.df, current_position, entry_price = await start_short(base=base)

    order_update = OrderUpdate(
        price=entry_price,
        quantity=0,
        status=base.client.ORDER_STATUS_CANCELED,
        last_filled_quantity=0,
        realized_quantity=0,
        order_id=1,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_CANCELED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[2].status == base.client.ORDER_STATUS_NEW
    assert current_position.orders[3].status == base.client.ORDER_STATUS_NEW

    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_two_orders_filled_then_target_reached(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position, base.df, balance = await target_reached(
        base=base, current_position=current_position
    )

    assert balance == 1099.45

    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    price = current_position.take_profit_order.price
    quantity = current_position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=quantity,
        order_id=6,
        realized_quantity=quantity,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None
    assert round(balance, 2) == 1199.89
    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    whole_quantity = current_position.take_profit_order.quantity

    partial_quantity = round(current_position.take_profit_order.quantity / 2, 3)

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=whole_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.entry_price == 19344.0
    assert current_position.take_profit_order.quantity == rest_of_order_quantity
    assert current_position.take_profit_order.realized_quantity == partial_quantity
    assert balance == 1099.94
    assert base.df.iloc[-1]["position"] == Signals.SHORT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}
    mock_get_order.return_value = mock_get_order_return_value()
    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    whole_quantity = current_position.take_profit_order.quantity

    partial_quantity = round(current_position.take_profit_order.quantity / 2, 3)

    rest_of_order_quantity = whole_quantity - partial_quantity

    price = current_position.take_profit_order.price
    status = base.client.ORDER_STATUS_PARTIALLY_FILLED

    order_update = OrderUpdate(
        price=price,
        quantity=whole_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert base.df.iloc[-1]["position"] == Signals.SHORT

    for order in current_position.orders:
        logger.info("Order status: %s", order.status)

    assert current_position.orders[0].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[1].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[2].status == base.client.ORDER_STATUS_FILLED
    assert current_position.orders[3].status == base.client.ORDER_STATUS_FILLED
    assert current_position.take_profit_order is not None
    assert current_position.take_profit_order.entry_price == 19344.0
    assert current_position.take_profit_order.quantity == rest_of_order_quantity
    assert current_position.take_profit_order.realized_quantity == partial_quantity
    assert balance == 1099.94

    price = current_position.take_profit_order.entry_price
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

    current_position, base.df, balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=balance,
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None
    assert balance == 1199.88
    assert base.df.iloc[-1]["position"] == Signals.FLAT


@patch("binance.AsyncClient.futures_get_order")
@patch("binance.AsyncClient.futures_position_information")
@patch("binance.AsyncClient.futures_cancel_order")
@patch("binance.AsyncClient.futures_create_order")
async def test_short_all_orders_filled_then_liquidation(
    mock_create_order,
    mock_cancel_order,
    mock_position_information,
    mock_get_order,
    base,
):
    mock_create_order.side_effect = mock_create_order_side_effect_short()
    mock_get_order.return_value = mock_get_order_return_value()
    mock_cancel_order.return_value = {"status": base.client.ORDER_STATUS_CANCELED}

    mock_position_information.side_effect = [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20852", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20904", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20956", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]

    base.df, current_position, entry_price = await start_short(base=base)

    for order in current_position.orders:
        logger.info("Orderdddd: %s", order)

    current_position = await first_order_filled(
        current_position=current_position,
        entry_price=entry_price,
        balance=base.position.balance,
        client=base.client,
        df=base.df,
    )
    assert current_position.take_profit_order.price == 19200.0
    assert current_position.liquidation_price == 20800.0

    current_position = await second_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19248.0
    assert current_position.liquidation_price == 20852.0

    current_position = await third_and_fourth_order_filled(
        base=base, current_position=current_position
    )
    assert current_position.take_profit_order.price == 19344.0
    assert current_position.liquidation_price == 20956.0

    price = current_position.liquidation_price
    quantity = current_position.take_profit_order.quantity
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

    current_position, base.df, base.position.balance = await order_handle(
        client=base.client,
        current_position=current_position,
        order_update=order_update,
        df=base.df,
        balance=base.position.balance,
    )

    assert current_position.orders == []
    assert current_position.take_profit_order is None
    assert base.position.balance == 800.00
    assert base.df.iloc[-1]["position"] == Signals.FLAT
