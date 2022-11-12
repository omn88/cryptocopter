import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import List, NamedTuple
import logging
import features
import binance

import lib


logger = logging.getLogger("order")


@dataclass
class Order:
    price: float
    quantity: float
    order_id: int
    time_in_force: str = binance.client.BaseClient.TIME_IN_FORCE_GTC
    status: str = binance.client.BaseClient.ORDER_STATUS_NEW


class Position(NamedTuple):
    symbol: str
    current_position: Order
    orders: List[Order]
    status: features.Signals
    saldo: float
    leverage: int = 25


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"


async def send_dca_orders(
    client: binance.AsyncClient,
    side: str,
    dca_orders: List[Order],
    symbol: str,
    order_quantity: float,
) -> List[Order]:

    for order in dca_orders:
        resp = await client.futures_create_order(
            symbol=symbol,
            price=order.price,
            order_quantity=order_quantity,
            side=side,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
        )
        order.order_id = resp["orderId"]
        logger.info(
            "New LIMIT order; Price: %s, quantity: %s, side: %s, order_id: %s"
            % (order.price, order_quantity, side, order.order_id)
        )

    return dca_orders


async def futures_long_position_open(
    client: binance.AsyncClient,
    position: Position,
    signal: features.Signals,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Opening long, saldo: %d" % position.saldo)
    order_quantity_list = lib.order_quantity_list_prepare()
    order_quantity = lib.order_quantity_check(
        oql=order_quantity_list, saldo=position.saldo
    )
    logger.info("Order quantity for new trade: %d" % order_quantity)

    if mode == PositionMode.DCA:
        orders = []
        resp = await client.futures_create_order(
            symbol=position.symbol,
            order_quantity=order_quantity,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )

        buy_price = resp["price"]
        order_id = resp["order_id"]
        logger.info("Long opened, DCA, resp %s" % resp)
        current_position = Order(
            price=buy_price,
            quantity=order_quantity,
            status=client.ORDER_STATUS_FILLED,
            order_id=order_id,
        )
        logger.info("Current position %s" % current_position)
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=order_quantity,
                order_id=0,
            )
            for order in range(number_of_dca_orders)
        ]
        logger.info("DCA orders created")

        for order in dca_orders:
            logger.info("Order: %s" % order)

        dca_orders = await asyncio.gather(
            *[
                send_dca_orders(
                    client=client,
                    dca_orders=dca_orders,
                    symbol=position.symbol,
                    order_quantity=order_quantity,
                    side=client.SIDE_BUY,
                )
            ]
        )

        logger.info("DCA orders send")
        for order in dca_orders:
            logger.info("Order: %s" % order)

        orders.append(current_position)
        orders.append(dca_orders)

        position.saldo = position.saldo - (number_of_dca_orders + 1) * order_quantity

        position = Position(
            current_position=current_position,
            orders=orders,
            status=signal,
            saldo=position.saldo,
            symbol=position.symbol,
        )

        logger.info("Position: %s" % position)

    elif mode == PositionMode.FULL:
        orders = []
        resp = await client.futures_create_order(
            symbol=position.symbol,
            order_quantity=(number_of_dca_orders + 1) * order_quantity,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        buy_price = resp["price"]
        order_id = resp["order_id"]
        logger.info("Long opened, FULL, resp %s" % resp)
        current_position = Order(
            price=buy_price,
            quantity=(number_of_dca_orders + 1) * order_quantity,
            status=client.ORDER_STATUS_FILLED,
            order_id=order_id,
        )

        orders.append(current_position)

        position.saldo = position.saldo - (number_of_dca_orders + 1) * order_quantity

        position = Position(
            current_position=current_position,
            orders=orders,
            status=signal,
            saldo=position.saldo,
            symbol=position.symbol,
        )
        logger.info("Position: %s" % position)

        logger.info(
            "Long opened in FULL mode. Price: %d, quantity: %d"
            % (current_position.price, current_position.quantity)
        )
    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )
        position = Position(
            current_position=Order(price=0, quantity=0, order_id=0),
            orders=[],
            status=features.Signals.NULL,
            saldo=position.saldo,
            symbol=position.symbol,
        )

    return position


