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
        "Cancelling take profit order: %s",
        position.current_position.take_profit_order.order_id,
    )
    position.current_position.take_profit_order.status = await cancel_order(
        client=client,
        order=position.current_position.take_profit_order,
        symbol=position.symbol,
    )

    loss = 0
    for order in position.orders:
        logger.info("quantity: %s, price: %s", order.quantity, order.price)
        loss += (order.quantity * order.price) / position.leverage

    position.saldo -= round(loss, 2)

    position.current_position = CurrentPosition()
    position.orders = []
    position.status = Signals.FLAT

    return position


async def target_reached(
    client: binance.AsyncClient,
    position: Position,
    realized_quantity,
    original_quantity,
    last_filled_quantity,
) -> Position:
    logger.info("Target price reached.")

    position.current_position.take_profit_order.quantity -= last_filled_quantity
    position.current_position.take_profit_order.realized_quantity += (
        last_filled_quantity
    )
    position.current_position.quantity -= last_filled_quantity

    logger.info(
        "Original quantity: %s, last filled quantity: %s, realized quantity: %s, remaining quantity: %s",
        original_quantity,
        last_filled_quantity,
        realized_quantity,
        position.current_position.take_profit_order.quantity,
    )

    saldo = position.saldo
    position.saldo += round(
        abs(
            last_filled_quantity
            * (
                position.current_position.take_profit_order.price
                - position.current_position.price
            )
        ),
        2,
    )

    logger.info("Earned: %s", round(position.saldo - saldo, 2))

    if position.current_position.take_profit_order.quantity == 0:
        logger.info("Take profit order filled!")
        position = await cancel_remaining_limit_orders(client=client, position=position)

        position.current_position = CurrentPosition()
        position.orders = []
        position.status = Signals.FLAT

    else:
        logger.info("Take profit order filled partially!")

    return position


async def order_update_handle(
    client: binance.AsyncClient, position: Position, order_update: OrderUpdate
) -> Position:
    logger.info("Enter order update handle")

    for order in position.orders:
        if order_update.order_id == order.order_id:
            if order.status == client.ORDER_STATUS_FILLED:
                logger.info("Order: %s already filled", order.order_id)
            order.status = order_update.status
            order.price = order_update.price
            order.quantity = order_update.quantity
            order.realized_quantity = order_update.realized_quantity

            if order_update.status in [
                client.ORDER_STATUS_NEW,
                client.ORDER_STATUS_CANCELED,
                client.ORDER_STATUS_EXPIRED,
            ]:
                order.status = order_update.status
                order.order_id = order_update.order_id
                logger.info("Order: %s status: %s", order.order_id, order.status)
            else:
                position = await update_position(
                    client=client,
                    position=position,
                )

    logger.info("Exit order update handle")
    return position


async def order_handle(
    client: binance.AsyncClient, position: Position, order_update: OrderUpdate
) -> Position:
    logger.info("Entering order handle")

    assert isinstance(order_update, OrderUpdate)
    if order_update.order_type == "LIQUIDATION":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            position = await position_liquidation(client=client, position=position)
        else:
            logger.info(
                "Position liquidation in progress, order status: %s!",
                order_update.status,
            )

    elif order_update.price == position.current_position.target_price:
        # ToDo: handle when filled partially, there was a test I think, wtf?
        if order_update.status != binance.AsyncClient.ORDER_STATUS_NEW:
            position = await target_reached(
                client=client,
                position=position,
                original_quantity=order_update.quantity,
                realized_quantity=order_update.realized_quantity,
                last_filled_quantity=order_update.last_filled_quantity,
            )
        else:
            logger.info("New take profit order created, id: %s", order_update.order_id)
    else:
        position = await order_update_handle(
            client=client,
            order_update=order_update,
            position=position,
        )

    logger.info("Exiting order handle")
    return position
