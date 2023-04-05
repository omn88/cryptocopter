import dataclasses
from pprint import pformat
from typing import Tuple, Optional
import json
from datetime import datetime
import binance
import pandas

from constants import NUMBER_OF_DCA_ORDERS, LEVERAGE
from src.common.common import futures_get_position_info
from src.features.features import Signal, State
from src.orders import (
    cancel_remaining_limit_orders,
    Position,
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
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("handle_order")


async def futures_validate_orders(
    position: Position,
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    balance: float,
) -> Tuple[Position, pandas.DataFrame, float]:
    assert position.orders is not None
    for order in position.orders:
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

            position, df, balance = await order_handle(
                df=df,
                balance=balance,
                position=position,
                order_update=order_update,
                client=client,
            )
            logger.info(
                "Order %s status changed to %s. Sending order update: %s",
                order.order_id,
                order.status,
                order_update,
            )

    return position, df, balance


async def futures_position_open(
    client: binance.AsyncClient,
    df: pandas.DataFrame,
    balance: float,
    order_quantity_list: pandas.DataFrame,
    signal: Signal,
    entry_price: float,
    side: str,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Entering %s position open, mode: %s", side, mode)

    position = Position(side=side)
    position.artifacts.start_balance = balance
    position.artifacts.no_of_dca_orders = NUMBER_OF_DCA_ORDERS

    position.status = signal

    position = prepare_orders(
        position=position,
        mode=mode,
        entry_price=entry_price,
        balance=balance,
        order_quantity_list=order_quantity_list,
    )

    assert position.orders is not None
    position.orders = await send_orders(
        client=client,
        orders=position.orders,
        side=client.SIDE_BUY if side == PositionSide.LONG else client.SIDE_SELL,
    )

    position, df, balance = await futures_validate_orders(
        position=position, client=client, df=df, balance=balance
    )

    logger.info(
        "Exiting %s position open, opened orders: %s",
        side,
        position.orders,
    )
    return position


async def futures_position_close(
    client: binance.AsyncClient, position: Position, balance: float
) -> Position:

    close_side = (
        client.SIDE_BUY if position.side == client.SIDE_SELL else client.SIDE_SELL
    )

    if position.take_profit_order is not None:
        logger.info("Entering position close, trying to Market %s", close_side)

        await send_market_order(
            client=client,
            position=position,
            side=close_side,
        )

        position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.take_profit_order,
        )
        logger.info("Cancelled take profit order")
    else:
        update_artifacts_and_save(position=position, order_update=None, balance=balance)

    if position.status in [
        State.SHORT_SPECIAL,
        State.LONG_SPECIAL,
    ]:
        logger.info(
            "Closing special position, trying to Market %s",
            close_side,
        )

        await send_market_order(
            client=client,
            position=position,
            side=close_side,
        )

        position.orders = []

    position.status = State.FLAT

    await cancel_remaining_limit_orders(client, position=position)

    logger.info("Exiting position close")
    return position


async def update_take_profit_order(
    client: binance.AsyncClient,
    position: Position,
) -> Position:

    if isinstance(position.take_profit_order, Order):
        logger.info(
            "Enter update take profit order: %s",
            position.take_profit_order.order_id,
        )
        position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.take_profit_order,
        )

    position.target_price = target_price_calculate(
        side=position.side,
        price=position.price,
    )

    take_profit_order = Order(
        price=position.target_price,
        quantity=position.quantity,
        quantity_stable=round(
            (abs(position.quantity) * position.price / LEVERAGE),
            2,
        ),
    )

    position.take_profit_order = await send_order(
        client=client,
        side=PositionSide.LONG
        if position.side == PositionSide.SHORT
        else PositionSide.SHORT,
        order=take_profit_order,
    )

    assert isinstance(position.take_profit_order, Order)
    logger.info(
        "New take profit buy order send, price: %s, quantity: %s realized QUANT: %s",
        position.target_price,
        position.take_profit_order.quantity,
        position.take_profit_order.realized_quantity,
    )

    return position


async def position_liquidation(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
    balance: float,
) -> Tuple[Position, pandas.DataFrame, float]:
    logger.info("Position liquidation")

    # IT WILL EXPIRE ITSELF, SO IT MAY BE REMOVED FROM HERE
    assert isinstance(position.take_profit_order, Order)
    status = await cancel_take_profit_order(
        client=client,
        take_profit_order=position.take_profit_order,
    )

    loss = 0.0
    assert position.orders is not None
    for order in position.orders:
        logger.info("quantity: %s, price: %s", order.quantity, order.price)
        loss += order.quantity_stable

    balance -= round(loss, 2)

    update_artifacts_and_save(
        position=position, order_update=order_update, balance=balance
    )

    position = Position()
    df.at[df.index[-1], "position"] = position.status

    return position, df, balance


