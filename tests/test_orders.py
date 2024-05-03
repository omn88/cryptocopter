import logging
from unittest.mock import patch

from binance.enums import (
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_CANCELED,
    ORDER_TYPE_MARKET,
    ORDER_TYPE_LIMIT,
)

from src.common.identifiers.futures import State, OrderUpdate, Order, Signal
from src.strategies.base import BaseStrategy
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
    validation_orders,
)

logger = logging.getLogger("TEST")


async def test_long_first_order_filled(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )

    base.strategy.client.futures_create_order.side_effect = get_orders_long()

    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)

    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_filled_partially(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long_for_order_partially_filled()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.entry_price == price
    assert base.strategy.position_handler.position.quantity == realized_quantity
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == realized_quantity
    )
    assert (
        base.strategy.position_handler.position.orders[0].realized_quantity
        == realized_quantity
    )

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_filled_partially_twice(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long_for_order_partially_filled()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()

    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.entry_price == price
    assert base.strategy.position_handler.position.quantity == realized_quantity
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == realized_quantity
    )
    assert (
        base.strategy.position_handler.position.orders[0].realized_quantity
        == realized_quantity
    )

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    another_realized_quantity = round(float(quantity / 4), 3)

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=another_realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity + another_realized_quantity,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.entry_price == price
    assert (
        base.strategy.position_handler.position.quantity
        == another_realized_quantity + realized_quantity
    )
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == realized_quantity + another_realized_quantity
    )
    assert (
        base.strategy.position_handler.position.orders[0].realized_quantity
        == realized_quantity + another_realized_quantity
    )

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_two_orders_filled(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    assert base.strategy.position_handler.position.take_profit_order.price == 20800.0
    assert base.strategy.position_handler.position.liquidation_price == 19200

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20748.0
    assert base.strategy.position_handler.position.liquidation_price == 19152
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_new(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_NEW

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await base.strategy.process_order()

    assert base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_expired(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_EXPIRED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_EXPIRED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_first_order_canceled(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_CANCELED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_CANCELED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_two_orders_filled_then_target_reached(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    logger.info(
        "Start Balance: %s, type: %s",
        base.strategy.balance,
        type(base.strategy.balance),
    )

    await start_long(base=base.strategy)
    await first_order_filled(base=base.strategy)

    logger.info(
        "First order filled Balance: %s, type: %s",
        base.strategy.balance,
        type(base.strategy.balance),
    )

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    assert base.strategy.position_handler.position.take_profit_order.price == 20800.0
    assert base.strategy.position_handler.position.liquidation_price == 19200

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20748.0
    assert base.strategy.position_handler.position.liquidation_price == 19152
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    logger.info(
        "Second order Balance: %s, type: %s",
        base.strategy.balance,
        type(base.strategy.balance),
    )

    await target_reached(base=base.strategy)
    logger.info(
        "Balance: %s, type: %s", base.strategy.balance, type(base.strategy.balance)
    )
    assert base.strategy.balance == 1099.75
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT


async def test_long_all_orders_filled_then_target_reached(
    base,
):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    assert base.strategy.position_handler.position.take_profit_order.price == 20800.0
    assert base.strategy.position_handler.position.liquidation_price == 19200

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20748.0
    assert base.strategy.position_handler.position.liquidation_price == 19152
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20644.0
    assert base.strategy.position_handler.position.liquidation_price == 19056

    await target_reached(base=base.strategy)

    assert base.strategy.position_handler.position.orders == []
    assert base.strategy.position_handler.position.take_profit_order == Order(
        price=0, quantity=0
    )
    assert base.strategy.balance == 1199.29
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT


async def test_long_all_orders_filled_then_target_reached_partially(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    assert base.strategy.position_handler.position.take_profit_order.price == 20800.0
    assert base.strategy.position_handler.position.liquidation_price == 19200

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20748.0
    assert base.strategy.position_handler.position.liquidation_price == 19152
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20644.0
    assert base.strategy.position_handler.position.liquidation_price == 19056

    partial_quantity = round(
        base.strategy.position_handler.position.take_profit_order.quantity / 2, 3
    )

    remaining_quantity = (
        base.strategy.position_handler.position.take_profit_order.quantity
        - partial_quantity
    )

    price = base.strategy.position_handler.position.take_profit_order.price
    status = ORDER_STATUS_PARTIALLY_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=partial_quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_FILLED
    )
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.take_profit_order.price == 20644.0
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == remaining_quantity
    )
    assert (
        base.strategy.position_handler.position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert base.strategy.balance == 1100.04
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG


async def test_long_all_orders_filled_then_target_reached_partially_then_filled_completely(
    base,
):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    assert base.strategy.position_handler.position.take_profit_order.price == 20800.0
    assert base.strategy.position_handler.position.liquidation_price == 19200

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20748.0
    assert base.strategy.position_handler.position.liquidation_price == 19152
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20644.0
    assert base.strategy.position_handler.position.liquidation_price == 19056

    quantity = base.strategy.position_handler.position.take_profit_order.quantity

    partial_quantity = round(quantity / 2, 3)

    remaining_quantity = quantity - partial_quantity

    price = base.strategy.position_handler.position.take_profit_order.price
    status = ORDER_STATUS_PARTIALLY_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=8,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_FILLED
    )
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.take_profit_order.price == 20644.0
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == remaining_quantity
    )
    assert (
        base.strategy.position_handler.position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert base.strategy.balance == 1100.04
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    status = ORDER_STATUS_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity + remaining_quantity,
        last_filled_quantity=remaining_quantity,
        order_id=8,
    )

    await base.strategy.process_order()

    assert base.strategy.position_handler.position.orders == []
    assert base.strategy.position_handler.position.take_profit_order == Order(
        price=0, quantity=0
    )
    assert base.strategy.balance == 1199.29
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT


async def test_long_all_orders_filled_then_liquidation(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_long()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    assert base.strategy.position_handler.position.take_profit_order.price == 20800.0
    assert base.strategy.position_handler.position.liquidation_price == 19200

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20748.0
    assert base.strategy.position_handler.position.liquidation_price == 19152
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20644.0
    assert base.strategy.position_handler.position.liquidation_price == 19056

    price = base.strategy.position_handler.position.liquidation_price
    quantity = base.strategy.position_handler.position.take_profit_order.quantity
    status = ORDER_STATUS_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        order_id=6,
        order_type="LIQUIDATION",
        realized_quantity=quantity,
        last_filled_quantity=quantity,
    )

    await base.strategy.process_order()

    assert base.strategy.position_handler.position.orders == []
    assert base.strategy.position_handler.position.take_profit_order == Order(
        price=0, quantity=0
    )
    assert base.strategy.balance == 800.00
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT


async def test_long_all_orders_filled_then_short_first_order_filled(base):
    assert isinstance(base.strategy, BaseStrategy)

    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_long_then_short()
    )
    base.strategy.client.futures_create_order.side_effect = (
        get_orders_long_then_market_then_short()
    )
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_long(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    assert base.strategy.position_handler.position.take_profit_order.price == 20800.0
    assert base.strategy.position_handler.position.liquidation_price == 19200

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20748.0
    assert base.strategy.position_handler.position.liquidation_price == 19152
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.LONG

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 20644.0
    assert base.strategy.position_handler.position.liquidation_price == 19056

    base.strategy.signal_update = generate_signal(
        signal=Signal.SHORT, df=base.strategy.df_handler.df
    )

    await base.strategy.process_signal()

    assert_dca_short_opened(
        position=base.strategy.position_handler.position,
        balance=base.strategy.balance,
        state=base.strategy.state,
        signal_update=base.strategy.signal_update,
        df=base.strategy.df_handler.df,
        number_of_orders=base.strategy.position_handler.config.number_of_orders,
    )

    base.strategy.order_update = OrderUpdate(
        price=20414,
        quantity=base.strategy.position_handler.closed_positions[-1].quantity,
        status=ORDER_STATUS_FILLED,
        realized_quantity=base.strategy.position_handler.closed_positions[-1].quantity,
        last_filled_quantity=base.strategy.position_handler.closed_positions[
            -1
        ].quantity,
        order_id=9,
        order_type=ORDER_TYPE_MARKET,
    )

    await base.strategy.process_order()

    await first_order_filled(base=base.strategy, order_id=10)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


# ------------------------------ SHORT -------------------------------------#


async def test_short_first_order_filled(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_filled_partially(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short_for_order_partially_filled()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.entry_price == price
    assert base.strategy.position_handler.position.quantity == realized_quantity
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == realized_quantity
    )
    assert (
        base.strategy.position_handler.position.orders[0].realized_quantity
        == realized_quantity
    )

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_filled_partially_twice(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short_for_order_partially_filled()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_PARTIALLY_FILLED

    realized_quantity = round(float(quantity / 2), 3)

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.entry_price == price
    assert base.strategy.position_handler.position.quantity == realized_quantity
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == realized_quantity
    )
    assert (
        base.strategy.position_handler.position.orders[0].realized_quantity
        == realized_quantity
    )

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    another_realized_quantity = round(float(quantity / 4), 3)

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        last_filled_quantity=another_realized_quantity,
        order_id=1,
        realized_quantity=realized_quantity + another_realized_quantity,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_PARTIALLY_FILLED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.entry_price == price
    assert (
        base.strategy.position_handler.position.quantity
        == another_realized_quantity + realized_quantity
    )
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == realized_quantity + another_realized_quantity
    )
    assert (
        base.strategy.position_handler.position.orders[0].realized_quantity
        == realized_quantity + another_realized_quantity
    )

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_two_orders_filled(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    assert base.strategy.position_handler.position.take_profit_order.price == 19200.0
    assert base.strategy.position_handler.position.liquidation_price == 20800

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19248.0
    assert base.strategy.position_handler.position.liquidation_price == 20848.0
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_new(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_get_order.side_effect = validation_orders()
    await start_short(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_NEW

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await base.strategy.process_order()

    assert base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_expired(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_get_order.side_effect = validation_orders()
    await start_short(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_EXPIRED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_EXPIRED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_first_order_canceled(base):
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)

    price = base.strategy.position_handler.position.orders[0].price
    quantity = base.strategy.position_handler.position.orders[0].quantity
    status = ORDER_STATUS_CANCELED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=0,
        last_filled_quantity=0,
        order_id=1,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status
        == ORDER_STATUS_CANCELED
    )
    assert base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_NEW
    assert base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_NEW
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_two_orders_filled_then_target_reached(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    assert base.strategy.position_handler.position.take_profit_order.price == 19200.0
    assert base.strategy.position_handler.position.liquidation_price == 20800

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19248.0
    assert base.strategy.position_handler.position.liquidation_price == 20848.0
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    await target_reached(base=base.strategy)

    assert base.strategy.balance == 1099.45
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT


async def test_short_all_orders_filled_then_target_reached(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    assert base.strategy.position_handler.position.take_profit_order.price == 19200.0
    assert base.strategy.position_handler.position.liquidation_price == 20800

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19248.0
    assert base.strategy.position_handler.position.liquidation_price == 20848.0
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19344.0
    assert base.strategy.position_handler.position.liquidation_price == 20944.0

    await target_reached(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT
    assert round(base.strategy.balance, 2) == 1199.89


async def test_short_all_orders_filled_then_target_reached_partially(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    assert base.strategy.position_handler.position.take_profit_order.price == 19200.0
    assert base.strategy.position_handler.position.liquidation_price == 20800

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19248.0
    assert base.strategy.position_handler.position.liquidation_price == 20848.0
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19344.0
    assert base.strategy.position_handler.position.liquidation_price == 20944.0

    quantity = base.strategy.position_handler.position.take_profit_order.quantity

    partial_quantity = round(quantity / 2, 3)

    remaining_quantity = quantity - partial_quantity

    price = base.strategy.position_handler.position.take_profit_order.price
    status = ORDER_STATUS_PARTIALLY_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_FILLED
    )
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert base.strategy.position_handler.position.take_profit_order.price == 19344.0
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == remaining_quantity
    )
    assert (
        base.strategy.position_handler.position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert base.strategy.balance == 1099.94
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT


async def test_short_all_orders_filled_then_target_reached_partially_then_filled_completely(
    base,
):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    assert base.strategy.position_handler.position.take_profit_order.price == 19200.0
    assert base.strategy.position_handler.position.liquidation_price == 20800

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19248.0
    assert base.strategy.position_handler.position.liquidation_price == 20848.0
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19344.0
    assert base.strategy.position_handler.position.liquidation_price == 20944.0

    quantity = base.strategy.position_handler.position.take_profit_order.quantity

    partial_quantity = round(quantity / 2, 3)

    remaining_quantity = quantity - partial_quantity

    price = base.strategy.position_handler.position.take_profit_order.price
    status = ORDER_STATUS_PARTIALLY_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=partial_quantity,
        last_filled_quantity=partial_quantity,
        order_id=6,
    )

    await base.strategy.process_order()

    assert (
        base.strategy.position_handler.position.orders[0].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[1].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[2].status == ORDER_STATUS_FILLED
    )
    assert (
        base.strategy.position_handler.position.orders[3].status == ORDER_STATUS_FILLED
    )
    assert base.strategy.position_handler.position.take_profit_order is not None
    assert base.strategy.position_handler.position.take_profit_order.price == 19344.0
    assert (
        base.strategy.position_handler.position.take_profit_order.quantity
        == remaining_quantity
    )
    assert (
        base.strategy.position_handler.position.take_profit_order.realized_quantity
        == partial_quantity
    )
    assert base.strategy.balance == 1099.94
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    price = base.strategy.position_handler.position.take_profit_order.price
    status = ORDER_STATUS_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=remaining_quantity,
        order_id=7,
    )

    await base.strategy.process_order()

    assert base.strategy.position_handler.position.orders == []
    assert base.strategy.position_handler.position.take_profit_order == Order(
        price=0, quantity=0
    )
    assert base.strategy.balance == 1199.88
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT


async def test_short_all_orders_filled_then_liquidation(base):
    base.strategy.client.futures_position_information.side_effect = (
        get_position_information_when_short()
    )
    base.strategy.client.futures_create_order.side_effect = get_orders_short()
    base.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    base.strategy.client.futures_get_order.side_effect = validation_orders()

    await start_short(base=base.strategy)
    await first_order_filled(base=base.strategy)

    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    assert base.strategy.position_handler.position.take_profit_order.price == 19200.0
    assert base.strategy.position_handler.position.liquidation_price == 20800

    await second_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19248.0
    assert base.strategy.position_handler.position.liquidation_price == 20848.0
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.SHORT

    await third_and_fourth_order_filled(base=base.strategy)
    assert base.strategy.position_handler.position.take_profit_order.price == 19344.0
    assert base.strategy.position_handler.position.liquidation_price == 20944.0

    price = base.strategy.position_handler.position.liquidation_price
    quantity = base.strategy.position_handler.position.take_profit_order.quantity
    status = ORDER_STATUS_FILLED

    base.strategy.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=6,
        order_type="LIQUIDATION",
    )

    await base.strategy.process_order()

    assert base.strategy.position_handler.position.orders == []
    assert base.strategy.position_handler.position.take_profit_order == Order(
        price=0, quantity=0
    )
    assert base.strategy.balance == 800.00
    assert base.strategy.df_handler.df.iloc[-1]["Position"] == State.FLAT
