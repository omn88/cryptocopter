import binance
from src import orders
import logging

logger = logging.getLogger("worker_order")


async def order_handle(
    client: binance.AsyncClient, position: orders.Position, order_update: dict
) -> orders.Position:
    logger.info("Entering order handle")

    updated_order = order_update["o"]
    order_status = updated_order["X"]
    order_price = updated_order["p"]
    order_quantity = updated_order["q"]

    # HANDLE WHEN LIQUIDATION OR TAKE PROFIT

    for order in position.orders:
        if order.status in [
            client.ORDER_STATUS_NEW,
            client.ORDER_STATUS_PARTIALLY_FILLED,
        ]:
            order_price = round(order_price, 2)
            if order.price == order_price:
                order.status = order_status

                if order_status == client.ORDER_STATUS_PARTIALLY_FILLED:
                    order.realized_quantity = order.realized_quantity + order_quantity
                    logger.info(
                        "Order partially filled, price: %s, quantity: %s"
                        % (order_price, order_quantity)
                    )
                    position.current_position = await orders.update_position(
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

                    position.current_position = await orders.update_position(
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
