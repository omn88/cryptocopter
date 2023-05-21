import logging
from unittest.mock import patch

from binance.enums import (
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_MARKET,
)

from src.common.identifiers import State, OrderUpdate, Order, Signal
from tests.common import (
    start_long,
    first_order_filled,
    second_order_filled,
    get_cancel_order,
    target_reached,
    third_and_fourth_order_filled,
    get_orders_long,
    get_orders_short,
    start_short,
    get_position_information_when_long,
    get_position_information_when_long_for_order_partially_filled,
    get_position_information_when_short,
    get_position_information_when_short_for_order_partially_filled,
    get_position_information_when_long_then_short,
    get_orders_long_then_short,
    generate_signal,
    assert_dca_short_opened,
    get_orders_long_then_market_then_short,
)

logger = logging.getLogger("TEST")


async def test_long_first_order_filled(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

    await start_long(base=basic_rsi)

    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_filled_partially(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long_for_order_partially_filled()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

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

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.quantity == realized_quantity
    assert basic_rsi.position.orders[0].realized_quantity == realized_quantity

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_filled_partially_twice(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long_for_order_partially_filled()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

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

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
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

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
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


async def test_long_two_orders_filled(
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()

    await start_long(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    assert basic_rsi.position.take_profit_order.price == 20800.0
    assert basic_rsi.position.liquidation_price == 19200

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 20748.0
    assert basic_rsi.position.liquidation_price == 19152
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_new(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_NEW

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_expired(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_EXPIRED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_EXPIRED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_canceled(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()

    await start_long(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_CANCELED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_CANCELED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("src.workers.handle_order.save_to_file")
async def test_long_two_orders_filled_then_target_reached(
    mock_save_to_file,
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

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


@patch("src.workers.handle_order.save_to_file")
async def test_long_all_orders_filled_then_target_reached(
    mock_save_to_file,
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

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


async def test_long_all_orders_filled_then_target_reached_partially(
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()

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
    status = ORDER_STATUS_PARTIALLY_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=partial_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.take_profit_order.quantity == remaining_quantity
    assert basic_rsi.position.take_profit_order.realized_quantity == partial_quantity
    assert basic_rsi.balance == 1100.04
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG


@patch("src.workers.handle_order.save_to_file")
async def test_long_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_save_to_file,
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

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

    remaining_quantity = quantity - partial_quantity

    price = basic_rsi.position.take_profit_order.price
    status = ORDER_STATUS_PARTIALLY_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=8,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.take_profit_order.price == 20644.0
    assert basic_rsi.position.take_profit_order.quantity == remaining_quantity
    assert basic_rsi.position.take_profit_order.realized_quantity == partial_quantity
    assert basic_rsi.balance == 1100.04
    assert basic_rsi.df.iloc[-1]["Position"] == State.LONG

    status = ORDER_STATUS_FILLED

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


@patch("src.workers.handle_order.save_to_file")
async def test_long_all_orders_filled_then_liquidation(
    mock_save_to_file,
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_long()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

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
    status = ORDER_STATUS_FILLED

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


@patch("src.workers.handle_order.save_to_file")
async def test_long_all_orders_filled_then_short_first_order_filled(
    mock_save_to_file,
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_long_then_short()
    )
    basic_rsi.client.futures_create_order.side_effect = (
        get_orders_long_then_market_then_short()
    )
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

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

    basic_rsi.signal_update = generate_signal(signal=Signal.SHORT, df=basic_rsi.df)

    await basic_rsi.process_signal()

    assert_dca_short_opened(
        position=basic_rsi.position,
        balance=basic_rsi.balance,
        state=basic_rsi.state,
        signal_update=basic_rsi.signal_update,
        df=basic_rsi.df,
    )

    basic_rsi.order_update = OrderUpdate(
        price=20414,
        quantity=basic_rsi.position_old.quantity,
        status=ORDER_STATUS_FILLED,
        realized_quantity=basic_rsi.position_old.quantity,
        last_filled_quantity=basic_rsi.position_old.quantity,
        order_id=9,
        order_type=ORDER_TYPE_MARKET,
    )

    await basic_rsi.process_order()

    logger.info(
        "Position: %s, \nposition old: %s", basic_rsi.position, basic_rsi.position_old
    )

    await first_order_filled(base=basic_rsi, order_id=10)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    # price = basic_rsi.position.liquidation_price
    # quantity = basic_rsi.position.take_profit_order.quantity
    # status = ORDER_STATUS_FILLED
    #
    # basic_rsi.order_update = OrderUpdate(
    #     price=price,
    #     quantity=quantity,
    #     status=status,
    #     order_id=6,
    #     order_type="LIQUIDATION",
    #     realized_quantity=quantity,
    #     last_filled_quantity=quantity,
    # )
    #
    # await basic_rsi.process_order()
    #
    # assert basic_rsi.position.orders == []
    # assert basic_rsi.position.take_profit_order == Order(price=0, quantity=0)
    # assert basic_rsi.balance == 800.00
    # assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT


# ------------------------------ SHORT -------------------------------------#


async def test_short_first_order_filled(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_filled_partially(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short_for_order_partially_filled()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()

    await start_short(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

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

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.position.entry_price == price
    assert basic_rsi.position.quantity == realized_quantity
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.quantity == realized_quantity
    assert basic_rsi.position.orders[0].realized_quantity == realized_quantity

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_filled_partially_twice(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short_for_order_partially_filled()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()

    await start_short(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

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

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
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

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_PARTIALLY_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
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


async def test_short_two_orders_filled(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    assert basic_rsi.position.take_profit_order.price == 19200.0
    assert basic_rsi.position.liquidation_price == 20800

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19248.0
    assert basic_rsi.position.liquidation_price == 20848.0
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_new(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    await start_short(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_NEW

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_expired(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    await start_short(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_EXPIRED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_EXPIRED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_canceled(basic_rsi):
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()

    await start_short(base=basic_rsi)

    price = basic_rsi.position.orders[0].price
    quantity = basic_rsi.position.orders[0].quantity
    status = ORDER_STATUS_CANCELED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_CANCELED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_NEW
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_NEW
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


@patch("src.workers.handle_order.save_to_file")
async def test_short_two_orders_filled_then_target_reached(
    mock_save_to_file, basic_rsi
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    assert basic_rsi.position.take_profit_order.price == 19200.0
    assert basic_rsi.position.liquidation_price == 20800

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19248.0
    assert basic_rsi.position.liquidation_price == 20848.0
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    await target_reached(base=basic_rsi)

    assert basic_rsi.balance == 1099.45
    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT


@patch("src.workers.handle_order.save_to_file")
async def test_short_all_orders_filled_then_target_reached(
    mock_save_to_file, basic_rsi
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    assert basic_rsi.position.take_profit_order.price == 19200.0
    assert basic_rsi.position.liquidation_price == 20800

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19248.0
    assert basic_rsi.position.liquidation_price == 20848.0
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19344.0
    assert basic_rsi.position.liquidation_price == 20944.0

    await target_reached(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT
    assert round(basic_rsi.balance, 2) == 1199.89


async def test_short_all_orders_filled_then_target_reached_partially(basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    assert basic_rsi.position.take_profit_order.price == 19200.0
    assert basic_rsi.position.liquidation_price == 20800

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19248.0
    assert basic_rsi.position.liquidation_price == 20848.0
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19344.0
    assert basic_rsi.position.liquidation_price == 20944.0

    quantity = basic_rsi.position.take_profit_order.quantity

    partial_quantity = round(quantity / 2, 3)

    remaining_quantity = quantity - partial_quantity

    price = basic_rsi.position.take_profit_order.price
    status = ORDER_STATUS_PARTIALLY_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.price == 19344.0
    assert basic_rsi.position.take_profit_order.quantity == remaining_quantity
    assert basic_rsi.position.take_profit_order.realized_quantity == partial_quantity
    assert basic_rsi.balance == 1099.94
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT


@patch("src.workers.handle_order.save_to_file")
async def test_short_all_orders_filled_then_target_reached_partially_then_filled_completely(
    mock_save_to_file,
    basic_rsi,
):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    assert basic_rsi.position.take_profit_order.price == 19200.0
    assert basic_rsi.position.liquidation_price == 20800

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19248.0
    assert basic_rsi.position.liquidation_price == 20848.0
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19344.0
    assert basic_rsi.position.liquidation_price == 20944.0

    quantity = basic_rsi.position.take_profit_order.quantity

    partial_quantity = round(quantity / 2, 3)

    remaining_quantity = quantity - partial_quantity

    price = basic_rsi.position.take_profit_order.price
    status = ORDER_STATUS_PARTIALLY_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders[0].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[1].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[2].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.orders[3].status == ORDER_STATUS_FILLED
    assert basic_rsi.position.take_profit_order is not None
    assert basic_rsi.position.take_profit_order.price == 19344.0
    assert basic_rsi.position.take_profit_order.quantity == remaining_quantity
    assert basic_rsi.position.take_profit_order.realized_quantity == partial_quantity
    assert basic_rsi.balance == 1099.94
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    price = basic_rsi.position.take_profit_order.price
    status = ORDER_STATUS_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=remaining_quantity,
        order_id=7,
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders == []
    assert basic_rsi.position.take_profit_order == Order(price=0, quantity=0)
    assert basic_rsi.balance == 1199.88
    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT


@patch("src.workers.handle_order.save_to_file")
async def test_short_all_orders_filled_then_liquidation(mock_save_to_file, basic_rsi):
    basic_rsi.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    basic_rsi.client.futures_create_order.side_effect = get_orders_short()
    basic_rsi.client.futures_cancel_order.return_value = get_cancel_order()
    mock_save_to_file.return_value = True

    await start_short(base=basic_rsi)
    await first_order_filled(base=basic_rsi)

    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    assert basic_rsi.position.take_profit_order.price == 19200.0
    assert basic_rsi.position.liquidation_price == 20800

    await second_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19248.0
    assert basic_rsi.position.liquidation_price == 20848.0
    assert basic_rsi.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=basic_rsi)
    assert basic_rsi.position.take_profit_order.price == 19344.0
    assert basic_rsi.position.liquidation_price == 20944.0

    price = basic_rsi.position.liquidation_price
    quantity = basic_rsi.position.take_profit_order.quantity
    status = ORDER_STATUS_FILLED

    basic_rsi.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=6,
        order_type="LIQUIDATION",
    )

    await basic_rsi.process_order()

    assert basic_rsi.position.orders == []
    assert basic_rsi.position.take_profit_order == Order(price=0, quantity=0)
    assert basic_rsi.balance == 800.00
    assert basic_rsi.df.iloc[-1]["Position"] == State.FLAT