async def futures_short_position_open(
    client: binance.AsyncClient,
    position: Position,
    signal: features.Signals,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Opening long, saldo: %d" % position.saldo)
    order_quantity_list = lib.order_quantity_list_prepare()
    order_quantity = lib.order_quantity_check(
        oql=order_quantity_list, saldo=position.saldo
    )
    logger.info("Order quantity for new trade: %d" % order_quantity)

    if mode == PositionMode.DCA:
        orders = []
        resp = await client.futures_create_order(
            symbol=position.symbol,
            order_quantity=order_quantity,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )

        sell_price = resp["price"]
        order_id = resp["order_id"]
        status = resp["status"]
        logger.info("Short opened, DCA, resp %s" % resp)
        current_position = Order(
            price=sell_price,
            quantity=order_quantity,
            status=status,
            order_id=order_id,
        )
        logger.info("Current position %s" % current_position)
        dca_orders = [
            Order(
                price=round((sell_price + (0.005 * (order + 1) * sell_price)), 2),
                quantity=order_quantity,
                order_id=0,
            )
            for order in range(number_of_dca_orders)
        ]
        logger.info("DCA orders created")

        for order in dca_orders:
            logger.info("Order: %s" % order)

        dca_orders = await asyncio.gather(
            *[
                send_dca_orders(
                    client=client,
                    dca_orders=dca_orders,
                    symbol=position.symbol,
                    order_quantity=order_quantity,
                    side=client.SIDE_SELL,
                )
            ]
        )

        logger.info("DCA orders send")
        for order in dca_orders:
            logger.info("Order: %s" % order)

        orders.append(current_position)
        orders.append(dca_orders)

        position.saldo = position.saldo - (number_of_dca_orders + 1) * order_quantity

        position = Position(
            current_position=current_position,
            orders=orders,
            status=signal,
            saldo=position.saldo,
            symbol=position.symbol,
        )

        logger.info("Position: %s" % position)

    elif mode == PositionMode.FULL:
        orders = []
        resp = await client.futures_create_order(
            symbol=position.symbol,
            order_quantity=(number_of_dca_orders + 1) * order_quantity,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        sell_price = resp["price"]
        order_id = resp["order_id"]
        status = resp["status"]
        logger.info("Short opened, FULL, resp %s" % resp)
        current_position = Order(
            price=sell_price,
            quantity=(number_of_dca_orders + 1) * order_quantity,
            status=status,
            order_id=order_id,
        )

        orders.append(current_position)

        position.saldo = position.saldo - (number_of_dca_orders + 1) * order_quantity

        position = Position(
            current_position=current_position,
            orders=orders,
            status=signal,
            saldo=position.saldo,
            symbol=position.symbol,
        )
        logger.info("Position: %s" % position)

        logger.info(
            "Short opened in FULL mode. Price: %d, quantity: %d"
            % (current_position.price, current_position.quantity)
        )
    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )
        position = Position(
            current_position=Order(price=0, quantity=0, order_id=0),
            orders=[],
            status=features.Signals.NULL,
            saldo=position.saldo,
            symbol=position.symbol,
        )

    return position


async def futures_long_position_close(client: binance.AsyncClient, position: Position):

    resp = await client.futures_create_order(
        symbol=position.symbol,
        side=client.SIDE_SELL,
        type=client.FUTURE_ORDER_TYPE_MARKET,
        close_position=True,
    )

    sell_price = resp["price"]

    net = round((sell_price - position.current_position.price), 2)
    net_percent = round((sell_price / position.current_position.price - 1), 4)
    logger.info(
        "Long closed. Price: %s, it's: %s USDT and %s percent"
        % (sell_price, net, 100 * net_percent)
    )

    real_earn = round(
        (position.current_position.quantity * position.leverage * net_percent), 2
    )
    position.saldo = round(position.saldo + real_earn, 2)

    logger.info(
        "Summary: quantity: %s, leverage: %d, earned: %d, new saldo is: %d"
        % position.current_position.quantity,
        position.leverage,
        real_earn,
        position.saldo,
    )

    position.status = position.status.FLAT

    return position


async def futures_short_position_close(
    client: binance.AsyncClient, position: Position
) -> Position:

    resp = await client.futures_create_order(
        symbol=position.symbol,
        side=client.SIDE_BUY,
        type=client.FUTURE_ORDER_TYPE_MARKET,
        close_position=True,
    )
    logger.info("Short closed, resp %s" % resp)

    buy_price = resp["price"]

    net = round((position.current_position.price - buy_price), 2)
    net_percent = round((position.current_position.price / buy_price - 1), 4)
    logger.info(
        "Short closed. Price: %s, it's: %s USDT and %s percent"
        % (buy_price, net, 100 * net_percent)
    )

    real_earn = round(
        (position.current_position.quantity * position.leverage * net_percent), 2
    )
    position.saldo = round(position.saldo + real_earn, 2)

    logger.info(
        "Summary: quantity: %s, leverage: %d, earned: %d, new saldo is: %d"
        % position.current_position.quantity,
        position.leverage,
        real_earn,
        position.saldo,
    )

    position.status = position.status.FLAT

    return position
