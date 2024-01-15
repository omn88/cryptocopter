import logging

import pandas
from binance.enums import (
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
)
from src.common.common import signal_to_state
from src.common.constants import NUMBER_OF_DCA_ORDERS

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
    return SignalUpdate(
        signal=signal, price=round(float(df.at[df.index[-1], "Close"]), 1)
    )


def assert_dca_long_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert NUMBER_OF_DCA_ORDERS == len(position.orders)
    assert 1000 == balance
    logger.info("State: %s, type: %s", state, type(state))
    assert state == signal_to_state(signal_update.signal)
    assert state == position.state
    assert all(order.price <= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


def assert_dca_short_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert NUMBER_OF_DCA_ORDERS == len(position.orders)
    assert 1000 == balance
    logger.info("State: %s, type: %s", state, type(state))
    assert state == signal_to_state(signal_update.signal)
    assert state == position.state, f"State: {state}, position.status: {position.state}"
    assert all(order.price >= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


async def first_order_filled(base, order_id=1):
    assert base.position.orders is not None
    price = base.position.orders[0].price
    quantity = base.position.orders[0].quantity

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=ORDER_STATUS_FILLED,
        order_id=order_id,
        last_filled_quantity=quantity,
        realized_quantity=quantity,
    )

    await base.process_order()

    assert base.position.orders is not None

    logger.info(
        "tpq: %s, bpoq: %s, tp: %s",
        base.position.take_profit_order.quantity,
        base.position.orders[0].quantity,
        base.position.take_profit_order,
    )

    assert base.position.orders[0].status == ORDER_STATUS_FILLED
    assert base.position.orders[1].status == ORDER_STATUS_NEW
    assert base.position.orders[2].status == ORDER_STATUS_NEW
    assert base.position.orders[3].status == ORDER_STATUS_NEW
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
    status = ORDER_STATUS_FILLED

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
        (orders[0].quantity + orders[1].quantity),
        3,
    )
    logger.info("q: %s, tq: %s", base.position.quantity, total_quantity)
    assert orders[0].status == ORDER_STATUS_FILLED
    assert orders[1].status == ORDER_STATUS_FILLED
    assert orders[2].status == ORDER_STATUS_NEW
    assert orders[3].status == ORDER_STATUS_NEW
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
    status = ORDER_STATUS_FILLED

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=3,
    )

    await base.process_order()

    assert orders[0].status == ORDER_STATUS_FILLED
    assert orders[1].status == ORDER_STATUS_FILLED
    assert orders[2].status == ORDER_STATUS_FILLED
    assert orders[3].status == ORDER_STATUS_NEW
    assert base.position.take_profit_order is not None

    assert base.position.take_profit_order.quantity == (
        orders[0].quantity + orders[1].quantity + orders[2].quantity
    )

    price = orders[3].price
    quantity = orders[3].quantity
    status = ORDER_STATUS_FILLED

    base.order_update = OrderUpdate(
        price=price,
        quantity=quantity,
        status=status,
        realized_quantity=quantity,
        last_filled_quantity=quantity,
        order_id=4,
    )

    await base.process_order()

    assert orders[0].status == ORDER_STATUS_FILLED
    assert orders[1].status == ORDER_STATUS_FILLED
    assert orders[2].status == ORDER_STATUS_FILLED
    assert orders[3].status == ORDER_STATUS_FILLED
    assert base.position.entry_price == round(
        (orders[0].price + orders[1].price + orders[2].price + orders[3].price) / 4,
        1,
    )
    assert base.position.take_profit_order is not None
    logger.info(
        "1: %s, 2: %s",
        base.position.take_profit_order.quantity,
        (
            orders[0].quantity
            + orders[1].quantity
            + orders[2].quantity
            + orders[3].quantity
        ),
    )
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
    status = ORDER_STATUS_FILLED

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


def get_orders_long():
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 5,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 6,
            "price": 20700.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 7,
            "price": 20600.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 8,
            "price": 20500.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 9,
            "price": 20500.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
    ]


def validation_orders():
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 5,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 6,
            "price": 20700.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 7,
            "price": 20600.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 8,
            "price": 20500.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 14,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 6,
            "price": 20700.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 7,
            "price": 20600.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 8,
            "price": 20500.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 1,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 5,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 6,
            "price": 20700.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 7,
            "price": 20600.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 8,
            "price": 20500.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 14,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 6,
            "price": 20700.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 7,
            "price": 20600.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
        {
            "orderId": 8,
            "price": 20500.00,
            "status": ORDER_STATUS_NEW,
            "time": 0,
            "executedQty": 0,
        },
    ]


def get_orders_short():
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 2,
            "price": 20100.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 3,
            "price": 20200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 4,
            "price": 20300.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 5,
            "price": 19200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 6,
            "price": 19300.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 7,
            "price": 19400.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 8,
            "price": 19500.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
    ]


def get_orders_long_then_short():
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 5,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 6,
            "price": 20100.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 7,
            "price": 20200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 8,
            "price": 20300.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
    ]


def get_orders_long_then_market_then_short():
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 2,
            "price": 19900.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 3,
            "price": 19800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 4,
            "price": 19700.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 5,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 6,
            "price": 20748.0,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 7,
            "price": 20696.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 8,
            "price": 20644.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 9,
            "price": 0,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_MARKET,
        },
        {
            "orderId": 10,
            "price": 20500.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 11,
            "price": 20600.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 12,
            "price": 20700.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 13,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT
            # "type":
        },
        {
            "orderId": 14,
            "price": 19200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 15,
            "price": 20600.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 16,
            "price": 20700.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
        {
            "orderId": 17,
            "price": 20800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT
            # "type":
        },
        {
            "orderId": 18,
            "price": 19200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
            "type": ORDER_TYPE_LIMIT,
        },
    ]


def get_orders_short_then_long():
    return [
        {
            "orderId": 1,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 2,
            "price": 20100.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 3,
            "price": 20200.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 4,
            "price": 20300.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 5,
            "price": 20000.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 6,
            "price": 19900.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 7,
            "price": 19800.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
        {
            "orderId": 8,
            "price": 19700.00,
            "status": ORDER_STATUS_NEW,
            "updateTime": 1566818724722,
        },
    ]


def get_position_information_when_long():
    return [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
    ]


def get_position_information_when_long_for_order_partially_filled():
    return [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.046"}],
    ]


def get_position_information_when_short():
    return [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20848", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20896", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20944", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]


def get_position_information_when_long_then_short():
    return [
        [{"liquidationPrice": "19200", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "19152", "entryPrice": "19950", "positionAmt": "0.125"}],
        [{"liquidationPrice": "19104", "entryPrice": "19900", "positionAmt": "0.188"}],
        [{"liquidationPrice": "19056", "entryPrice": "19850", "positionAmt": "0.251"}],
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.062"}],
        [{"liquidationPrice": "20848", "entryPrice": "20050", "positionAmt": "0.124"}],
        [{"liquidationPrice": "20896", "entryPrice": "20100", "positionAmt": "0.186"}],
        [{"liquidationPrice": "20944", "entryPrice": "20150", "positionAmt": "0.248"}],
    ]


def get_position_information_when_short_for_order_partially_filled():
    return [
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.031"}],
        [{"liquidationPrice": "20800", "entryPrice": "20000", "positionAmt": "0.046"}],
    ]


def get_cancel_order():
    return {"status": "CANCELED"}
