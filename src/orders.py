import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import List, NamedTuple, Tuple, Optional
import logging
import features
import binance

from binance import exceptions

import lib


logger = logging.getLogger("order")


class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass
class Order:
    price: float
    quantity: float
    order_id: int
    realized_quantity: float = 0
    time_in_force: str = binance.client.BaseClient.TIME_IN_FORCE_GTC
    status: str = binance.client.BaseClient.ORDER_STATUS_NEW


@dataclass()
class CurrentPosition:
    price: float = 0
    quantity: float = 0
    side: PositionSide = PositionSide.FLAT
    liquidation_price: float = 0
    target_price: float = 0
    take_profit_order: Optional[Order] = None


@dataclass
class Position:
    symbol: str
    current_position: CurrentPosition = CurrentPosition()
    orders: List[Order] = field(default_factory=list)
    status: features.Signals = features.Signals.NULL
    saldo: float = 0
    leverage: int = 25


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"


async def send_dca_orders(
    client: binance.AsyncClient,
    side: str,
    dca_orders: List[Order],
    symbol: str,
) -> List[Order]:

    for order in dca_orders:
        resp = await client.futures_create_order(
            symbol=symbol,
            price=order.price,
            quantity=order.quantity,
            side=side,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
        )
        order.order_id = resp["orderId"]
        logger.info(
            "New LIMIT order; Price: %s, quantity: %s, side: %s, order_id: %s"
            % (order.price, order.quantity, side, order.order_id)
        )

    return dca_orders


