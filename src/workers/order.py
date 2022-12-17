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

    if order_price == position.current_position.liquidation_price:
        # cancel remaining orders
        take_profit_order = position.current_position.take_profit_order
        if take_profit_order is not None:
            logger.info(
                "Take profit order is not none, so cancelling order: %s"
                % take_profit_order.order_id
            )
            resp = await client.futures_cancel_order(
                order_id=take_profit_order.order_id
            )
            assert resp["status"] == client.ORDER_STATUS_CANCELED

        position.current_position = CurrentPosition()
        position.orders = []
        position.status = Signals.FLAT
    if order_price == position.current_position.target_price:
        position = await cancel_remaining_limit_orders(client=client, position=position)
        position.saldo += position.current_position.take_profit_order.quantity * (
            position.current_position.take_profit_order.price
            - position.current_position.price
        )
        position.current_position = CurrentPosition()
        position.orders = []
        position.status = Signals.FLAT

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
                        current_position=position.current_position,
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
                        current_position=position.current_position,
                        price=order_price,
                        order_quantity=order.quantity,
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
