import binance

from src.features import Signals
from src.orders import (
    cancel_remaining_limit_orders,
    Position,
    CurrentPosition,
    update_position,
)
import logging

logger = logging.getLogger("worker_order")


async def order_handle(
    client: binance.AsyncClient, position: Position, order_update: dict
) -> Position:
    logger.info("Entering order handle")

    updated_order = order_update["o"]
    order_status = updated_order["X"]
    order_price = round(updated_order["p"], 2)
    order_quantity = updated_order["q"]

    logger.info(
        "Order price: %s, order quantity: %s, order status: %s"
        % (order_price, order_quantity, order_status)
    )

    if order_price == position.current_position.liquidation_price:
        logger.info("Position liquidation")
        take_profit_order = position.current_position.take_profit_order

        logger.info("Cancelling take profit order: %s" % take_profit_order.order_id)
        resp = await client.futures_cancel_order(order_id=take_profit_order.order_id)
        assert resp["status"] == client.ORDER_STATUS_CANCELED

        loss = 0
        for order in position.orders:
            logger.info("quantity: %s, price: %s" % (order.quantity, order.price))
            loss += (order.quantity * order.price) / position.leverage

        position.saldo -= round(loss, 2)

        position.current_position = CurrentPosition()
        position.orders = []
        position.status = Signals.FLAT

    if order_price == position.current_position.target_price:
        logger.info("Target price reached.")

        position.current_position.take_profit_order.quantity -= order_quantity
        position.current_position.take_profit_order.realized_quantity += order_quantity

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
            position = await cancel_remaining_limit_orders(
                client=client, position=position
            )
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

    for order in position.orders:
        if order.status in [
            client.ORDER_STATUS_NEW,
            client.ORDER_STATUS_PARTIALLY_FILLED,
        ]:
            if order.price == order_price:
                order.status = order_status

                if order_status == client.ORDER_STATUS_PARTIALLY_FILLED:
                    order.realized_quantity = order.realized_quantity + order_quantity
                    logger.info(
                        "Order partially filled, price: %s, quantity: %s"
                        % (order_price, order_quantity)
                    )
                    position.current_position = await update_position(
                        client=client,
                        position=position,
                        price=order_price,
                        order_quantity=order_quantity,
                        symbol=position.symbol,
                        leverage=position.leverage,
                    )
                elif order_status == client.ORDER_STATUS_FILLED:
                    order.realized_quantity = order.quantity

                    logger.info(
                        "Order filled, price: %s, quantity: %s"
                        % (order_price, order_quantity)
                    )

                    position.current_position = await update_position(
                        client=client,
                        position=position,
                        price=order_price,
                        order_quantity=order_quantity,
                        symbol=position.symbol,
                        leverage=position.leverage,
                    )
                elif order_status == client.ORDER_STATUS_NEW:
                    logger.info("New order created")
                elif order_status == client.ORDER_STATUS_CANCELED:
                    logger.info("Order cancelled")
                elif order_status == client.ORDER_STATUS_EXPIRED:
                    logger.info("Order expired")

    return position
