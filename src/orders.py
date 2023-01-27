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


@dataclass
class Position:
    symbol: str
    current_position: CurrentPosition = CurrentPosition()
    orders: List[Order] = field(default_factory=list)
    status: features.Signals = features.Signals.FLAT
    saldo: float = 0
    leverage: int = 25

    def __repr__(self) -> str:
        return (
            f"Position(symbol={self.symbol}, current_position={self.current_position}, "
            f"orders={self.orders}, status={self.status}, saldo={self.saldo}, leverage={self.leverage})"
        )


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"


def order_quantity_list_prepare(
    number_of_dca_orders: int = 3,
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
    oql["sum_of_all_losses"] = (
        oql.order_value * (number_of_dca_orders + 1) * losses_per_level
    )
    oql["threshold"] = oql.sum_of_all_losses + oql.sum_of_all_losses.shift(1)
    # oql.threshold.iloc[0] = oql.sum_of_all_losses.iloc[0]
    oql.at[oql.index[0], "threshold"] = oql.at[oql.index[0], "sum_of_all_losses"]

    logger.debug("Order quantity list: \n%s", oql)

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


def target_depo_price_calculate(
    side: str, price: float, leverage: int
) -> Tuple[float, float]:
    if side == "LONG":
        depo_price = round((1 - (100 / leverage / 100)) * price, 2)
        target_price = round((1 + (100 / leverage / 100)) * price, 2)
        return target_price, depo_price

    if side == "SHORT":
        target_price = round((1 - (100 / leverage / 100)) * price, 2)
        depo_price = round((1 + (100 / leverage / 100)) * price, 2)
        return target_price, depo_price


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
        "New LIMIT order, Price: %s, quantity: %s, side: %s, order_id: %s, status: %s"
        % (order.price, order.quantity, side, order.order_id, order.status)
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
            f"Order status for order {order.order_id} was not set to cancelled. Got: {resp['status']}"
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


def prepare_orders(
    side: str,
    mode: PositionMode,
    entry_price: float,
    saldo: float,
    number_of_dca_orders: int,
    leverage: int,
    dca_span: float = 0.005,
) -> Tuple[List[Order], float]:
    logger.info("Entering prepare orders")

    orders = []
    order_quantity_list = order_quantity_list_prepare()
    order_quantity = order_quantity_check(oql=order_quantity_list, saldo=saldo)
    logger.info("Order quantity: %s", order_quantity)

    if side == PositionSide.LONG:
        if mode == PositionMode.DCA:
            orders = [
                Order(
                    price=round((entry_price - (dca_span * order * entry_price)), 1),
                    quantity=round(
                        leverage
                        * order_quantity
                        / (round((entry_price - (dca_span * order * entry_price)), 2)),
                        3,
                    ),
                    order_id=0,
                    quantity_stable=order_quantity,
                )
                for order in range(number_of_dca_orders + 1)
            ]
            logger.info("DCA orders created")

            for order in orders:
                logger.info("Order: %s" % order)

        elif mode == PositionMode.FULL:
            orders = [
                Order(
                    price=round((entry_price - (dca_span * order * entry_price)), 1),
                    quantity=round(
                        leverage
                        * (order_quantity * (number_of_dca_orders + 1))
                        / (round((entry_price - (dca_span * order * entry_price)), 2)),
                        3,
                    ),
                    order_id=0,
                    quantity_stable=order_quantity,
                )
                for order in range(1)
            ]
            logger.info("FULL order created")

            for order in orders:
                logger.info("Order: %s" % order)

    elif side == PositionSide.SHORT:
        if mode == PositionMode.DCA:
            orders = [
                Order(
                    price=round((entry_price + (dca_span * order * entry_price)), 1),
                    quantity=round(
                        leverage
                        * order_quantity
                        / (round((entry_price + (dca_span * order * entry_price)), 2)),
                        3,
                    ),
                    order_id=0,
                    quantity_stable=order_quantity,
                )
                for order in range(number_of_dca_orders + 1)
            ]
            logger.info("DCA orders created")

            for order in orders:
                logger.info("Order: %s" % order)
        elif mode == PositionMode.FULL:
            orders = [
                Order(
                    price=round((entry_price + (dca_span * order * entry_price)), 1),
                    quantity=round(
                        leverage
                        * order_quantity
                        / (round((entry_price + (dca_span * order * entry_price)), 2)),
                        3,
                    ),
                    order_id=0,
                    quantity_stable=order_quantity,
                )
                for order in range(1)
            ]
            logger.info("FULL order created")

            for order in orders:
                logger.info("Order: %s" % order)

    logger.info("Exiting prepare orders")
    return orders, saldo


async def futures_long_position_open(
    client: binance.AsyncClient,
    signal: features.Signals,
    position: Position,
    entry_price: float,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Entering long position open")
    position.current_position = CurrentPosition(side=PositionSide.LONG)

    if mode == PositionMode.DCA:
        logger.info("Entering mode: %s" % mode)
        position.status = signal

        position.orders, position.saldo = prepare_orders(
            side=position.current_position.side,
            mode=mode,
            entry_price=entry_price,
            saldo=position.saldo,
            number_of_dca_orders=number_of_dca_orders,
            leverage=position.leverage,
        )

        position.orders = await send_orders(
            client=client,
            orders=position.orders,
            symbol=position.symbol,
            side=client.SIDE_BUY,
        )

        logger.info("Position: %s" % position)

    elif mode == PositionMode.FULL:
        logger.info("Entering mode: %s" % mode)
        position.status = signal

        position.orders, position.saldo = prepare_orders(
            side=position.current_position.side,
            mode=mode,
            entry_price=entry_price,
            saldo=position.saldo,
            number_of_dca_orders=number_of_dca_orders,
            leverage=position.leverage,
        )

        position.orders = await send_orders(
            client=client,
            orders=position.orders,
            symbol=position.symbol,
            side=client.SIDE_BUY,
        )

        logger.info("Position: %s" % position)

    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )

    logger.info("Exiting long position open")
    return position


async def futures_short_position_open(
    client: binance.AsyncClient,
    position: Position,
    entry_price: float,
    signal: features.Signals,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Entering short position open")

    position.current_position = CurrentPosition(side=PositionSide.SHORT)

    # ToDo: Assert no order is opened

    if mode == PositionMode.DCA:
        logger.info("Entering mode: %s" % mode)
        position.status = signal

        position.orders, position.saldo = prepare_orders(
            side=position.current_position.side,
            mode=mode,
            entry_price=entry_price,
            saldo=position.saldo,
            number_of_dca_orders=number_of_dca_orders,
            leverage=position.leverage,
        )

        position.orders = await send_orders(
            client=client,
            orders=position.orders,
            symbol=position.symbol,
            side=client.SIDE_SELL,
        )

        logger.info("Position: %s" % position)

    elif mode == PositionMode.FULL:
        logger.info("Entering mode: %s" % mode)
        position.status = signal

        position.orders, position.saldo = prepare_orders(
            side=position.current_position.side,
            mode=mode,
            entry_price=entry_price,
            saldo=position.saldo,
            number_of_dca_orders=number_of_dca_orders,
            leverage=position.leverage,
        )

        position.orders = await send_orders(
            client=client,
            orders=position.orders,
            symbol=position.symbol,
            side=client.SIDE_SELL,
        )

        logger.info("Position: %s" % position)
    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )

    logger.info("Exiting short position open")
    return position


async def futures_long_position_close(
    client: binance.AsyncClient, position: Position
) -> Position:
    logger.info("Entering long position close")

    # ToDo: what dafuq. Check current position price and quantity
    if any(
        order.status
        in [
            binance.AsyncClient.ORDER_STATUS_FILLED,
            binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED,
        ]
        for order in position.orders
    ):
        logger.info("Trying to market sell")
        resp = None
        try:
            resp = await client.futures_create_order(
                symbol=position.symbol,
                side=client.SIDE_SELL,
                quantity=abs(position.current_position.quantity),
                type=client.FUTURE_ORDER_TYPE_MARKET,
                close_position=True,
            )
        except BinanceAPIException as exception:
            logger.info("exception: %s", exception)

        sell_price = round(float(resp["price"]), 1)
        net = round((sell_price - position.current_position.price), 2)
        net_percent = round((sell_price / position.current_position.price - 1), 4)
        logger.info(
            "Long closed. Price: %s, quantity: %s, it's: %s USDT and %s percent"
            % (sell_price, position.current_position.quantity, net, 100 * net_percent)
        )
        real_earn = round(position.current_position.quantity * net, 2)
        position.saldo = position.saldo + real_earn

        logger.info(
            "Summary: quantity: %s, leverage: %s, earned: %s, new saldo is: %s"
            % (
                position.current_position.quantity,
                position.leverage,
                real_earn,
                position.saldo,
            )
        )

        logger.info("Cancelling take profit order")
        position.current_position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.current_position.take_profit_order,
            symbol=position.symbol,
        )
        logger.info("Cancelled take profit order")

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
                "Order with order_id: %s should be cancelled and is: %s"
                % (order.order_id, order.status)
            )

    position.status = position.status.FLAT

    position.current_position = CurrentPosition()

    position.orders = []

    logger.info("SALDO: %s" % position.saldo)

    logger.info("Exiting long position close")
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
                "Order with order_id: %s should be cancelled and is: %s"
                % (order.order_id, order.status)
            )

    return position