async def target_reached(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
    df: pandas.DataFrame,
    balance: float,
) -> Tuple[Position, pandas.DataFrame, float]:
    logger.info("Target price reached.")

    assert isinstance(position.take_profit_order, Order)

    position.take_profit_order.quantity -= order_update.last_filled_quantity
    position.take_profit_order.realized_quantity += order_update.last_filled_quantity
    position.quantity -= order_update.last_filled_quantity

    logger.info(
        "Original quantity: %s, last filled quantity: %s, realized quantity: %s, remaining quantity: %s",
        order_update.quantity,
        order_update.last_filled_quantity,
        order_update.realized_quantity,
        position.take_profit_order.quantity,
    )

    realized_position = round(
        abs(
            order_update.last_filled_quantity
            * (position.take_profit_order.price - position.price)
        ),
        2,
    )

    balance += realized_position

    logger.info("Earned: %s", round(realized_position, 2))

    if (
        position.take_profit_order.quantity == 0
        or order_update.status == client.ORDER_STATUS_FILLED
    ):
        logger.info("Take profit order filled!")
        position = await cancel_remaining_limit_orders(client=client, position=position)
        update_artifacts_and_save(
            position=position,
            order_update=order_update,
            balance=balance,
        )

        position = Position()
        df.at[df.index[-1], "position"] = position.status

    else:
        logger.info("Take profit order filled partially!")

    return position, df, balance


async def update_position(
    client: binance.AsyncClient,
    position: Position,
) -> Position:
    logger.info("Entering update position")

    (
        position.liquidation_price,
        position.price,
        position.quantity,
    ) = await futures_get_position_info(client=client)

    position = await update_take_profit_order(
        client=client,
        position=position,
    )

    logger.info("Exiting update position")

    return position


async def handle_order_update(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
) -> Position:
    logger.info("Enter order update handle")

    assert position.orders is not None

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


def update_artifacts_and_save(
    position: Position,
    order_update: Optional[OrderUpdate],
    balance: float,
) -> None:

    artifacts = position.artifacts

    if order_update is not None:
        artifacts.close_price = (
            order_update.average_price
            if order_update.order_type in ["MARKET", "LIQUIDATION"]
            else order_update.price
        )
        artifacts.per_cent_earned = order_update.price / position.price
        artifacts.stable_earned = artifacts.quantity * (
            order_update.price - artifacts.price
        )

        balance += artifacts.stable_earned
        artifacts.status = "PROFIT" if artifacts.per_cent_earned > 0 else "LOSS"

    else:
        artifacts.status = "NO_POSITION"

    artifacts.orders = position.orders
    artifacts.price = position.price
    artifacts.quantity = position.quantity
    artifacts.end_balance = balance

    logger.info("Position artifacts: %s", pformat(artifacts))

    save_to_file(artifacts=artifacts)


async def order_handle(
    df: pandas.DataFrame,
    balance: float,
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
) -> Tuple[Position, pandas.DataFrame, float]:
    logger.info("Entering order handle")

    assert isinstance(order_update, OrderUpdate)
    if order_update.order_type == "LIQUIDATION":
        if order_update.status == binance.AsyncClient.ORDER_STATUS_FILLED:
            position, df, balance = await position_liquidation(
                client=client,
                position=position,
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
            assert position.market_order is not None

            position.market_order.status = order_update.status
            position.market_order.price = order_update.price
            position.market_order.quantity = order_update.quantity
            position.market_order.realized_quantity = order_update.realized_quantity

            update_artifacts_and_save(
                position=position,
                order_update=order_update,
                balance=balance,
            )

            position.orders = []

        else:
            position.market_order = Order(
                price=order_update.price,
                quantity=order_update.quantity,
                order_id=order_update.order_id,
                realized_quantity=order_update.realized_quantity,
                status=order_update.status,
            )
            logger.info(
                "Market order realization in progress: %s!",
                position.market_order,
            )

    elif order_update.order_type == "LIMIT":
        if order_update.price == position.target_price:
            if order_update.status in [
                binance.AsyncClient.ORDER_STATUS_FILLED,
                binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED,
            ]:
                position, df, balance = await target_reached(
                    client=client,
                    position=position,
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
            position = await handle_order_update(
                client=client,
                order_update=order_update,
                position=position,
            )

    logger.info("Exiting order handle")
    return position, df, balance
