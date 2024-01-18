import asyncio
from typing import List, Optional, Tuple
import logging
from binance.enums import (
    FUTURE_ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_NEW,
    FUTURE_ORDER_TYPE_MARKET,
)
from binance.exceptions import (
    BinanceAPIException,
    BinanceOrderException,
    BinanceRequestException,
)

from src.common.common import convert_time
from src.common.constants import LEVERAGE, DCA_SPAN, LOSSES_PER_LEVEL
import pandas

from src.common.identifiers import (
    Order,
    PositionSide,
    PositionMode,
    Position,
    BinanceClient,
)
from src.gui.identifiers import OrderData

MAX_RETRIES = 10

logger = logging.getLogger("orders")


def order_quantity_list_prepare(
    number_of_orders: int,
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
    oql["sum_of_all_losses"] = oql.order_value * number_of_orders * LOSSES_PER_LEVEL
    oql["threshold"] = oql.sum_of_all_losses + oql.sum_of_all_losses.shift(1)
    oql.at[oql.index[0], "threshold"] = oql.at[oql.index[0], "sum_of_all_losses"]

    # logger.debug("Order quantity list: \n%s", oql)

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


async def send_order(
    client: BinanceClient, side: str, order: Order, ui_queue: asyncio.Queue, symbol: str
) -> Order:
    last_exception = None

    for _ in range(MAX_RETRIES):
        try:
            resp = await client.futures_create_order(
                symbol=symbol,
                price=round(order.price, 1),
                quantity=round(abs(order.quantity), 3),
                side=side,
                type=FUTURE_ORDER_TYPE_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                timestamp=int(await client.get_adjusted_time() * 1000),
            )
        except (
            BinanceAPIException,
            BinanceOrderException,
            BinanceRequestException,
        ) as e:
            last_exception = e
            logger.error("Failed to create order due to %s: %s", type(e).__name__, e)
            await asyncio.sleep(1)  # wait for a second before retrying
            continue
        else:
            logger.info("RESP: %s", resp)
            order.order_id = int(resp["orderId"])
            order.status = resp["status"]
            logger.info("New: %s", order)
            order.open_time = convert_time(resp["updateTime"])

            await ui_queue.put(
                OrderData(
                    order_id=order.order_id,
                    open_time=order.open_time,
                    symbol=symbol,
                    order_type=order.order_type,
                    side=side,
                    price=order.price,
                    quantity=order.quantity,
                    realized_quantity=order.realized_quantity,
                    status=order.status,
                )
            )

            return order

    assert last_exception is not None
    raise last_exception


async def cancel_order(
    client: BinanceClient, order: Order, ui_queue: asyncio.Queue, side: str, symbol: str
):
    logger.info("Enter cancel order: %s, symbol: %s", order.order_id, symbol)
    last_exception = None

    for _ in range(MAX_RETRIES):
        try:
            resp = await client.futures_cancel_order(
                symbol=symbol,
                orderId=order.order_id,
                timestamp=int(await client.get_adjusted_time() * 1000),
            )
            order.status = resp["status"]
            await ui_queue.put(
                OrderData(
                    order_id=order.order_id,
                    open_time=order.open_time,
                    symbol=symbol,
                    order_type=order.order_type,
                    side=side,
                    price=order.price,
                    quantity=order.quantity,
                    realized_quantity=order.realized_quantity,
                    status=order.status,
                )
            )
        except (
            BinanceAPIException,
            BinanceOrderException,
            BinanceRequestException,
        ) as e:
            last_exception = e
            logger.error(
                "Failed to cancel order order due to %s: %s", type(e).__name__, e
            )
            await asyncio.sleep(1)  # wait for a second before retrying
            continue

        logger.info("Exit cancel order")
        return resp["status"]

    # if we've exhausted all retries and still have an exception, raise it
    if last_exception is not None:
        raise last_exception


async def send_orders(
    client: BinanceClient,
    side: str,
    orders: List[Order],
    ui_queue: asyncio.Queue,
    symbol: str,
) -> List[Order]:
    """Send a list of orders concurrently.

    Args:
        client: A `BinanceClient` object.
        side: The side of the orders (either `PositionSide.BUY` or `PositionSide.SELL`).
        orders: A list of `Order` objects to send.

    Returns:
        A list of `Order` objects with updated order IDs and statuses.
    """
    tasks = []
    for order in orders:
        task = asyncio.create_task(
            send_order(
                client=client, side=side, order=order, ui_queue=ui_queue, symbol=symbol
            )
        )
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
    number_of_orders: int,
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
            * number_of_orders
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
            * number_of_orders
            / (round((entry_price + (DCA_SPAN * order * entry_price)), 2)),
            3,
        )


