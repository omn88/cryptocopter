import asyncio
from datetime import datetime
from typing import List, Optional, Tuple
import logging
import binance
import pytz
from binance.enums import (
    FUTURE_ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    FUTURE_ORDER_TYPE_MARKET,
)
from binance.exceptions import BinanceAPIException
from src.common.constants import (
    SYMBOL,
    LEVERAGE,
    DCA_SPAN,
    NUMBER_OF_DCA_ORDERS,
    LOSSES_PER_LEVEL,
)
import pandas

from src.common.identifiers import Order, PositionSide, PositionMode, Position

logger = logging.getLogger("orders")


def order_quantity_list_prepare(
    order_values: Optional[List[float]] = None,
) -> pandas.DataFrame:
    order_values = (
        [
            1,
            2,
            5,
            10,
            15,
            20,
            25,
            50,
            100,
            200,
            300,
            400,
            500,
            600,
            700,
            800,
            900,
            1000,
            1250,
            1500,
            1750,
            2000,
            2500,
            3000,
            3500,
            4000,
            5000,
            6000,
            7000,
            8000,
            9000,
            10000,
            12500,
            15000,
            17500,
            20000,
            25000,
            30000,
            35000,
            40000,
            45000,
            50000,
        ]
        if order_values is None
        else order_values
    )

    # OQL stands for order quantity list
    oql = pandas.DataFrame(order_values, columns=["order_value"])
    oql.set_index(pandas.Index(list(range(len(order_values)))))
    oql["sum_of_all_losses"] = oql.order_value * NUMBER_OF_DCA_ORDERS * LOSSES_PER_LEVEL
    oql["threshold"] = oql.sum_of_all_losses + oql.sum_of_all_losses.shift(1)
    oql.at[oql.index[0], "threshold"] = oql.at[oql.index[0], "sum_of_all_losses"]

    logger.debug("Order quantity list: \n%s", oql)

    return oql


def order_quantity_check(oql: pandas.DataFrame, balance: float) -> Tuple[int, int]:
    index_list = []

    for threshold in oql.threshold:
        if balance > threshold:
            index_list.append(threshold)

    if len(index_list) > 0:
        order_quantity = oql.order_value[len(index_list)]
    else:
        order_quantity = oql.order_value[0]

    return order_quantity, len(index_list) + 1


async def send_order(client: binance.AsyncClient, side: str, order: Order) -> Order:
    resp = await client.futures_create_order(
        symbol=SYMBOL,
        price=round(order.price, 1),
        quantity=round(abs(order.quantity), 3),
        side=side,
        type=FUTURE_ORDER_TYPE_LIMIT,
        timeInForce=TIME_IN_FORCE_GTC,
    )
    logger.debug("RESP: %s", resp)
    order.order_id = int(resp["orderId"])
    order.status = resp["status"]
    logger.info(
        "New %s order, price: %s, quantity: %s, side: %s, order_id: %s, status: %s",
        order.order_type,
        order.price,
        order.quantity,
        side,
        order.order_id,
        order.status,
    )

    return order


async def cancel_order(client: binance.AsyncClient, order: Order):
    logger.info("Enter cancel order: %s, symbol: %s", order.order_id, SYMBOL)

    try:
        resp = await client.futures_cancel_order(symbol=SYMBOL, orderId=order.order_id)
    except BinanceAPIException as e:
        # Log the exception
        logger.info(e)
        return None

    if resp["status"] != ORDER_STATUS_CANCELED:
        logger.info(
            "Order status for order: %s was not set to cancelled. Got: %s",
            order.order_id,
            resp["status"],
        )
        return None
    logger.info("Exit cancel order")
    return resp["status"]


async def send_orders(
    client: binance.AsyncClient, side: str, orders: List[Order]
) -> List[Order]:
    """Send a list of orders concurrently.

    Args:
        client: A `binance.AsyncClient` object.
        side: The side of the orders (either `PositionSide.BUY` or `PositionSide.SELL`).
        orders: A list of `Order` objects to send.

    Returns:
        A list of `Order` objects with updated order IDs and statuses.
    """
    tasks = []
    for order in orders:
        task = asyncio.create_task(send_order(client=client, side=side, order=order))
        tasks.append(task)
    results = await asyncio.gather(*tasks)

    return list(results)


async def get_orders(client: binance.AsyncClient, orders: List[Order]) -> List[Order]:
    tasks = []
    for order in orders:
        task = asyncio.create_task(futures_get_order(client=client, order=order))
        tasks.append(task)
    results = await asyncio.gather(*tasks)

    return list(results)


def target_price_calculate(side: str, price: float) -> float:
    logger.info("Entering target price calculate")
    if side == PositionSide.LONG:
        target_price = round((1 + (100 / LEVERAGE / 100)) * price, 1)
    elif side == PositionSide.SHORT:
        target_price = round((1 - (100 / LEVERAGE / 100)) * price, 1)
    else:
        raise AssertionError("Wrong position side: %s", side)

    logger.info("position side: %s, target: %s" % (side, target_price))
    return target_price


def get_order_price(side: str, entry_price: float, order: int):
    if side == PositionSide.LONG:
        return round((entry_price - (DCA_SPAN * order * entry_price)), 1)

    if side == PositionSide.SHORT:
        return round((entry_price + (DCA_SPAN * order * entry_price)), 1)


