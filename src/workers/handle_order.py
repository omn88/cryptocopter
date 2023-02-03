import dataclasses
from typing import Tuple
import json
from datetime import datetime
import binance
import pandas

from src.features import Signals
from src.orders import (
    cancel_remaining_limit_orders,
    Position,
    CurrentPosition,
    update_position,
    cancel_order,
    Artifacts,
    Order,
)
import logging
from src.producers.producers import OrderUpdate

logger = logging.getLogger("handle_order")


async def cancel_take_profit_order(
    client: binance.AsyncClient, position: Position
) -> str:
    assert isinstance(position.current_position.take_profit_order, Order)
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
    client: binance.AsyncClient, position: Position, df: pandas.DataFrame
) -> Tuple[Position, pandas.DataFrame]:
    logger.info("Position liquidation")

    # IT WILL EXPIRE ITSELF, SO IT MAY BE REMOVED FROM HERE
    status = await cancel_take_profit_order(client=client, position=position)
    loss = 0.0
    for order in position.orders:
        logger.info("quantity: %s, price: %s", order.quantity, order.price)
        loss += (order.quantity * order.price) / float(position.leverage)

    position.balance -= round(loss, 2)

    position.current_position = CurrentPosition()
    position.orders = []
    position.status = Signals.FLAT
    df.at[df.index[-1], "position"] = position.status

    return position, df


async def target_reached(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
) -> Tuple[Position, pandas.DataFrame]:
    logger.info("Target price reached.")

    assert isinstance(position.current_position.take_profit_order, Order)

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

    balance = position.balance
    position.balance += round(
        abs(
            order_update.last_filled_quantity
            * (
                position.current_position.take_profit_order.price
                - position.current_position.price
            )
        ),
        2,
    )

    logger.info("Earned: %s", round(position.balance - balance, 2))

    if (
        position.current_position.take_profit_order.quantity == 0
        or order_update.status == client.ORDER_STATUS_FILLED
    ):
        logger.info("Take profit order filled!")
        position = await cancel_remaining_limit_orders(client=client, position=position)

        position.current_position = CurrentPosition()
        position.orders = []
        position.status = Signals.FLAT
        df.at[df.index[-1], "position"] = position.status

    else:
        logger.info("Take profit order filled partially!")

    return position, df


async def handle_order_update(
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


def save_to_file(artifacts: Artifacts):
    """
    Save the Artifacts instance to a file in JSON format. The file name will have the date and time of creation.
    The file will be saved in the './artifacts/' directory.

    :param artifacts: the Artifacts instance to be saved
    """
    current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = f"./artifacts/artifacts_{current_time}.json"

    with open(file_path, "w") as f:
        json.dump(dataclasses.asdict(artifacts), f, default=str)


async def order_handle(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
) -> Tuple[Position, pandas.DataFrame]:
    logger.info("Entering order handle")

    assert isinstance(order_update, OrderUpdate)
    if order_update.order_type == "LIQUIDATION":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            position, df = await position_liquidation(
                client=client, position=position, df=df
            )
        else:
            logger.info(
                "Position liquidation in progress, order status: %s!",
                order_update.status,
            )

    elif order_update.order_type == "MARKET":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            logger.info("MARKET order filled!")

            artifacts = position.current_position.artifacts
            artifacts.orders = position.orders
            artifacts.price = position.current_position.price
            artifacts.quantity = order_update.quantity
            artifacts.close_price = order_update.price
            artifacts.per_cent_earned = (
                order_update.price / position.current_position.price
            )
            artifacts.stable_earned = artifacts.quantity * (
                artifacts.close_price - artifacts.price
            )

            balance = await client.futures_account_balance(asset="USDT")
            artifacts.end_balance = round(float(balance[6]["balance"]), 2)

            artifacts.status = "PROFIT" if artifacts.per_cent_earned > 0 else "LOSS"

            save_to_file(artifacts=artifacts)

            position.current_position = CurrentPosition()
            position.orders = []
            position.status = Signals.FLAT
            df.at[df.index[-1], "position"] = position.status

        else:
            logger.info(
                "Market order realization in progress, order status: %s!",
                order_update.status,
            )

    elif order_update.order_type == "LIMIT":
        if order_update.price == position.current_position.target_price:
            if order_update.status in [
                binance.AsyncClient.ORDER_STATUS_FILLED,
                binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED,
            ]:
                position, df = await target_reached(
                    client=client, position=position, order_update=order_update, df=df
                )
            if order_update.status == binance.AsyncClient.ORDER_STATUS_NEW:
                logger.info(
                    "New take profit order created, id: %s", order_update.order_id
                )
            if order_update.status == binance.AsyncClient.ORDER_STATUS_CANCELED:
                logger.info("Cancelled take profit order: %s", order_update.order_id)
            if order_update.status == binance.AsyncClient.ORDER_STATUS_EXPIRED:
                logger.info("Expired take profit order: %s", order_update.order_id)

        else:
            position = await handle_order_update(
                client=client,
                order_update=order_update,
                position=position,
            )

    logger.info("Exiting order handle")
    return position, df
