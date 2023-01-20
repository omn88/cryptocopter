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
    client: binance.AsyncClient, position: Position, order_update: OrderUpdate
) -> Position:
    logger.info("Enter order update handle")

    for order in position.orders:
        if order_update.order_id == order.order_id:
            if order.status == client.ORDER_STATUS_FILLED:
                logger.info("Order: %s already filled", order.order_id)
            else:

                order.status = order_update.status
                order.price = order_update.price
                order.quantity = order_update.quantity
                order.realized_quantity = order_update.realized_quantity

                position = await update_position(
                    client=client,
                    position=position,
                )
        else:
            try:
                assert order_update.status == binance.AsyncClient.ORDER_STATUS_NEW
            except AssertionError as error:
                logger.info(error)

    logger.info("Exit order update handle")
    return position


async def order_handle(
    client: binance.AsyncClient, position: Position, order_update: OrderUpdate
) -> Position:
    logger.info("Entering order handle")

    assert isinstance(order_update, OrderUpdate)
    order_price = order_update.price
    order_quantity = order_update.quantity
    order_realized_quantity = order_update.realized_quantity
    order_status = order_update.status
    order_id = order_update.order_id
    order_type = order_update.order_type

    logger.info(
        "Order price: %s, order quantity: %s, realized quantity: %s, order status: %s, order id: %s, order type: %s"
        % (
            order_price,
            order_quantity,
            order_realized_quantity,
            order_status,
            order_id,
            order_type,
        )
    )

    if order_price == position.current_position.liquidation_price:
        if order_status == binance.AsyncClient.ORDER_STATUS_FILLED:
            position = await position_liquidation(client=client, position=position)
        else:
            logger.info(
                "Position liquidation in progress, order status: %s!", order_status
            )

    elif order_price == position.current_position.target_price:
        # ToDo: handle when filled partially, there was a test I think, wtf?
        if order_status != binance.AsyncClient.ORDER_STATUS_NEW:
            position = await target_reached(
                client=client, position=position, order_quantity=order_quantity
            )
        else:
            logger.info("New take profit order created, id: %s", order_id)
    else:
        position = await order_update_handle(
            client=client,
            order_update=order_update,
            position=position,
        )

    logger.info("Exiting order handle")
    return position
