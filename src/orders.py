import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple
import logging
import binance
from binance.exceptions import BinanceAPIException

from constants import SYMBOL, LEVERAGE, DCA_SPAN, NUMBER_OF_DCA_ORDERS, LOSSES_PER_LEVEL
from src import features
import pandas

logger = logging.getLogger("orders")


class PositionSide:
    LONG = "BUY"
    SHORT = "SELL"
    FLAT = "FLAT"


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"
    NEW = "NEW"


@dataclass
class Order:
    price: float
    quantity: float
    quantity_stable: float = 0
    order_id: int = 0
    realized_quantity: float = 0
    time_in_force: str = binance.AsyncClient.TIME_IN_FORCE_GTC
    status: str = binance.AsyncClient.ORDER_STATUS_NEW
    order_type: str = binance.AsyncClient.ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return (
            f"Order(price={self.price}, quantity={self.quantity}, "
            f"quantity_stable={self.quantity_stable}, order_id={self.order_id}, "
            f"realized_quantity={self.realized_quantity}, "
            f"time_in_force={self.time_in_force}, status={self.status})"
        )


@dataclass()
class Artifacts:
    start_balance: float = 0
    no_of_dca_orders: int = 0
    leverage: int = 0
    order_quantity_stable: int = 0
    order_level: int = 0
    max_position: float = 0
    price: float = 0
    quantity: float = 0
    side: str = "NEW"
    mode: PositionMode = PositionMode.NEW
    close_price: float = 0
    orders: Optional[List[Order]] = None
    per_cent_earned: float = 0
    stable_earned: float = 0
    end_balance: float = 0
    status: str = "NEW"

    def __repr__(self):
        return (
            f"Artifacts(start_balance={self.start_balance}, no_of_dca_orders={self.no_of_dca_orders},"
            f" leverage={self.leverage}, order_quantity_stable={self.order_quantity_stable},"
            f" max_position={self.max_position}, price={self.price}, quantity={self.quantity},"
            f" side='{self.side}', mode='{self.mode}', close_price={self.close_price}, orders={self.orders},"
            f" per_cent_earned={self.per_cent_earned}, stable_earned={self.stable_earned},"
            f" end_balance={self.end_balance}, status='{self.status}')"
        )


@dataclass()
class CurrentPosition:
    price: float = 0
    quantity: float = 0
    status: features.Signals = features.Signals.FLAT
    side: str = PositionSide.FLAT
    orders: Optional[List[Order]] = None
    liquidation_price: float = 0
    target_price: float = 0
    take_profit_order: Optional[Order] = None
    market_order: Optional[Order] = None
    artifacts: Artifacts = Artifacts()

    def __post_init__(self):
        if self.orders is None:
            self.orders = []

    def __repr__(self) -> str:
        return (
            f"\nCurrentPosition(price={self.price}, quantity={self.quantity}, side={self.side}, "
            f"liquidation_price={self.liquidation_price}, target_price={self.target_price}, "
            f"take_profit_order={self.take_profit_order})"
        )


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
    oql.set_index(pandas.Index([i for i in range(len(order_values))]))
    oql["sum_of_all_losses"] = oql.order_value * NUMBER_OF_DCA_ORDERS * LOSSES_PER_LEVEL
    oql["threshold"] = oql.sum_of_all_losses + oql.sum_of_all_losses.shift(1)
    oql.at[oql.index[0], "threshold"] = oql.at[oql.index[0], "sum_of_all_losses"]

    return oql


@dataclass
class Position:
    current_position: CurrentPosition = CurrentPosition()
    order_quantity_list: pandas.DataFrame = order_quantity_list_prepare()
    balance: float = 0
    expected_balance: float = 0

    def __repr__(self) -> str:
        return (
            f"Position(current_position={self.current_position}, "
            f"balance={self.balance}, "
            f"order_quantity_list={self.order_quantity_list}"
        )


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
        type=client.FUTURE_ORDER_TYPE_LIMIT,
        timeInForce=client.TIME_IN_FORCE_GTC,
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

    if resp["status"] != client.ORDER_STATUS_CANCELED:
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
    current_position: CurrentPosition,
    mode: PositionMode,
    entry_price: float,
    balance: float,
    order_quantity_list: pandas.DataFrame,
) -> CurrentPosition:
    logger.info("Entering prepare orders")

    number_of_dca_orders = 1 if mode == PositionMode.FULL else NUMBER_OF_DCA_ORDERS
    order_quantity_stable, order_level = order_quantity_check(
        oql=order_quantity_list, balance=balance
    )
    current_position.artifacts.order_quantity_stable = order_quantity_stable
    current_position.artifacts.order_level = order_level
    current_position.artifacts.max_position = order_quantity_stable * float(
        number_of_dca_orders
    )
    current_position.artifacts.side = current_position.side
    current_position.artifacts.mode = mode
    current_position.artifacts.leverage = LEVERAGE

    logger.info(
        "Balance: %s, single order value: %s USDT, number of dca orders: %s, dca span: %s",
        balance,
        order_quantity_stable,
        number_of_dca_orders,
        DCA_SPAN,
    )

    current_position.orders = [
        Order(
            price=get_order_price(
                side=current_position.side,
                entry_price=entry_price,
                order=order,
            ),
            quantity=get_order_quantity(
                side=current_position.side,
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
    return current_position


async def futures_get_order(client: binance.AsyncClient, order: Order) -> Order:
    resp = await client.futures_get_order(symbol=SYMBOL, orderId=order.order_id)
    updated_status = resp["status"]
    realized_quantity = round(float(resp["executedQty"]), 3)
    order.realized_quantity = realized_quantity
    order.status = updated_status
    logger.info(
        "Validation, order: %s, realized qty: %s, status: %s",
        resp["orderId"],
        realized_quantity,
        updated_status,
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
    current_position: CurrentPosition,
    side: str,
):
    try:
        resp = await client.futures_create_order(
            symbol=SYMBOL,
            side=side,
            quantity=abs(current_position.quantity),
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        logger.info(
            "%s order, type: %s send: %s",
            side,
            client.FUTURE_ORDER_TYPE_MARKET,
            resp,
        )
    except BinanceAPIException as exception:
        logger.info("exception: %s", exception)


async def cancel_remaining_limit_orders(
    client: binance.AsyncClient, current_position: CurrentPosition
) -> CurrentPosition:
    logger.info("Cancelling remaining limit orders")
    assert current_position.orders is not None
    for order in current_position.orders:
        if order.status in [
            client.ORDER_STATUS_PARTIALLY_FILLED,
            client.ORDER_STATUS_NEW,
        ]:
            order.status = await cancel_order(client=client, order=order)
            logger.info(
                "Order with order_id: %s should be cancelled and is: %s",
                order.order_id,
                order.status,
            )

    return current_position