async def futures_short_position_close(
    client: binance.AsyncClient, position: Position
) -> Position:
    logger.info("Entering short position close")

    if any(
        order.status == binance.client.BaseClient.ORDER_STATUS_FILLED
        for order in position.orders
    ):

        resp = await client.futures_create_order(
            symbol=position.symbol,
            side=client.SIDE_BUY,
            quantity=abs(position.current_position.quantity),
            type=client.FUTURE_ORDER_TYPE_MARKET,
            close_position=True,
        )
        logger.info("Short closed, resp %s" % resp)

        buy_price = round(float(resp["price"]), 1)

        net = round((position.current_position.price - buy_price), 2)
        net_percent = round((position.current_position.price / buy_price - 1), 4)
        logger.info(
            "Buy price: %s, it's: %s USDT and %s percent"
            % (buy_price, net, 100 * net_percent)
        )

        real_earn = round(position.current_position.quantity * net, 2)
        position.saldo = round(position.saldo + real_earn, 2)

        logger.info(
            "Summary: quantity: %s, leverage: %s, earned: %s, new saldo is: %s"
            % (
                position.current_position.quantity,
                position.leverage,
                real_earn,
                position.saldo,
            )
        )

        logger.info("Cancelling take profit order")
        position.current_position.take_profit_order.status = await cancel_order(
            client=client,
            symbol=position.symbol,
            order=position.current_position.take_profit_order,
        )

    position = await cancel_remaining_limit_orders(client=client, position=position)

    position.status = position.status.FLAT

    position.current_position = CurrentPosition()
    position.orders = []
    logger.info("Exiting short position close")
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
