import dataclasses
from pprint import pformat
from typing import Tuple, Optional
import json
from datetime import datetime
import binance
import pandas

from constants import NUMBER_OF_DCA_ORDERS, LEVERAGE
from src import features
from src.common import futures_get_position_info
from src.orders import (
    cancel_remaining_limit_orders,
    CurrentPosition,
    cancel_order,
    Artifacts,
    Order,
    PositionMode,
    prepare_orders,
    send_orders,
    PositionSide,
    cancel_take_profit_order,
    futures_get_order,
    send_market_order,
    send_order,
    target_price_calculate,
)
import logging
from src.producers.producers import OrderUpdate

logger = logging.getLogger("handle_order")


async def futures_validate_orders(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
    df: pandas.DataFrame,
    balance: float,
) -> Tuple[CurrentPosition, pandas.DataFrame]:
    assert current_position.orders is not None
    for order in current_position.orders:
        order = await futures_get_order(client=client, order=order)

        if order.status != "NEW":
            order_update = OrderUpdate(
                price=order.price,
                quantity=order.quantity,
                status=order.status,
                order_id=order.order_id,
                order_type="LIMIT",
                last_filled_quantity=order.realized_quantity,
                realized_quantity=order.realized_quantity,
            )

            current_position, df, balance = await order_handle(
                client=client,
                df=df,
                current_position=current_position,
                order_update=order_update,
                balance=balance,
            )
            logger.info(
                "Order %s status changed to %s. Sending order update: %s",
                order.order_id,
                order.status,
                order_update,
            )

    return current_position, df


async def futures_position_open(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    signal: features.Signals,
    balance: float,
    entry_price: float,
    side: str,
    order_quantity_list: pandas.DataFrame,
    mode: PositionMode = PositionMode.DCA,
) -> CurrentPosition:
    logger.info("Entering %s position open, mode: %s", side, mode)

    current_position = CurrentPosition(side=side)
    current_position.artifacts.start_balance = balance
    current_position.artifacts.no_of_dca_orders = NUMBER_OF_DCA_ORDERS

    current_position.status = signal

    current_position = prepare_orders(
        current_position=current_position,
        mode=mode,
        entry_price=entry_price,
        balance=balance,
        order_quantity_list=order_quantity_list,
    )

    assert current_position.orders is not None
    current_position.orders = await send_orders(
        client=client,
        orders=current_position.orders,
        side=client.SIDE_BUY if side == PositionSide.LONG else client.SIDE_SELL,
    )

    current_position, df = await futures_validate_orders(
        client=client,
        current_position=current_position,
        balance=balance,
        df=df,
    )

    logger.info(
        "Exiting %s position open, opened orders: %s",
        side,
        current_position.orders,
    )
    return current_position


async def futures_position_close(
    client: binance.AsyncClient, current_position: CurrentPosition, balance: float
) -> CurrentPosition:

    close_side = (
        client.SIDE_BUY
        if current_position.side == client.SIDE_SELL
        else client.SIDE_SELL
    )

    if current_position.take_profit_order is not None:
        logger.info("Entering position close, trying to Market %s", close_side)

        await send_market_order(
            client=client,
            current_position=current_position,
            side=close_side,
        )

        current_position.take_profit_order.status = await cancel_order(
            client=client,
            order=current_position.take_profit_order,
        )
        logger.info("Cancelled take profit order")
    else:
        update_artifacts_and_save(
            current_position=current_position, order_update=None, balance=balance
        )

    if current_position.status in [
        features.Signals.SHORT_SPECIAL,
        features.Signals.LONG_SPECIAL,
    ]:
        logger.info(
            "Closing special position, trying to Market %s",
            close_side,
        )

        await send_market_order(
            client=client,
            current_position=current_position,
            side=close_side,
        )

        current_position.orders = []

    current_position.status = features.Signals.FLAT

    await cancel_remaining_limit_orders(client, current_position=current_position)

    logger.info("Exiting position close")
    return current_position


async def update_take_profit_order(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
) -> CurrentPosition:

    if isinstance(current_position.take_profit_order, Order):
        logger.info(
            "Enter update take profit order: %s",
            current_position.take_profit_order.order_id,
        )
        current_position.take_profit_order.status = await cancel_order(
            client=client,
            order=current_position.take_profit_order,
        )

    current_position.target_price = target_price_calculate(
        side=current_position.side,
        price=current_position.price,
    )

    take_profit_order = Order(
        price=current_position.target_price,
        quantity=current_position.quantity,
        quantity_stable=round(
            (abs(current_position.quantity) * current_position.price / LEVERAGE),
            2,
        ),
    )

    current_position.take_profit_order = await send_order(
        client=client,
        side=PositionSide.LONG
        if current_position.side == PositionSide.SHORT
        else PositionSide.SHORT,
        order=take_profit_order,
    )

    assert isinstance(current_position.take_profit_order, Order)
    logger.info(
        "New take profit buy order send, price: %s, quantity: %s realized QUANT: %s",
        current_position.target_price,
        current_position.take_profit_order.quantity,
        current_position.take_profit_order.realized_quantity,
    )

    return current_position


