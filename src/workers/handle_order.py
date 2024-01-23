import asyncio
import dataclasses
from pprint import pformat
from typing import Tuple, Optional
import json
from datetime import datetime
import logging
from binance.enums import SIDE_SELL, SIDE_BUY

from src.common.common import signal_to_state
from src.common.constants import LEVERAGE
from src.common.identifiers import (
    OrderUpdate,
    Signal,
    PositionMode,
    Position,
    State,
    Order,
    Artifacts,
    BinanceClient,
)

logger = logging.getLogger("handle_order")


async def prepare_and_send_orders(
    client: BinanceClient,
    signal: Signal,
    entry_price: float,
    side: str,
    ui_queue: asyncio.Queue,
    symbol: str,
    number_of_orders: int,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Entering %s position open, mode: %s", side, mode)
    position = Position(side=side)
    position.state = signal_to_state(signal=signal)

    position = prepare_orders(
        position=position,
        mode=mode,
        entry_price=entry_price,
        number_of_orders=number_of_orders,
    )

    side = SIDE_BUY if side == PositionSide.LONG else SIDE_SELL

    assert position.orders is not None
    position.orders = await send_orders(
        client=client,
        orders=position.orders,
        side=side,
        ui_queue=ui_queue,
        symbol=symbol,
    )

    logger.info(
        "Exiting %s position open, opened orders: %s",
        side,
        position.orders,
    )
    return position


async def close_special_position(
    client: BinanceClient, position: Position, ui_queue: asyncio.Queue, symbol: str
) -> Position:
    if position.state in [State.SHORT_SPECIAL, State.LONG_SPECIAL]:
        close_side = (
            client.SIDE_BUY
            if position.state == State.SHORT_SPECIAL
            else client.SIDE_SELL
        )
        logger.info("Closing special position, trying to Market %s", close_side)

        await send_market_order(
            client=client, position=position, side=close_side, symbol=symbol
        )

        position.orders = []

    position.state = State.FLAT

    await cancel_remaining_limit_orders(
        client, position=position, ui_queue=ui_queue, symbol=symbol
    )

    logger.info("Exiting position close")
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


# def update_artifacts_and_save(
#     position: Position,
#     order_update: Optional[OrderUpdate],
#     balance: float,
# ) -> None:
#     artifacts = position.artifacts

#     if order_update is not None:
#         if order_update.order_type in [
#             "MARKET",
#             "LIQUIDATION",
#         ]:
#             close_price = order_update.average_price
#             artifacts.close_price = close_price
#             artifacts.per_cent_earned = round(
#                 float(close_price / position.entry_price), 3
#             )
#             artifacts.stable_earned = position.quantity * (
#                 close_price - position.entry_price
#             )
#         else:
#             artifacts.close_price = order_update.price
#             artifacts.per_cent_earned = round(
#                 float(order_update.price / position.entry_price), 3
#             )
#             artifacts.stable_earned = artifacts.quantity * (
#                 order_update.price - artifacts.price
#             )

#         balance += artifacts.stable_earned
#         artifacts.status = "PROFIT" if artifacts.per_cent_earned > 0 else "LOSS"

#     else:
#         artifacts.status = "NO_POSITION"

#     artifacts.orders = position.orders
#     artifacts.price = position.entry_price
#     artifacts.quantity = position.quantity
#     artifacts.end_balance = balance
#     artifacts.market_order = position.market_order

#     logger.info("Position artifacts: %s", pformat(artifacts))

#     save_to_file(artifacts=artifacts)


async def market_order_filled(
    order_update: OrderUpdate, position: Position, balance: float
) -> Tuple[Position, float]:
    logger.info("MARKET order filled!")
    assert position.market_order is not None

    position.market_order.status = order_update.status
    position.market_order.price = order_update.price
    position.market_order.quantity = order_update.quantity
    position.market_order.realized_quantity = order_update.realized_quantity

    # update_artifacts_and_save(
    #     position=position,
    #     order_update=order_update,
    #     balance=balance,
    # )

    return position, balance


async def market_order_filled_partially(order_update: OrderUpdate, position: Position):
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
