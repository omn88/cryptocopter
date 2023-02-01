import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Optional
import logging
import binance
from binance.exceptions import BinanceAPIException

from src import features
import pandas

from src.common import position_information

logger = logging.getLogger("orders")


class PositionSide:
    LONG = "BUY"
    SHORT = "SELL"
    FLAT = "FLAT"


@dataclass
class Order:
    price: float
    quantity: float
    quantity_stable: float = 0
    order_id: int = 0
    realized_quantity: float = 0
    time_in_force: str = binance.AsyncClient.TIME_IN_FORCE_GTC
    status: str = binance.AsyncClient.ORDER_STATUS_NEW

    def __repr__(self) -> str:
        return (
            f"Order(price={self.price}, quantity={self.quantity}, "
            f"quantity_stable={self.quantity_stable}, order_id={self.order_id}, "
            f"realized_quantity={self.realized_quantity}, "
            f"time_in_force={self.time_in_force}, status={self.status})"
        )


@dataclass()
class CurrentPosition:
    price: float = 0
    quantity: float = 0
    side: str = PositionSide.FLAT
    liquidation_price: float = 0
    target_price: float = 0
    take_profit_order: Optional[Order] = None

    def __repr__(self) -> str:
        return (
            f"\nCurrentPosition(price={self.price}, quantity={self.quantity}, side={self.side}, "
            f"liquidation_price={self.liquidation_price}, target_price={self.target_price}, "
            f"take_profit_order={self.take_profit_order})"
        )


def order_quantity_list_prepare(
    number_of_dca_orders: int = 4,
    order_values: Optional[List[float]] = None,
    losses_per_level: int = 4,
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
    oql["sum_of_all_losses"] = oql.order_value * number_of_dca_orders * losses_per_level
    oql["threshold"] = oql.sum_of_all_losses + oql.sum_of_all_losses.shift(1)
    # oql.threshold.iloc[0] = oql.sum_of_all_losses.iloc[0]
    oql.at[oql.index[0], "threshold"] = oql.at[oql.index[0], "sum_of_all_losses"]

    return oql


def order_quantity_check(oql: pandas.DataFrame, saldo: float) -> float:
    logger.info("Saldo: %s", saldo)
    # try:
    #     index = next(i for i, thrshld in enumerate(oql.threshold) if saldo > thrshld)
    # except StopIteration:
    #     index = 0

    index_list = []

    [index_list.append(thrshld) for thrshld in oql.threshold if saldo > thrshld]

    order_quantity = (
        oql.order_value[len(index_list) - 1]
        if len(index_list) > 0
        else oql.order_value[0]
    )

    # order_quantity = oql.order_value[index]
    logger.info("Order quantity: %s", order_quantity)
    return order_quantity


@dataclass
class Position:
    symbol: str
    current_position: CurrentPosition = CurrentPosition()
    orders: List[Order] = field(default_factory=list)
    status: features.Signals = features.Signals.FLAT
    order_quantity_list: pandas.DataFrame = order_quantity_list_prepare()
    number_of_dca_orders = 4
    saldo: float = 0
    calculated_saldo: float = 0
    leverage: int = 25

    def __repr__(self) -> str:
        return (
            f"Position(symbol={self.symbol}, current_position={self.current_position}, "
            f"orders={self.orders}, status={self.status}, saldo={self.saldo}, leverage={self.leverage}, "
            f"order_quantity_list={self.order_quantity_list}, number_of_dca_orders={self.number_of_dca_orders}, "
            f"calculated_saldo={self.calculated_saldo})"
        )


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"


async def send_order(
    client: binance.AsyncClient, symbol: str, side: str, order: Order
) -> Order:

    resp = await client.futures_create_order(
        symbol=symbol,
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
        "New LIMIT order, Price: %s, quantity: %s, side: %s, order_id: %s, status: %s",
        order.price,
        order.quantity,
        side,
        order.order_id,
        order.status,
    )

    return order


async def cancel_order(client: binance.AsyncClient, order: Order, symbol: str):
    logger.info("Enter cancel order: %s, symbol: %s", order.order_id, symbol)

    try:
        resp = await client.futures_cancel_order(symbol=symbol, orderId=order.order_id)
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
    client: binance.AsyncClient, symbol: str, side: str, orders: List[Order]
) -> List[Order]:
    """Send a list of orders concurrently.

    Args:
        client: A `binance.AsyncClient` object.
        symbol: The symbol to send the orders for.
        side: The side of the orders (either `PositionSide.BUY` or `PositionSide.SELL`).
        orders: A list of `Order` objects to send.

    Returns:
        A list of `Order` objects with updated order IDs and statuses.
    """
    tasks = []
    for order in orders:
        task = asyncio.create_task(send_order(client, symbol, side, order))
        tasks.append(task)
    results = await asyncio.gather(*tasks)

    return list(results)