def prepare_orders(
    position: Position,
    mode: PositionMode,
    entry_price: float,
    balance: float,
    number_of_orders: int,
    order_quantity_list: pandas.DataFrame,
) -> Position:
    logger.info("Entering prepare orders")

    order_quantity_stable, order_level = order_quantity_check(
        oql=order_quantity_list, balance=balance
    )
    position.artifacts.order_quantity_stable = order_quantity_stable
    position.artifacts.order_level = order_level
    position.artifacts.max_position = order_quantity_stable * float(number_of_orders)
    position.artifacts.side = position.side
    position.artifacts.mode = mode
    position.artifacts.leverage = LEVERAGE

    logger.info(
        "Balance: %s, single order value: %s USDT, number of dca orders: %s, dca span: %s",
        balance,
        order_quantity_stable,
        number_of_orders,
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
                number_of_orders=number_of_orders,
            ),
            order_id=0,
            quantity_stable=order_quantity_stable,
        )
        for order in range(number_of_orders)
    ]

    logger.info("Exiting prepare orders")
    return position


async def cancel_take_profit_order(
    client: BinanceClient,
    take_profit_order: Order,
    side: str,
    ui_queue: asyncio.Queue,
    symbol: str,
) -> str:
    take_profit_order.status = await cancel_order(
        client=client,
        order=take_profit_order,
        side=side,
        ui_queue=ui_queue,
        symbol=symbol,
    )
    logger.info(
        "Take profit order: %s, status: %s",
        take_profit_order.order_id,
        take_profit_order.status,
    )

    return take_profit_order.status


async def send_market_order(
    client: BinanceClient, position: Position, side: str, symbol: str
) -> Position:
    order_type = FUTURE_ORDER_TYPE_MARKET
    quantity = abs(position.quantity)

    last_exception = None

    for _ in range(MAX_RETRIES):
        try:
            resp = await client.futures_create_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                type=order_type,
                timestamp=int(await client.get_adjusted_time() * 1000),
            )
        except (
            BinanceAPIException,
            BinanceOrderException,
            BinanceRequestException,
        ) as e:
            last_exception = e
            logger.error(
                "Failed to send market order due to %s: %s", type(e).__name__, e
            )
            await asyncio.sleep(1)  # wait for a second before retrying
            continue
        else:
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

    assert last_exception is not None
    raise last_exception


async def cancel_remaining_limit_orders(
    client: BinanceClient, position: Position, ui_queue: asyncio.Queue, symbol: str
) -> Tuple[Position, bool]:
    logger.info("Cancelling remaining limit orders")
    assert position.orders is not None
    new_orders_count = 0
    cancelled_orders_count = 0
    for order in position.orders:
        if order.status == ORDER_STATUS_PARTIALLY_FILLED:
            order.status = await cancel_order(
                client=client,
                order=order,
                ui_queue=ui_queue,
                side=position.side,
                symbol=symbol,
            )
            logger.info("Cancelled partially filled order_id: %s", order.order_id)
            cancelled_orders_count += 1
        elif order.status == ORDER_STATUS_NEW:
            new_orders_count += 1
            order.status = await cancel_order(
                client=client,
                order=order,
                ui_queue=ui_queue,
                side=position.side,
                symbol=symbol,
            )
            logger.info("Cancelled new order_id: %s", order.order_id)
            cancelled_orders_count += 1

    position_opened = new_orders_count != len(position.orders)

    return position, position_opened
