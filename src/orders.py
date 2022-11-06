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
    saldo: float,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Tuple[List[Order], Order]:
    order_quantity_list = lib.order_quantity_list_prepare()
    order_quantity = lib.order_quantity_check(oql=order_quantity_list, saldo=saldo)
    logger.info("Order quantity for new trade: %d" % order_quantity)

    if mode == PositionMode.DCA:
        await client.futures_create_order()
        logger.info("Long opened at price %s" % buy_price)
        position = Order(price=buy_price, quantity=order_quantity)
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=order_quantity,
            )
            for order in range(number_of_dca_orders)
        ]
    elif mode == PositionMode.FULL:
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