def target_price_calculate(side: str, price: float, leverage: int) -> float:
    logger.info("Entering target price calculate")
    if side == PositionSide.LONG:
        target_price = round((1 + (100 / leverage / 100)) * price, 1)
    elif side == PositionSide.SHORT:
        target_price = round((1 - (100 / leverage / 100)) * price, 1)
    else:
        raise AssertionError("Wrong position side: %s", side)

    logger.info("position side: %s, target: %s" % (side, target_price))
    return target_price


def get_order_price(side: str, entry_price: float, dca_span: float, order: int):

    if side == PositionSide.LONG:
        return round((entry_price - (dca_span * order * entry_price)), 1)

    if side == PositionSide.SHORT:
        return round((entry_price + (dca_span * order * entry_price)), 1)


def get_order_quantity(
    side: str,
    mode: PositionMode,
    leverage: int,
    order_quantity: float,
    entry_price: float,
    dca_span: float,
    order: int,
    number_of_dca_orders: int,
):

    if side == PositionSide.LONG and mode == PositionMode.DCA:
        return round(
            leverage
            * order_quantity
            / (round((entry_price - (dca_span * order * entry_price)), 2)),
            3,
        )

    if side == PositionSide.LONG and mode == PositionMode.FULL:
        return round(
            leverage
            * order_quantity
            * number_of_dca_orders
            / (round((entry_price - (dca_span * order * entry_price)), 2)),
            3,
        )

    if side == PositionSide.SHORT and mode == PositionMode.DCA:
        return round(
            leverage
            * order_quantity
            / (round((entry_price + (dca_span * order * entry_price)), 2)),
            3,
        )

    if side == PositionSide.SHORT and mode == PositionMode.FULL:
        return round(
            leverage
            * order_quantity
            * number_of_dca_orders
            / (round((entry_price + (dca_span * order * entry_price)), 2)),
            3,
        )


def prepare_orders(
    side: str,
    mode: PositionMode,
    entry_price: float,
    saldo: float,
    number_of_dca_orders: int,
    leverage: int,
    order_quantity_list: pandas.DataFrame,
    dca_span: float = 0.005,
) -> Tuple[List[Order], float]:
    logger.info("Entering prepare orders")

    number_of_dca_orders = 1 if mode == PositionMode.FULL else number_of_dca_orders

    order_quantity_stable = order_quantity_check(oql=order_quantity_list, saldo=saldo)
    logger.info(
        "Saldo: %s, single order value: %s USDT, number of dca orders: %s, dca span: %s",
        saldo,
        order_quantity_stable,
        number_of_dca_orders,
        dca_span,
    )

    orders = [
        Order(
            price=get_order_price(
                side=side,
                entry_price=entry_price,
                dca_span=dca_span,
                order=order,
            ),
            quantity=get_order_quantity(
                side=side,
                mode=mode,
                leverage=leverage,
                order_quantity=order_quantity_stable,
                entry_price=entry_price,
                dca_span=dca_span,
                order=order,
                number_of_dca_orders=number_of_dca_orders,
            ),
            order_id=0,
            quantity_stable=order_quantity_stable,
        )
        for order in range(number_of_dca_orders)
    ]

    for order in orders:
        logger.debug("Order: %s", order)

    logger.info("Exiting prepare orders")
    return orders, saldo


