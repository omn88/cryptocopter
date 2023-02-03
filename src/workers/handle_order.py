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
    client: binance.AsyncClient, take_profit_order: Order, symbol: str
) -> str:

    take_profit_order.status = await cancel_order(
        client=client,
        order=take_profit_order,
        symbol=symbol,
    )
    logger.info(
        "Take profit order: %s, status: %s",
        take_profit_order.order_id,
        take_profit_order.status,
    )

    return take_profit_order.status


async def position_liquidation(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
    df: pandas.DataFrame,
    balance: float,
    leverage: int,
    symbol: str,
) -> Tuple[CurrentPosition, pandas.DataFrame, float]:
    logger.info("Position liquidation")

    # IT WILL EXPIRE ITSELF, SO IT MAY BE REMOVED FROM HERE
    assert isinstance(current_position.take_profit_order, Order)
    status = await cancel_take_profit_order(
        client=client,
        take_profit_order=current_position.take_profit_order,
        symbol=symbol,
    )
    loss = 0.0

    assert current_position.orders is not None
    for order in current_position.orders:
        logger.info("quantity: %s, price: %s", order.quantity, order.price)
        loss += (order.quantity * order.price) / float(leverage)

    balance -= round(loss, 2)

    # ToDo: Add artifacts HEREEEEEE

    current_position = CurrentPosition()
    current_position.status = Signals.FLAT
    df.at[df.index[-1], "position"] = current_position.status

    return current_position, df, balance


async def target_reached(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
    balance: float,
    symbol: str,
) -> Tuple[CurrentPosition, pandas.DataFrame, float]:
    logger.info("Target price reached.")

    assert isinstance(current_position.take_profit_order, Order)

    current_position.take_profit_order.quantity -= order_update.last_filled_quantity
    current_position.take_profit_order.realized_quantity += (
        order_update.last_filled_quantity
    )
    current_position.quantity -= order_update.last_filled_quantity

    logger.info(
        "Original quantity: %s, last filled quantity: %s, realized quantity: %s, remaining quantity: %s",
        order_update.quantity,
        order_update.last_filled_quantity,
        order_update.realized_quantity,
        current_position.take_profit_order.quantity,
    )

    keep_balance = balance
    balance += round(
        abs(
            order_update.last_filled_quantity
            * (current_position.take_profit_order.price - current_position.price)
        ),
        2,
    )
    expected_balance = balance

    logger.info("Earned: %s", round(balance - keep_balance, 2))

    if (
        current_position.take_profit_order.quantity == 0
        or order_update.status == client.ORDER_STATUS_FILLED
    ):
        logger.info("Take profit order filled!")
        current_position = await cancel_remaining_limit_orders(
            client=client, current_position=current_position, symbol=symbol
        )
        # TODO: POSITION ARTIFACTS ARE NOT GATHERED HERE
        current_position = CurrentPosition()
        current_position.orders = []
        current_position.status = Signals.FLAT
        df.at[df.index[-1], "position"] = current_position.status

    else:
        logger.info("Take profit order filled partially!")

    return current_position, df, expected_balance


async def handle_order_update(
    client: binance.AsyncClient, position: Position, order_update: OrderUpdate
) -> Position:
    logger.info("Enter order update handle")

    assert position.current_position.orders is not None

    for order in position.current_position.orders:
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
            (
                position.current_position,
                df,
                position.balance,
            ) = await position_liquidation(
                client=client,
                current_position=position.current_position,
                df=df,
                symbol=position.symbol,
                balance=position.balance,
                leverage=position.leverage,
            )
        else:
            logger.info(
                "Position liquidation in progress, order status: %s!",
                order_update.status,
            )

    elif order_update.order_type == "MARKET":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            logger.info("MARKET order filled!")

            current_position = position.current_position

            artifacts = current_position.artifacts
            artifacts.orders = current_position.orders
            artifacts.price = current_position.price
            artifacts.quantity = order_update.quantity
            artifacts.close_price = order_update.price
            artifacts.per_cent_earned = order_update.price / current_position.price
            artifacts.stable_earned = artifacts.quantity * (
                artifacts.close_price - artifacts.price
            )

            position.balance += artifacts.stable_earned
            artifacts.end_balance = position.balance

            artifacts.status = "PROFIT" if artifacts.per_cent_earned > 0 else "LOSS"

            save_to_file(artifacts=artifacts)

            position.current_position = CurrentPosition()
            position.current_position.orders = []
            position.current_position.status = Signals.FLAT
            df.at[df.index[-1], "position"] = position.current_position.status

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
                (
                    position.current_position,
                    df,
                    position.balance,
                ) = await target_reached(
                    client=client,
                    current_position=position.current_position,
                    order_update=order_update,
                    df=df,
                    balance=position.balance,
                    symbol=position.symbol,
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
