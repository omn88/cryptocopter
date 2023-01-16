from typing import NamedTuple

import binance

from src.features import Signals
from src.orders import (
    cancel_remaining_limit_orders,
    Position,
    CurrentPosition,
    update_position,
    cancel_order,
)
import logging

from src.producers.producers import OrderUpdate

logger = logging.getLogger("handle_order")


async def position_liquidation(
    client: binance.AsyncClient, position: Position
) -> Position:
    logger.info("Position liquidation")

    logger.info(
        "Cancelling take profit order: %s"
        % position.current_position.take_profit_order.order_id
    )
    position.current_position.take_profit_order.status = await cancel_order(
        client=client,
        order=position.current_position.take_profit_order,
        symbol=position.symbol,
    )

    loss = 0
    for order in position.orders:
        logger.info("quantity: %s, price: %s" % (order.quantity, order.price))
        loss += (order.quantity * order.price) / position.leverage

    position.saldo -= round(loss, 2)

    position.current_position = CurrentPosition()
    position.orders = []
    position.status = Signals.FLAT

    return position


async def target_reached(
    client: binance.AsyncClient, position: Position, order_quantity
) -> Position:
    logger.info("Target price reached.")

    position.current_position.take_profit_order.quantity -= order_quantity
    position.current_position.take_profit_order.realized_quantity += order_quantity

    position.current_position.quantity -= order_quantity

    logger.info(
        "New take profit quantity: %s",
        position.current_position.take_profit_order.quantity,
    )

    logger.info(
        "Saldo: %s, current position price: %s, current position quantity: %s, take profit order: %s"
        % (
            position.saldo,
            position.current_position.price,
            position.current_position.quantity,
            position.current_position.take_profit_order,
        )
    )

    if position.current_position.take_profit_order.quantity == 0:
        logger.info("Take profit order FILLED!")
        saldo = position.saldo
        position = await cancel_remaining_limit_orders(client=client, position=position)
        position.saldo += round(
            abs(
                order_quantity
                * (
                    position.current_position.take_profit_order.price
                    - position.current_position.price
                )
            ),
            2,
        )

        logger.info("Earned: %s", round(position.saldo - saldo, 2))

        position.current_position = CurrentPosition()
        position.orders = []
        position.status = Signals.FLAT

        logger.info("Position after reaching target: %s", position.current_position)
    else:
        logger.info("Take profit order FILLED PARTIALLY!")
        saldo = position.saldo
        position.saldo += round(
            abs(
                order_quantity
                * (
                    position.current_position.take_profit_order.price
                    - position.current_position.price
                )
            ),
            2,
        )

        logger.info("Earned: %s", round(position.saldo - saldo, 2))

    return position


async def order_update_handle(
    client: binance.AsyncClient,
    position: Position,
    order_price,
    order_status,
    order_quantity,
) -> Position:
    logger.info("Enter order update handle")
    for order in position.orders:
        if order.status in [
            client.ORDER_STATUS_NEW,
            client.ORDER_STATUS_PARTIALLY_FILLED,
        ]:
            if order.price == order_price:
                order.status = order_status
                if order_status == client.ORDER_STATUS_PARTIALLY_FILLED:
                    logger.info(
                        "Order partially filled, price: %s, quantity: %s"
                        % (order_price, order_quantity)
                    )
                    logger.info(
                        "Order: %s realized quantity: %s",
                        order.order_id,
                        order.realized_quantity,
                    )
                    order.realized_quantity += order_quantity
                    logger.info(
                        "Order: %s NEW realized quantity: %s",
                        order.order_id,
                        order.realized_quantity,
                    )

                    position = await update_position(
                        client=client,
                        position=position,
                        price=order_price,
                        order_quantity=order_quantity,
                        order=order,
                    )
                elif order_status == client.ORDER_STATUS_FILLED:
                    order.realized_quantity = order.quantity
                    order.status = order_status

                    logger.info(
                        "Order filled, price: %s, quantity: %s"
                        % (order_price, order_quantity)
                    )

                    position = await update_position(
                        client=client,
                        position=position,
                        price=order_price,
                        order_quantity=order_quantity,
                        order=order,
                    )
                elif order_status == client.ORDER_STATUS_NEW:
                    logger.info("New order created")
                elif order_status == client.ORDER_STATUS_CANCELED:
                    logger.info("Order cancelled")
                elif order_status == client.ORDER_STATUS_EXPIRED:
                    logger.info("Order expired")
        elif order.status == client.ORDER_STATUS_FILLED:
            logger.info("Order: %s already filled", order.order_id)
    logger.info("Exit order update handle")
    return position


async def order_handle(
    client: binance.AsyncClient, position: Position, order_update: NamedTuple
) -> Position:
    logger.info("Entering order handle")

    assert isinstance(order_update, OrderUpdate)
    order_price = order_update.price
    order_quantity = order_update.quantity
    order_status = order_update.status
    order_id = order_update.order_id

    logger.info(
        "Order price: %s, order quantity: %s, order status: %s, order id: %s"
        % (order_price, order_quantity, order_status, order_id)
    )

    # ToDo: GET LIQUID PRICE FROM BINANCE
    if order_price == position.current_position.liquidation_price:
        position = await position_liquidation(client=client, position=position)
    elif order_price == position.current_position.target_price:
        if order_status != binance.AsyncClient.ORDER_STATUS_NEW:
            position = await target_reached(
                client=client, position=position, order_quantity=order_quantity
            )
        else:
            logger.info("New order created, id: %s", order_id)
    else:
        position = await order_update_handle(
            client=client,
            order_quantity=order_quantity,
            position=position,
            order_status=order_status,
            order_price=order_price,
        )

    logger.info("Exiting order handle")
    return position
