import logging
from typing import Tuple

import binance
import pandas

from src.common.identifiers import (
    Signal,
    SignalUpdate,
    Position,
    State,
    OrderUpdate,
    Order,
)

logger = logging.getLogger("common")


def generate_signal(signal: Signal, df: pandas.DataFrame) -> SignalUpdate:
    entry_price = round(float(df.at[df.index[-1], "Close"]), 1)
    return SignalUpdate(signal=signal, price=entry_price)


def assert_dca_long_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert state == position.status
    assert all(order.price <= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


def assert_dca_short_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert (
        state == position.status
    ), f"State: {state}, position.status: {position.status}"
    assert all(order.price >= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


async def first_order_filled(base):

    assert base.position.orders is not None
    price = base.position.orders[0].price
    quantity = base.position.orders[0].quantity

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=binance.AsyncClient.ORDER_STATUS_FILLED,
        order_id=1,
        last_filled_quantity=quantity,
        realized_quantity=quantity,
    )

    await base.process_order()

    assert base.position.orders is not None

    assert base.position.orders[0].status == binance.AsyncClient.ORDER_STATUS_FILLED
    assert base.position.orders[1].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert base.position.orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert base.position.orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert base.position.entry_price == price
    assert base.position.quantity == quantity
    assert base.position.take_profit_order is not None
    assert base.position.take_profit_order.quantity == base.position.orders[0].quantity
    assert base.position.orders[0].realized_quantity == quantity


async def second_order_filled(base):

    orders = base.position.orders
    assert orders is not None

    price = orders[1].price
    quantity = orders[1].quantity
    status = binance.AsyncClient.ORDER_STATUS_FILLED

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        order_id=2,
        last_filled_quantity=quantity,
        realized_quantity=quantity,
    )

    await base.process_order()

    average_price = round(
        (orders[0].price + orders[1].price) / 2,
        1,
    )

    total_quantity = round(
        (orders[0].realized_quantity + orders[1].realized_quantity),
        3,
    )

    assert orders[0].status == binance.AsyncClient.ORDER_STATUS_FILLED
    assert orders[1].status == binance.AsyncClient.ORDER_STATUS_FILLED
    assert orders[2].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert orders[3].status == binance.AsyncClient.ORDER_STATUS_NEW
    assert base.position.entry_price == average_price
    assert base.position.quantity == total_quantity
    assert base.position.take_profit_order is not None
    assert base.position.take_profit_order.quantity == total_quantity
    assert orders[1].realized_quantity == quantity


async def third_and_fourth_order_filled(base):

    orders = base.position.orders
    assert orders is not None

    price = orders[2].price
    quantity = orders[2].quantity
    status = base.client.ORDER_STATUS_FILLED

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=3,
    )

    await base.process_order()

    assert orders[0].status == base.client.ORDER_STATUS_FILLED
    assert orders[1].status == base.client.ORDER_STATUS_FILLED
    assert orders[2].status == base.client.ORDER_STATUS_FILLED
    assert orders[3].status == base.client.ORDER_STATUS_NEW
    assert base.position.take_profit_order is not None

    assert base.position.take_profit_order.quantity == (
        orders[0].quantity + orders[1].quantity + orders[2].quantity
    )

    price = orders[3].price
    quantity = orders[3].quantity
    status = base.client.ORDER_STATUS_FILLED

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=4,
    )

    await base.process_order()

    assert orders[0].status == base.client.ORDER_STATUS_FILLED
    assert orders[1].status == base.client.ORDER_STATUS_FILLED
    assert orders[2].status == base.client.ORDER_STATUS_FILLED
    assert orders[3].status == base.client.ORDER_STATUS_FILLED
    assert base.position.entry_price == round(
        (orders[0].price + orders[1].price + orders[2].price + orders[3].price) / 4,
        1,
    )
    assert base.position.take_profit_order is not None
    assert base.position.take_profit_order.quantity == (
        orders[0].quantity
        + orders[1].quantity
        + orders[2].quantity
        + orders[3].quantity
    )


async def target_reached(base):
    assert isinstance(base.position.take_profit_order, Order)

    price = base.position.take_profit_order.price
    quantity = base.position.take_profit_order.quantity
    status = base.client.ORDER_STATUS_FILLED

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=5,
    )

    await base.process_order()

    assert base.position.orders == []
    assert base.position.take_profit_order == Order(price=0, quantity=0)


async def start_long(base) -> None:

    base.signal_update = generate_signal(signal=Signal.LONG, df=base.df)

    await base.process_signal()

    assert_dca_long_opened(
        position=base.position,
        balance=base.balance,
        state=base.state,
        signal_update=base.signal_update,
        df=base.df,
    )


async def start_short(base) -> None:

    base.signal_update = generate_signal(signal=Signal.SHORT, df=base.df)

    await base.process_signal()

    assert_dca_short_opened(
        position=base.position,
        balance=base.balance,
        state=base.state,
        signal_update=base.signal_update,
        df=base.df,
    )


def get_orders_long(base):
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 5,
            "price": 20800.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 6,
            "price": 20700.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 7,
            "price": 20600.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 8,
            "price": 20500.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
    ]


def get_orders_short(base):
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 20100.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 20200.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 20300.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 5,
            "price": 19200.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 6,
            "price": 19300.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 7,
            "price": 19400.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 8,
            "price": 19500.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
    ]


def get_orders_long_then_short(base):
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 5,
            "price": 20000.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 6,
            "price": 20100.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 7,
            "price": 20200.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 8,
            "price": 20300.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
    ]


def get_orders_short_then_long(base):
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 2,
            "price": 20100.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 3,
            "price": 20200.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 4,
            "price": 20300.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 5,
            "price": 20000.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 6,
            "price": 19900.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 7,
            "price": 19800.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
        {
            "orderId": 8,
            "price": 19700.00,
            "status": base.client.ORDER_STATUS_NEW,
        },
    ]


def get_position_information():
    return [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]


def get_position_information_for_order_partially_filled():
    return [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.046"}],
    ]


def get_cancel_order():
    return {"status": "CANCELED"}