async def position_liquidation(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
    balance: float,
) -> Tuple[CurrentPosition, pandas.DataFrame, float]:
    logger.info("Position liquidation")

    # IT WILL EXPIRE ITSELF, SO IT MAY BE REMOVED FROM HERE
    assert isinstance(current_position.take_profit_order, Order)
    status = await cancel_take_profit_order(
        client=client,
        take_profit_order=current_position.take_profit_order,
    )

    loss = 0.0
    assert current_position.orders is not None
    for order in current_position.orders:
        logger.info("quantity: %s, price: %s", order.quantity, order.price)
        loss += order.quantity_stable

    balance -= round(loss, 2)

    update_artifacts_and_save(
        current_position=current_position, order_update=order_update, balance=balance
    )

    current_position = CurrentPosition()
    df.at[df.index[-1], "position"] = current_position.status

    return current_position, df, balance


async def target_reached(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
    balance: float,
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

    realized_position = round(
        abs(
            order_update.last_filled_quantity
            * (current_position.take_profit_order.price - current_position.price)
        ),
        2,
    )

    balance += realized_position

    logger.info("Earned: %s", round(realized_position, 2))

    if (
        current_position.take_profit_order.quantity == 0
        or order_update.status == client.ORDER_STATUS_FILLED
    ):
        logger.info("Take profit order filled!")
        current_position = await cancel_remaining_limit_orders(
            client=client, current_position=current_position
        )
        update_artifacts_and_save(
            current_position=current_position,
            order_update=order_update,
            balance=balance,
        )

        current_position = CurrentPosition()
        df.at[df.index[-1], "position"] = current_position.status

    else:
        logger.info("Take profit order filled partially!")

    return current_position, df, balance


async def update_position(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
) -> CurrentPosition:
    logger.info("Entering update position")

    (
        current_position.liquidation_price,
        current_position.price,
        current_position.quantity,
    ) = await futures_get_position_info(client=client)

    current_position = await update_take_profit_order(
        client=client,
        current_position=current_position,
    )

    logger.info("Exiting update position")

    return current_position


async def handle_order_update(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
    order_update: OrderUpdate,
) -> CurrentPosition:
    logger.info("Enter order update handle")

    assert current_position.orders is not None

    for order in current_position.orders:
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
                current_position = await update_position(
                    client=client,
                    current_position=current_position,
                )

    logger.info("Exit order update handle")
    return current_position


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


def update_artifacts_and_save(
    current_position: CurrentPosition,
    order_update: Optional[OrderUpdate],
    balance: float,
) -> None:

    artifacts = current_position.artifacts

    if order_update is not None:
        artifacts.close_price = (
            order_update.average_price
            if order_update.order_type in ["MARKET", "LIQUIDATION"]
            else order_update.price
        )
        artifacts.per_cent_earned = order_update.price / current_position.price
        artifacts.stable_earned = artifacts.quantity * (
            order_update.price - artifacts.price
        )

        balance += artifacts.stable_earned
        artifacts.status = "PROFIT" if artifacts.per_cent_earned > 0 else "LOSS"

    else:
        artifacts.status = "NO_POSITION"

    artifacts.orders = current_position.orders
    artifacts.price = current_position.price
    artifacts.quantity = current_position.quantity
    artifacts.end_balance = balance

    logger.info("Position artifacts: %s", pformat(artifacts))

    save_to_file(artifacts=artifacts)


async def order_handle(
    client: binance.AsyncClient,
    current_position: CurrentPosition,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
    balance: float,
) -> Tuple[CurrentPosition, pandas.DataFrame, float]:
    logger.info("Entering order handle")

    assert isinstance(order_update, OrderUpdate)
    if order_update.order_type == "LIQUIDATION":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            current_position, df, balance = await position_liquidation(
                client=client,
                current_position=current_position,
                df=df,
                balance=balance,
                order_update=order_update,
            )
        else:
            logger.info(
                "Position liquidation in progress, order status: %s!",
                order_update.status,
            )

    elif order_update.order_type == "MARKET":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            logger.info("MARKET order filled!")
            assert current_position.market_order is not None

            current_position.market_order.status = order_update.status
            current_position.market_order.price = order_update.price
            current_position.market_order.quantity = order_update.quantity
            current_position.market_order.realized_quantity = (
                order_update.realized_quantity
            )

            update_artifacts_and_save(
                current_position=current_position,
                order_update=order_update,
                balance=balance,
            )

            current_position.orders = []

        else:
            current_position.market_order = Order(
                price=order_update.price,
                quantity=order_update.quantity,
                order_id=order_update.order_id,
                realized_quantity=order_update.realized_quantity,
                status=order_update.status,
            )
            logger.info(
                "Market order realization in progress: %s!",
                current_position.market_order,
            )

    elif order_update.order_type == "LIMIT":
        if order_update.price == current_position.target_price:
            if order_update.status in [
                binance.AsyncClient.ORDER_STATUS_FILLED,
                binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED,
            ]:
                current_position, df, balance = await target_reached(
                    client=client,
                    current_position=current_position,
                    order_update=order_update,
                    df=df,
                    balance=balance,
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
            current_position = await handle_order_update(
                client=client,
                order_update=order_update,
                current_position=current_position,
            )

    logger.info("Exiting order handle")
    return current_position, df, balance