async def futures_long_position_open(
    client: binance.AsyncClient,
    signal: features.Signals,
    position: Position,
    entry_price: float,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Entering long position open, mode: %s", mode)
    position.current_position = CurrentPosition(side=PositionSide.LONG)

    position.status = signal

    position.orders, position.saldo = prepare_orders(
        side=position.current_position.side,
        mode=mode,
        entry_price=entry_price,
        saldo=position.saldo,
        number_of_dca_orders=position.number_of_dca_orders,
        leverage=position.leverage,
        order_quantity_list=position.order_quantity_list,
    )

    position.orders = await send_orders(
        client=client,
        orders=position.orders,
        symbol=position.symbol,
        side=client.SIDE_BUY,
    )

    logger.info("Exiting long position open, opened orders: %s", position.orders)
    return position


async def futures_short_position_open(
    client: binance.AsyncClient,
    position: Position,
    entry_price: float,
    signal: features.Signals,
    number_of_dca_orders: int = 4,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Entering short position open, mode: %s", mode)

    position.current_position = CurrentPosition(side=PositionSide.SHORT)

    position.status = signal

    position.orders, position.saldo = prepare_orders(
        side=position.current_position.side,
        mode=mode,
        entry_price=entry_price,
        saldo=position.saldo,
        number_of_dca_orders=number_of_dca_orders,
        leverage=position.leverage,
        order_quantity_list=position.order_quantity_list,
    )

    position.orders = await send_orders(
        client=client,
        orders=position.orders,
        symbol=position.symbol,
        side=client.SIDE_SELL,
    )

    logger.info("Exiting short position open, opened orders: %s", position.orders)
    return position


#
#
# def calculate_long_position(position: Position, sell_price: float) -> Position:
#     sell_price = round(float(sell_price), 2)
#     net = round((sell_price - position.current_position.price), 2)
#     net_percent = round((sell_price / position.current_position.price - 1), 4)
#     logger.info(
#         "Long closed. Price: %s, quantity: %s, it's: %s USDT and %s percent"
#         % (sell_price, position.current_position.quantity, net, 100 * net_percent)
#     )
#     real_earn = round(position.current_position.quantity * net, 2)
#     position.calculated_saldo = position.saldo + real_earn
#
#     logger.info(
#         "Summary: quantity: %s, leverage: %s, earned: %s, new saldo is: %s"
#         % (
#             position.current_position.quantity,
#             position.leverage,
#             real_earn,
#             position.saldo,
#         )
#     )
#
#     position.status = position.status.FLAT
#     position.current_position = CurrentPosition()
#     position.orders = []
#
#     logger.info("SALDO: %s", position.saldo)
#
#     return position


# def calculate_short_position(buy_price: float, position: Position) -> Position:
#     buy_price = round(float(buy_price), 1)
#
#     net = round((position.current_position.price - buy_price), 2)
#     net_percent = round((position.current_position.price / buy_price - 1), 4)
#     logger.info(
#         "Buy price: %s, it's: %s USDT and %s percent"
#         % (buy_price, net, 100 * net_percent)
#     )
#
#     real_earn = round(position.current_position.quantity * net, 2)
#     position.calculated_saldo = round(position.saldo + real_earn, 2)
#
#     logger.info(
#         "Summary: quantity: %s, leverage: %s, earned: %s, new saldo is: %s"
#         % (
#             position.current_position.quantity,
#             position.leverage,
#             real_earn,
#             position.saldo,
#         )
#     )
#
#     position.status = position.status.FLAT
#     position.current_position = CurrentPosition()
#     position.orders = []
#
#     logger.info("SALDO: %s", position.saldo)
#
#     return position


async def send_market_order(client: binance.AsyncClient, position: Position, side: str):
    resp = None
    try:
        resp = await client.futures_create_order(
            symbol=position.symbol,
            side=side,
            quantity=abs(position.current_position.quantity),
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


async def close_position(client: binance.AsyncClient, position: Position):

    logger.info(
        "Entering position close, trying to Market %s", position.current_position.side
    )

    if position.current_position.take_profit_order is not None:

        await send_market_order(
            client=client,
            position=position,
            side=client.SIDE_BUY
            if position.current_position.side == client.SIDE_SELL
            else client.SIDE_SELL,
        )
        position.current_position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.current_position.take_profit_order,
            symbol=position.symbol,
        )
        logger.info("Cancelled take profit order")

    await cancel_remaining_limit_orders(client, position=position)

    logger.info("Exiting position close")
    return position


async def cancel_remaining_limit_orders(
    client: binance.AsyncClient, position: Position
) -> Position:
    logger.info("Cancelling remaining limit orders")
    for order in position.orders:
        if order.status in [
            client.ORDER_STATUS_PARTIALLY_FILLED,
            client.ORDER_STATUS_NEW,
        ]:
            order.status = await cancel_order(
                client=client, symbol=position.symbol, order=order
            )
            logger.info(
                "Order with order_id: %s should be cancelled and is: %s",
                order.order_id,
                order.status,
            )

    return position


async def update_take_profit_order(
    client: binance.AsyncClient, position: Position, take_profit_order: Optional[Order]
):

    if take_profit_order is not None:
        logger.info(
            "Enter update take profit order: %s",
            position.current_position.take_profit_order.order_id,
        )
        position.current_position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.current_position.take_profit_order,
            symbol=position.symbol,
        )

    position.current_position.target_price = target_price_calculate(
        side=position.current_position.side,
        price=position.current_position.price,
        leverage=position.leverage,
    )

    take_profit_order = Order(
        price=position.current_position.target_price,
        quantity=position.current_position.quantity,
        quantity_stable=round(
            (
                abs(position.current_position.quantity)
                * position.current_position.price
                / position.leverage
            ),
            2,
        ),
    )

    position.current_position.take_profit_order = await send_order(
        client=client,
        symbol=position.symbol,
        side=PositionSide.LONG
        if position.current_position.side == PositionSide.SHORT
        else PositionSide.SHORT,
        order=take_profit_order,
    )

    assert isinstance(position.current_position.take_profit_order, Order)
    logger.info(
        "New take profit buy order send, price: %s, quantity: %s realized QUANT: %s",
        position.current_position.target_price,
        position.current_position.take_profit_order.quantity,
        position.current_position.take_profit_order.realized_quantity,
    )

    return position


async def update_position(
    client: binance.AsyncClient,
    position: Position,
) -> Position:
    logger.info("Entering update position")

    (
        position.current_position.liquidation_price,
        position.current_position.price,
        position.current_position.quantity,
    ) = await position_information(client=client, symbol=position.symbol)

    position = await update_take_profit_order(
        client=client,
        position=position,
        take_profit_order=position.current_position.take_profit_order,
    )

    logger.info("Exiting update position")

    return position
