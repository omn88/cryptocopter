from dataclasses import dataclass
from enum import Enum
from typing import Tuple, List
import logging

import binance

import lib


logger = logging.getLogger("order")


@dataclass
class Order:
    price: float
    quantity: float


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"


async def futures_long_position_open(
    client: binance.AsyncClient,
    symbol: str,
    saldo: float,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Tuple[List[Order], Order]:
    order_quantity_list = lib.order_quantity_list_prepare()
    order_quantity = lib.order_quantity_check(oql=order_quantity_list, saldo=saldo)
    logger.info("Order quantity for new trade: %d" % order_quantity)

    if mode == PositionMode.DCA:
        resp = await client.futures_create_order(
            symbol=symbol,
            order_quantity=order_quantity,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        logger.info("Long opened, DCA, resp %s" % resp)
        buy_price = resp["price"]
        position = Order(price=buy_price, quantity=order_quantity)
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=order_quantity,
            )
            for order in range(number_of_dca_orders)
        ]
    elif mode == PositionMode.FULL:
        resp = await client.futures_create_order(
            symbol=symbol,
            order_quantity=(number_of_dca_orders + 1) * order_quantity,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        logger.info("Long opened, DCA, resp %s" % resp)
        buy_price = resp["price"]
        position = Order(
            price=buy_price,
            quantity=(number_of_dca_orders + 1) * order_quantity,
        )
        dca_orders = []
        logger.info(
            "Long opened in FULL mode. Price: %d, quantity: %d"
            % (position.price, position.quantity)
        )
    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )
        dca_orders = []
        position = Order(price=0, quantity=0)

    return dca_orders, position


async def futures_short_position_open(
    client: binance.AsyncClient,
    symbol: str,
    saldo: float,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Tuple[List[Order], Order]:
    order_quantity_list = lib.order_quantity_list_prepare()
    order_quantity = lib.order_quantity_check(oql=order_quantity_list, saldo=saldo)
    logger.info("Order quantity for new trade: %d" % order_quantity)

    if mode == PositionMode.DCA:
        resp = await client.futures_create_order(
            symbol=symbol,
            order_quantity=order_quantity,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        logger.info("Short opened, DCA, resp %s" % resp)
        buy_price = resp["price"]
        position = Order(price=buy_price, quantity=order_quantity)
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=order_quantity,
            )
            for order in range(number_of_dca_orders)
        ]
    elif mode == PositionMode.FULL:
        resp = await client.futures_create_order(
            symbol=symbol,
            order_quantity=(number_of_dca_orders + 1) * order_quantity,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        logger.info("Short opened, FULL, resp %s" % resp)
        buy_price = resp["price"]
        position = Order(
            price=buy_price,
            quantity=(number_of_dca_orders + 1) * order_quantity,
        )
        dca_orders = []
        logger.info(
            "Short opened in FULL mode. Price: %d, quantity: %d"
            % (position.price, position.quantity)
        )
    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )
        dca_orders = []
        position = Order(price=0, quantity=0)

    return dca_orders, position


async def futures_long_position_close(client: binance.AsyncClient, symbol: str):

    resp = await client.futures_create_order(
        symbol=symbol,
        side=client.SIDE_SELL,
        type=client.FUTURE_ORDER_TYPE_MARKET,
    )
    logger.info("Long closed, resp %s" % resp)


async def futures_short_position_close(client: binance.AsyncClient, symbol: str):

    resp = await client.futures_create_order(
        symbol=symbol,
        side=client.SIDE_BUY,
        type=client.FUTURE_ORDER_TYPE_MARKET,
    )
    logger.info("Short closed, resp %s" % resp)
