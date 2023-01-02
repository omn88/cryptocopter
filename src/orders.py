import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Tuple, Optional
import logging
import binance
from src import features
import pandas

logger = logging.getLogger("orders")


class PositionSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass
class Order:
    price: float
    quantity: float
    quantity_stable: float = 0
    order_id: int = 0
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
    status: features.Signals = features.Signals.FLAT
    saldo: float = 0
    leverage: int = 25


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

    return oql


def order_quantity_check(oql: pandas.DataFrame, saldo: float) -> float:
    index_list = []

    [index_list.append(thrshld) for thrshld in oql.threshold if saldo > thrshld]

    order_quantity = (
        oql.order_value[len(index_list) - 1]
        if len(index_list) > 0
        else oql.order_value[0]
    )

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
    client: binance.AsyncClient, symbol: str, side: PositionSide, order: Order
):
    try:
        resp = await client.futures_create_order(
            symbol=symbol,
            price=order.price,
            quantity=order.quantity,
            side=side,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
            timeInForce=client.TIME_IN_FORCE_GTC,
        )
        order.order_id = resp["orderId"]
        order.status = resp["status"]
        logger.info(
            "New LIMIT order; Price: %s, quantity: %s, side: %s, order_id: %s, status: %s"
            % (order.price, order.quantity, side, order.order_id, order.status)
        )
    except Exception as e:
        logger.info(e)


async def send_orders(
    client: binance.AsyncClient,
    side: PositionSide,
    orders: List[Order],
    symbol: str,
) -> List[Order]:
    logger.info("Entering send orders")

    await asyncio.gather(
        *[
            send_order(client=client, symbol=symbol, side=side, order=order)
            for order in orders
        ]
    )

    return orders


def liquidation_target_price_calculate(
    side: PositionSide, price: float, leverage: int
) -> Tuple[float, float]:
    logger.info("Entering liquidation target price calculate")
    if side == PositionSide.LONG:
        liquidation_price = round((1 - (100 / leverage / 100)) * price, 2)
        target_price = round((1 + (100 / leverage / 100)) * price, 2)
        logger.info(
            "position side: %s, liquidation: %s, target: %s"
            % (side, liquidation_price, target_price)
        )
        return liquidation_price, target_price

    if side == PositionSide.SHORT:
        liquidation_price = round((1 + (100 / leverage / 100)) * price, 2)
        target_price = round((1 - (100 / leverage / 100)) * price, 2)
        logger.info(
            "position side: %s, liquidation: %s, target: %s"
            % (side, liquidation_price, target_price)
        )
        return liquidation_price, target_price


def prepare_orders(
    side: PositionSide,
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
    logger.info("Order quantity: %d" % order_quantity)

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
        logger.info("Before Send Orders")
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

    if any(
        order.status
        in [
            binance.AsyncClient.ORDER_STATUS_FILLED,
            binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED,
        ]
        for order in position.orders
    ):

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
        resp = await client.futures_cancel_order(
            order_id=position.current_position.take_profit_order.order_id
        )
        assert resp["status"] == binance.AsyncClient.ORDER_STATUS_CANCELED
        logger.info("Cancelled take profit order")

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

    position.status = position.status.FLAT

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
            resp = await client.futures_cancel_order(order_id=order.order_id)
            logger.info(
                "Order with order_id: %s should be cancelled and is: %s"
                % (order.order_id, resp["status"])
            )
            order.status = resp["status"]

            logger.info("Status: %s, saldo: %s" % (order.status, position.saldo))

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
            type=client.FUTURE_ORDER_TYPE_MARKET,
            close_position=True,
        )
        logger.info("Short closed, resp %s" % resp)

        buy_price = resp["price"]

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
        resp = await client.futures_cancel_order(
            order_id=position.current_position.take_profit_order.order_id
        )
        assert resp["status"] == binance.AsyncClient.ORDER_STATUS_CANCELED

    position = await cancel_remaining_limit_orders(client=client, position=position)

    position.status = position.status.FLAT

    logger.info("Exiting short position close")
    return position


async def update_position(
    client: binance.AsyncClient,
    symbol: str,
    position: Position,
    price: float,
    order_quantity: float,
    leverage: int,
) -> CurrentPosition:
    logger.info("Entering handle filled order")
    current_position = position.current_position
    tpo = current_position.take_profit_order

    if tpo is not None:
        logger.info(
            "Take profit order is not none, so cancelling order: %s" % tpo.order_id
        )
        resp = await client.futures_cancel_order(order_id=tpo.order_id)
        assert resp["status"] == client.ORDER_STATUS_CANCELED

        total_value = 0
        total_quantity = 0

        for order in position.orders:
            if order.status in [
                binance.AsyncClient.ORDER_STATUS_FILLED,
                binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED,
            ]:
                total_quantity += order.realized_quantity
                total_value += order.realized_quantity * order.price

        new_price = round(total_value / total_quantity, 2)

        (
            current_position.liquidation_price,
            current_position.target_price,
        ) = liquidation_target_price_calculate(
            side=current_position.side, price=new_price, leverage=leverage
        )

        new_quantity = current_position.quantity + order_quantity

        resp = await client.futures_create_order(
            symbol=symbol,
            order_quantity=new_quantity,
            side=current_position.side,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
            price=current_position.target_price,
        )
        logger.info(
            "New take profit buy order send, price: %s, quantity: %s"
            % (current_position.target_price, new_quantity)
        )

        current_position.price = new_price
        current_position.quantity = new_quantity

    else:
        logger.info("No take profit order, thus creating first now")

        (
            current_position.liquidation_price,
            current_position.target_price,
        ) = liquidation_target_price_calculate(
            side=current_position.side, price=price, leverage=leverage
        )

        resp = await client.futures_create_order(
            symbol=symbol,
            order_quantity=order_quantity,
            side=current_position.side,
            type=client.FUTURE_ORDER_TYPE_LIMIT,
            price=current_position.target_price,
        )
        logger.info(
            "New take profit buy order send, price: %s" % current_position.target_price
        )

        current_position.price = price
        current_position.quantity = order_quantity

    current_position.take_profit_order = Order(
        price=current_position.target_price,
        quantity=current_position.quantity,
        order_id=resp["orderId"],
        quantity_stable=current_position.target_price
        * current_position.quantity
        / leverage,
    )

    logger.info("Exiting handle filled order")

    return current_position
