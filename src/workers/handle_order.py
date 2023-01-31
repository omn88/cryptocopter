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


async def cancel_take_profit_order(
    client: binance.AsyncClient, position: Position
) -> str:
    position.current_position.take_profit_order.status = await cancel_order(
        client=client,
        order=position.current_position.take_profit_order,
        symbol=position.symbol,
    )
    logger.info(
        "Take profit order: %s, status: %s",
        position.current_position.take_profit_order.order_id,
        position.current_position.take_profit_order.status,
    )

    return position.current_position.take_profit_order.status


async def position_liquidation(
    client: binance.AsyncClient, position: Position
) -> Position:
    logger.info("Position liquidation")

    # IT WILL EXPIRE ITSELF, SO IT MAY BE REMOVED FROM HERE
    status = await cancel_take_profit_order(client=client, position=position)
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
    client: binance.AsyncClient, position: Position, order_update: OrderUpdate
) -> Position:
    logger.info("Target price reached.")

    position.current_position.take_profit_order.quantity -= (
        order_update.last_filled_quantity
    )
    position.current_position.take_profit_order.realized_quantity += (
        order_update.last_filled_quantity
    )
    position.current_position.quantity -= order_update.last_filled_quantity

    logger.info(
        "Original quantity: %s, last filled quantity: %s, realized quantity: %s, remaining quantity: %s",
        order_update.quantity,
        order_update.last_filled_quantity,
        order_update.realized_quantity,
        position.current_position.take_profit_order.quantity,
    )

    saldo = position.saldo
    position.saldo += round(
        abs(
            order_update.last_filled_quantity
            * (
                position.current_position.take_profit_order.price
                - position.current_position.price
            )
        ),
        2,
    )

    logger.info("Earned: %s", round(position.saldo - saldo, 2))

    if (
        position.current_position.take_profit_order.quantity == 0
        or order_update.status == client.ORDER_STATUS_FILLED
    ):
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

    elif order_update.order_type == "MARKET":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            logger.info("MARKET order filled!")
            position.current_position.take_profit_order.status = (
                cancel_take_profit_order(client=client, position=position)
            )
            position = await cancel_remaining_limit_orders(
                client=client, position=position
            )

            position.current_position = CurrentPosition()
            position.orders = []
            position.status = Signals.FLAT
        else:
            logger.info(
                "Market order realization in progress, order status: %s!",
                order_update.status,
            )

    elif order_update.price == position.current_position.target_price:
        if order_update.status in [
            binance.AsyncClient.ORDER_STATUS_FILLED,
            binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED,
        ]:
            position = await target_reached(
                client=client, position=position, order_update=order_update
            )
        if order_update.status == binance.AsyncClient.ORDER_STATUS_NEW:
            logger.info("New take profit order created, id: %s", order_update.order_id)
        if order_update.status == binance.AsyncClient.ORDER_STATUS_CANCELED:
            logger.info("Cancelled take profit order: %s", order_update.order_id)
        if order_update.status == binance.AsyncClient.ORDER_STATUS_EXPIRED:
            logger.info("Expired take profit order: %s", order_update.order_id)

    else:
        position = await order_update_handle(
            client=client,
            order_update=order_update,
            position=position,
        )

    logger.info("Exiting order handle")
    return position