def get_order_quantity(
    side: str,
    mode: PositionMode,
    order_quantity: float,
    entry_price: float,
    order: int,
):
    if side == PositionSide.LONG and mode == PositionMode.DCA:
        return round(
            LEVERAGE
            * order_quantity
            / (round((entry_price - (DCA_SPAN * order * entry_price)), 2)),
            3,
        )

    if side == PositionSide.LONG and mode == PositionMode.FULL:
        return round(
            LEVERAGE
            * order_quantity
            * NUMBER_OF_DCA_ORDERS
            / (round((entry_price - (DCA_SPAN * order * entry_price)), 2)),
            3,
        )

    if side == PositionSide.SHORT and mode == PositionMode.DCA:
        return round(
            LEVERAGE
            * order_quantity
            / (round((entry_price + (DCA_SPAN * order * entry_price)), 2)),
            3,
        )

    if side == PositionSide.SHORT and mode == PositionMode.FULL:
        return round(
            LEVERAGE
            * order_quantity
            * NUMBER_OF_DCA_ORDERS
            / (round((entry_price + (DCA_SPAN * order * entry_price)), 2)),
            3,
        )


def prepare_orders(
    position: Position,
    mode: PositionMode,
    entry_price: float,
    balance: float,
    order_quantity_list: pandas.DataFrame,
) -> Position:
    logger.info("Entering prepare orders")

    number_of_dca_orders = 1 if mode == PositionMode.FULL else NUMBER_OF_DCA_ORDERS
    order_quantity_stable, order_level = order_quantity_check(
        oql=order_quantity_list, balance=balance
    )
    position.artifacts.order_quantity_stable = order_quantity_stable
    position.artifacts.order_level = order_level
    position.artifacts.max_position = order_quantity_stable * float(
        number_of_dca_orders
    )
    position.artifacts.side = position.side
    position.artifacts.mode = mode
    position.artifacts.leverage = LEVERAGE

    logger.info(
        "Balance: %s, single order value: %s USDT, number of dca orders: %s, dca span: %s",
        balance,
        order_quantity_stable,
        number_of_dca_orders,
        DCA_SPAN,
    )

    position.orders = [
        Order(
            price=get_order_price(
                side=position.side,
                entry_price=entry_price,
                order=order,
            ),
            quantity=get_order_quantity(
                side=position.side,
                mode=mode,
                order_quantity=order_quantity_stable,
                entry_price=entry_price,
                order=order,
            ),
            order_id=0,
            quantity_stable=order_quantity_stable,
        )
        for order in range(number_of_dca_orders)
    ]

    logger.info("Exiting prepare orders")
    return position


def convert_time(timestamp):
    # Binance timestamp is in milliseconds, convert it to seconds
    timestamp_s = timestamp / 1000

    # Create datetime object in UTC
    utc_time = datetime.utcfromtimestamp(timestamp_s)

    # Add timezone information
    utc_time = utc_time.replace(tzinfo=pytz.utc)

    # Convert to Polish timezone
    poland_time = utc_time.astimezone(pytz.timezone("Europe/Warsaw"))

    return poland_time


async def futures_get_order(client: binance.AsyncClient, order: Order) -> Order:
    resp = await client.futures_get_order(symbol=SYMBOL, orderId=order.order_id)
    order.status = resp["status"]
    realized_quantity = round(float(resp["executedQty"]), 3)
    order.realized_quantity = realized_quantity

    # Convert 'time' to Polish local time and set it as 'open_time'
    order.open_time = convert_time(resp["time"])

    logger.info(
        "Validation, order: %s opened at: %s, realized qty: %s, status: %s",
        order.order_id,
        order.open_time,
        order.realized_quantity,
        order.status,
    )

    return order


async def cancel_take_profit_order(
    client: binance.AsyncClient, take_profit_order: Order
) -> str:
    take_profit_order.status = await cancel_order(
        client=client,
        order=take_profit_order,
    )
    logger.info(
        "Take profit order: %s, status: %s",
        take_profit_order.order_id,
        take_profit_order.status,
    )

    return take_profit_order.status


async def send_market_order(
    client: binance.AsyncClient,
    position: Position,
    side: str,
) -> Position:
    order_type = FUTURE_ORDER_TYPE_MARKET
    quantity = abs(position.quantity)
    resp = await client.futures_create_order(
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        type=order_type,
    )
    position.market_order = Order(
        order_type=order_type,
        order_id=int(resp["orderId"]),
        price=0,
        quantity=quantity,
    )
    logger.info(
        "%s order, type: %s send: %s",
        side,
        order_type,
        resp,
    )

    return position


async def cancel_remaining_limit_orders(
    client: binance.AsyncClient, position: Position
) -> Tuple[Position, bool]:
    logger.info("Cancelling remaining limit orders")
    assert position.orders is not None
    new_orders_count = 0
    cancelled_orders_count = 0
    for order in position.orders:
        if order.status == ORDER_STATUS_PARTIALLY_FILLED:
            order.status = await cancel_order(client=client, order=order)
            logger.info("Cancelled partially filled order_id: %s", order.order_id)
            cancelled_orders_count += 1
        elif order.status == ORDER_STATUS_NEW:
            new_orders_count += 1
            order.status = await cancel_order(client=client, order=order)
            logger.info("Cancelled new order_id: %s", order.order_id)
            cancelled_orders_count += 1

    position_opened = new_orders_count != len(position.orders)

    return position, position_opened
