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
    status: str = binance.client.BaseClient.ORDER_STATUS_NEW


class Position(NamedTuple):
    current_position: Order
    orders: List[Order]
    status: features.Signals


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"


async def futures_long_position_open(
    client: binance.AsyncClient,
    symbol: str,
    saldo: float,
    signal: features.Signals,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Opening long, saldo: %d" % saldo)
    order_quantity_list = lib.order_quantity_list_prepare()
    order_quantity = lib.order_quantity_check(oql=order_quantity_list, saldo=saldo)
    logger.info("Order quantity for new trade: %d" % order_quantity)

    if mode == PositionMode.DCA:
        orders = []
        resp = await client.futures_create_order(
            symbol=symbol,
            order_quantity=order_quantity,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )

        resp = {"price": 100}
        logger.info("Long opened, DCA, resp %s" % resp)
        buy_price = resp["price"]
        current_position = Order(
            price=buy_price, quantity=order_quantity, status=client.ORDER_STATUS_FILLED
        )
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=order_quantity,
            )
            for order in range(number_of_dca_orders)
        ]
        orders.append(current_position)
        orders.append(dca_orders)

        position = Position(
            current_position=current_position, orders=orders, status=signal
        )

    elif mode == PositionMode.FULL:
        # resp = await client.futures_create_order(
        #     symbol=symbol,
        #     order_quantity=(number_of_dca_orders + 1) * order_quantity,
        #     side=client.SIDE_BUY,
        #     type=client.FUTURE_ORDER_TYPE_MARKET,
        # )
        resp = {"price": 100}
        logger.info("Long opened, DCA, resp %s" % resp)
        buy_price = resp["price"]
        current_position = Order(
            price=buy_price,
            quantity=(number_of_dca_orders + 1) * order_quantity,
        )
        dca_orders = []
        position = Position(
            current_position=current_position,
            orders=[current_position],
            status=signal,
        )
        logger.info(
            "Long opened in FULL mode. Price: %d, quantity: %d"
            % (current_position.price, current_position.quantity)
        )
    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )
        position = Position(
            current_position=Order(price=0, quantity=0),
            orders=[],
            status=features.Signals.NULL,
        )

    return position


async def futures_short_position_open(
    client: binance.AsyncClient,
    symbol: str,
    saldo: float,
    signal: features.Signals,
    number_of_dca_orders: int = 3,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    order_quantity_list = lib.order_quantity_list_prepare()
    order_quantity = lib.order_quantity_check(oql=order_quantity_list, saldo=saldo)
    logger.info("Order quantity for new trade: %d" % order_quantity)

    if mode == PositionMode.DCA:
        orders = []
        # resp = await client.futures_create_order(
        #     symbol=symbol,
        #     order_quantity=order_quantity,
        #     side=client.SIDE_SELL,
        #     type=client.FUTURE_ORDER_TYPE_MARKET,
        # )
        resp = {"price": 100}
        logger.info("Short opened, DCA, resp %s" % resp)
        buy_price = resp["price"]
        current_position = Order(price=buy_price, quantity=order_quantity)
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=order_quantity,
            )
            for order in range(number_of_dca_orders)
        ]
        orders.append(current_position)
        orders.append(dca_orders)
        position = Position(
            current_position=current_position, orders=orders, status=signal
        )
    elif mode == PositionMode.FULL:
        # resp = await client.futures_create_order(
        #     symbol=symbol,
        #     order_quantity=(number_of_dca_orders + 1) * order_quantity,
        #     side=client.SIDE_SELL,
        #     type=client.FUTURE_ORDER_TYPE_MARKET,
        # )
        resp = {"price": 100}
        logger.info("Short opened, FULL, resp %s" % resp)
        buy_price = resp["price"]
        current_position = Order(
            price=buy_price,
            quantity=(number_of_dca_orders + 1) * order_quantity,
        )
        logger.info(
            "Short opened in FULL mode. Price: %d, quantity: %d"
            % (current_position.price, current_position.quantity)
        )
        position = Position(
            current_position=current_position,
            orders=[current_position],
            status=signal,
        )
    else:
        logger.info(
            "Something's no yes, you've tried to use PositionMode different than 'DCA' or 'FULL'"
        )
        position = Position(
            current_position=Order(price=0, quantity=0),
            orders=[],
            status=features.Signals.NULL,
        )

    return position


async def futures_long_position_close(client: binance.AsyncClient, symbol: str):

    # resp = await client.futures_create_order(
    #     symbol=symbol,
    #     side=client.SIDE_SELL,
    #     type=client.FUTURE_ORDER_TYPE_MARKET,
    # )
    resp = {"price": 100}
    logger.info("Long closed, resp %s" % resp)


async def futures_short_position_close(client: binance.AsyncClient, symbol: str):

    # resp = await client.futures_create_order(
    #     symbol=symbol,
    #     side=client.SIDE_BUY,
    #     type=client.FUTURE_ORDER_TYPE_MARKET,
    # )
    resp = {"price": 100}
    logger.info("Short closed, resp %s" % resp)