def liquidation_target_price_calculate(
    side: PositionSide, price: float, leverage: int
) -> Tuple[float, float]:
    if side == "LONG":
        liquidation_price = round((1 - (100 / leverage / 100)) * price, 2)
        target_price = round((1 + (100 / leverage / 100)) * price, 2)
        return liquidation_price, target_price

    if side == "SHORT":
        liquidation_price = round((1 + (100 / leverage / 100)) * price, 2)
        target_price = round((1 - (100 / leverage / 100)) * price, 2)
        return liquidation_price, target_price


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

    btc_price = await client.get_avg_price(symbol=position.symbol)

    if mode == PositionMode.DCA:
        logger.info("Entering DCA mode")
        # prepare orders
        # send orders

        quantity = round(order_quantity / float(btc_price["price"]), 5)
        try:
            resp = await client.futures_create_order(
                symbol=position.symbol,
                quantity=quantity,
                side=client.SIDE_BUY,
                type=client.FUTURE_ORDER_TYPE_MARKET,
                newOrderRespType="RESULT",
            )
            logger.info("Long opened, DCA, resp %s" % resp)
        except exceptions.BinanceAPIException as e:
            logger.info("Tej kurwa co jest: %s" % e)

        buy_price = resp["price"]
        liquidation_price, target_price = liquidation_target_price_calculate(
            side=resp["positionSide"], price=buy_price, leverage=position.leverage
        )

        resp = await client.futures_create_order(
            symbol=position.symbol,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
            price=target_price,
            closePosition=True,
        )

        logger.info("Take profit sell order send, price: %s" % target_price)

        current_position = CurrentPosition(
            price=buy_price,
            quantity=quantity,
            target_price=target_price,
            liquidation_price=liquidation_price,
            side=PositionSide.LONG,
            take_profit_order=Order(
                price=target_price, quantity=quantity, order_id=resp["orderId"]
            ),
        )
        logger.info("Current position %s" % current_position)

        orders = [
            Order(
                price=buy_price,
                quantity=quantity,
                status=client.ORDER_STATUS_FILLED,
                order_id=0,
            )
        ]
        dca_orders = [
            Order(
                price=round((buy_price - (0.005 * (order + 1) * buy_price)), 2),
                quantity=round(
                    order_quantity
                    / (round((buy_price - (0.005 * (order + 1) * buy_price)), 2)),
                    5,
                ),
                order_id=0,
            )
            for order in range(number_of_dca_orders)
        ]
        logger.info("DCA orders created")

        for order in orders:
            logger.info("Order: %s" % order)

        dca_orders = await send_dca_orders(
            client=client,
            dca_orders=dca_orders,
            symbol=position.symbol,
            side=client.SIDE_BUY,
        )

        orders.append(dca_orders)

        logger.info("DCA orders send")
        for order in orders:
            logger.info("Order: %s" % order)

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
        full_order_quantity = (number_of_dca_orders + 1) * order_quantity

        quantity = round(full_order_quantity / float(btc_price["price"]), 5)

        resp = await client.futures_create_order(
            symbol=position.symbol,
            quantity=quantity,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        buy_price = resp["price"]
        logger.info("Long opened, FULL, resp %s" % resp)

        orders.append(
            Order(
                price=buy_price,
                quantity=quantity,
                status=client.ORDER_STATUS_FILLED,
                order_id=0,
            )
        )

        liquidation_price, target_price = liquidation_target_price_calculate(
            side=resp["positionSide"], price=buy_price, leverage=position.leverage
        )

        resp = await client.futures_create_order(
            symbol=position.symbol,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
            price=target_price,
            closePosition=True,
        )

        logger.info("Take profit sell order send, price: %s" % target_price)

        current_position = CurrentPosition(
            price=buy_price,
            quantity=full_order_quantity,
            liquidation_price=liquidation_price,
            target_price=target_price,
            side=PositionSide.LONG,
            take_profit_order=Order(
                price=target_price,
                quantity=full_order_quantity,
                order_id=resp["orderId"],
            ),
        )

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
            current_position=CurrentPosition(
                price=0,
                quantity=0,
                target_price=0,
                liquidation_price=0,
                side=PositionSide.FLAT,
                take_profit_order=Order(price=0, quantity=0, order_id=0),
            ),
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

    btc_price = await client.get_avg_price(symbol=position.symbol)

    if mode == PositionMode.DCA:
        quantity = round(order_quantity / float(btc_price["price"]), 5)
        resp = await client.futures_create_order(
            symbol=position.symbol,
            quantity=quantity,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        sell_price = resp["price"]
        logger.info("Short opened, DCA, resp %s" % resp)

        liquidation_price, target_price = liquidation_target_price_calculate(
            side=resp["positionSide"], price=sell_price, leverage=position.leverage
        )
        resp = await client.futures_create_order(
            symbol=position.symbol,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
            closePosition=True,
            price=target_price,
        )
        logger.info("Take profit buy order send, price: %s" % target_price)

        current_position = CurrentPosition(
            price=sell_price,
            quantity=quantity,
            target_price=target_price,
            liquidation_price=liquidation_price,
            side=PositionSide.SHORT,
            take_profit_order=Order(
                price=sell_price, quantity=quantity, order_id=resp["orderId"]
            ),
        )
        logger.info("Current position %s" % current_position)

        orders = [
            Order(
                price=sell_price,
                quantity=quantity,
                status=client.ORDER_STATUS_FILLED,
                order_id=0,
            )
        ]
        dca_orders = [
            Order(
                price=round((sell_price + (0.005 * (order + 1) * sell_price)), 2),
                quantity=round(
                    order_quantity
                    / (round((sell_price + (0.005 * (order + 1) * sell_price)), 2)),
                    5,
                ),
                order_id=0,
            )
            for order in range(number_of_dca_orders)
        ]
        logger.info("DCA orders created")

        for order in dca_orders:
            logger.info("Order: %s" % order)

        dca_orders = await send_dca_orders(
            client=client,
            dca_orders=dca_orders,
            symbol=position.symbol,
            side=client.SIDE_SELL,
        )
        logger.info("DCA orders send")
        for order in dca_orders:
            logger.info("Order: %s" % order)

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
        full_order_quantity = (number_of_dca_orders + 1) * order_quantity
        quantity = round(full_order_quantity / float(btc_price["price"]), 5)

        resp = await client.futures_create_order(
            symbol=position.symbol,
            quantity=quantity,
            side=client.SIDE_SELL,
            type=client.FUTURE_ORDER_TYPE_MARKET,
        )
        sell_price = resp["price"]
        logger.info("Long opened, FULL, resp %s" % resp)

        orders.append(
            Order(
                price=sell_price,
                quantity=quantity,
                status=client.ORDER_STATUS_FILLED,
                order_id=0,
            )
        )

        liquidation_price, target_price = liquidation_target_price_calculate(
            side=resp["positionSide"], price=sell_price, leverage=position.leverage
        )

        resp = await client.futures_create_order(
            symbol=position.symbol,
            side=client.SIDE_BUY,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
            closePosition=True,
            price=target_price,
        )
        logger.info("Take profit buy order send, price: %s" % target_price)

        current_position = CurrentPosition(
            price=sell_price,
            quantity=quantity,
            liquidation_price=liquidation_price,
            target_price=target_price,
            side=PositionSide.LONG,
            take_profit_order=Order(
                price=sell_price, quantity=quantity, order_id=resp["orderId"]
            ),
        )

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
            current_position=CurrentPosition(
                price=0,
                quantity=0,
                target_price=0,
                liquidation_price=0,
                side=PositionSide.FLAT,
                take_profit_order=Order(price=0, quantity=0, order_id=0),
            ),
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

    logger.info("Cancelling remaining limit orders")
    for order in position.orders:
        if order.status in [
            client.ORDER_STATUS_PARTIALLY_FILLED,
            client.ORDER_STATUS_NEW,
        ]:
            resp = await client.futures_cancel_order(order_id=order.order_id)
            logger.info(
                "Order with order_id: %s should be cancelled and is: %s"
                % (order.order_id, resp["status"])
            )
            position.saldo = position.saldo + (order.quantity - order.realized_quantity)

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

    logger.info("Cancelling remaining limit orders")
    for order in position.orders:
        if order.status in [
            client.ORDER_STATUS_PARTIALLY_FILLED,
            client.ORDER_STATUS_NEW,
        ]:
            resp = await client.futures_cancel_order(order_id=order.order_id)
            logger.info(
                "Order with order_id: %s should be cancelled and is: %s"
                % (order.order_id, resp["status"])
            )
            position.saldo = position.saldo + (order.quantity - order.realized_quantity)

    position.status = position.status.FLAT

    return position


async def update_take_profit_order(
    client: binance.AsyncClient,
    symbol: str,
    take_profit_order: Order,
    price: float,
    order_quantity: float,
    side: PositionSide,
) -> Order:

    resp = await client.futures_cancel_order(order_id=take_profit_order.order_id)

    logger.info(
        "Order with order_id: %s should be cancelled and is: %s"
        % (take_profit_order.order_id, resp["status"])
    )

    resp = await client.futures_create_order(
        symbol=symbol,
        order_quantity=order_quantity,
        side=side,
        type=client.FUTURE_ORDER_TYPE_LIMIT,
        price=price,
    )
    logger.info("New take profit buy order send, price: %s" % price)

    return Order(price=resp["price"], quantity=order_quantity, order_id=resp["orderId"])
