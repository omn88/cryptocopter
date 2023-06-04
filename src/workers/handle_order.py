import asyncio
import dataclasses
from pprint import pformat
from typing import Tuple, Optional
import json
from datetime import datetime
import binance
import pandas
from binance.enums import SIDE_SELL, SIDE_BUY

from src.common.constants import NUMBER_OF_DCA_ORDERS, LEVERAGE, SYMBOL
from src.common.identifiers import (
    Signal,
    PositionMode,
    Position,
    State,
    Order,
    Artifacts,
)
from src.common.orders import (
    cancel_remaining_limit_orders,
    cancel_order,
    prepare_orders,
    send_orders,
    PositionSide,
    cancel_take_profit_order,
    send_market_order,
    send_order,
    target_price_calculate,
    get_orders,
    futures_get_order,
)
import logging

from src.gui.identifiers import OrderData
from src.producers.producers import OrderUpdate

logger = logging.getLogger("handle_order")


def signal_to_state(signal: Signal) -> State:
    return State(signal.value)


async def prepare_and_send_orders(
    client: binance.AsyncClient,
    balance: float,
    order_quantity_list: pandas.DataFrame,
    signal: Signal,
    entry_price: float,
    side: str,
    ui_queue: asyncio.Queue,
    mode: PositionMode = PositionMode.DCA,
) -> Position:
    logger.info("Entering %s position open, mode: %s", side, mode)
    position = Position(side=side)
    position.artifacts.start_balance = balance
    position.artifacts.no_of_dca_orders = NUMBER_OF_DCA_ORDERS
    position.status = signal_to_state(signal=signal)

    position = prepare_orders(
        position=position,
        mode=mode,
        entry_price=entry_price,
        balance=balance,
        order_quantity_list=order_quantity_list,
    )

    side = SIDE_BUY if side == PositionSide.LONG else SIDE_SELL

    assert position.orders is not None
    position.orders = await send_orders(
        client=client,
        orders=position.orders,
        side=side,
    )

    position.orders = await get_orders(client=client, orders=position.orders)

    for order in position.orders:
        await ui_queue.put(
            OrderData(
                order_id=order.order_id,
                open_time=order.open_time,
                symbol=SYMBOL,
                order_type=order.order_type,
                side=side,
                price=order.price,
                quantity=order.quantity,
                realized_quantity=order.realized_quantity,
                status=order.status,
            )
        )

    logger.info(
        "Exiting %s position open, opened orders: %s",
        side,
        position.orders,
    )
    return position


async def close_special_position(
    client: binance.AsyncClient, position: Position, ui_queue: asyncio.Queue
) -> Position:
    if position.status in [State.SHORT_SPECIAL, State.LONG_SPECIAL]:
        close_side = (
            client.SIDE_BUY
            if position.status == State.SHORT_SPECIAL
            else client.SIDE_SELL
        )
        logger.info("Closing special position, trying to Market %s", close_side)

        await send_market_order(
            client=client,
            position=position,
            side=close_side,
        )

        position.orders = []

    position.status = State.FLAT

    await cancel_remaining_limit_orders(client, position=position, ui_queue=ui_queue)

    logger.info("Exiting position close")
    return position


async def close_long(
    client: binance.AsyncClient,
    position: Position,
    balance: float,
    ui_queue: asyncio.Queue,
) -> Position:
    close_side = SIDE_SELL
    position, position_was_opened = await cancel_remaining_limit_orders(
        client, position=position, ui_queue=ui_queue
    )

    if position_was_opened:
        logger.info("Entering position close, trying to Market %s", close_side)
        position = await send_market_order(
            client=client,
            position=position,
            side=close_side,
        )

        position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.take_profit_order,
            side=position.side,
            ui_queue=ui_queue,
        )
        logger.info("Cancelled take profit order")

    else:
        update_artifacts_and_save(position=position, order_update=None, balance=balance)

    logger.info("Exiting close long")
    return position


async def close_short(
    client: binance.AsyncClient,
    position: Position,
    balance: float,
    ui_queue: asyncio.Queue,
) -> Position:
    close_side = client.SIDE_BUY
    position, position_was_opened = await cancel_remaining_limit_orders(
        client, position=position, ui_queue=ui_queue
    )

    if position_was_opened:
        logger.info("Entering position close, trying to Market %s", close_side)
        await send_market_order(
            client=client,
            position=position,
            side=close_side,
        )

        position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.take_profit_order,
            side=position.side,
            ui_queue=ui_queue,
        )
        logger.info("Cancelled take profit order")

    else:
        update_artifacts_and_save(position=position, order_update=None, balance=balance)

    logger.info("Exiting close short")
    return position


async def update_take_profit_order(
    client: binance.AsyncClient, position: Position, ui_queue: asyncio.Queue
) -> Position:
    tp_side = (
        PositionSide.LONG if position.side == PositionSide.SHORT else PositionSide.SHORT
    )
    if position.take_profit_order.order_id != 0:
        logger.info(
            "Enter update take profit order: %s, side: %s",
            position.take_profit_order.order_id,
            tp_side,
        )
        position.take_profit_order.status = await cancel_order(
            client=client,
            order=position.take_profit_order,
            ui_queue=ui_queue,
            side=tp_side,
        )

    position.target_price = target_price_calculate(
        side=position.side,
        price=position.entry_price,
    )

    position.take_profit_order = Order(
        price=position.target_price,
        quantity=position.quantity,
        quantity_stable=round(
            (abs(position.quantity) * position.entry_price / LEVERAGE),
            2,
        ),
    )

    position.take_profit_order = await send_order(
        client=client,
        side=tp_side,
        order=position.take_profit_order,
    )

    position.take_profit_order = await futures_get_order(
        client=client, order=position.take_profit_order
    )

    await ui_queue.put(
        OrderData(
            order_id=position.take_profit_order.order_id,
            open_time=position.take_profit_order.open_time,
            symbol=SYMBOL,
            order_type=position.take_profit_order.order_type,
            side=tp_side,
            price=position.take_profit_order.price,
            quantity=position.take_profit_order.quantity,
            realized_quantity=position.take_profit_order.realized_quantity,
            status=position.take_profit_order.status,
        )
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
    balance: float,
    ui_queue: asyncio.Queue,
) -> Tuple[Position, float]:
    logger.info("Position liquidation")

    # IT WILL EXPIRE ITSELF, SO IT MAY BE REMOVED FROM HERE
    assert isinstance(position.take_profit_order, Order)
    _ = await cancel_take_profit_order(
        client=client,
        take_profit_order=position.take_profit_order,
        ui_queue=ui_queue,
        side=position.side,
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

    position.status = State.FLAT

    return position, balance


async def partial_position_liquidation(
    order_update: OrderUpdate,
) -> None:
    logger.info(
        "Position liquidation in progress, order status: %s!",
        order_update.status,
    )


async def target_partially_reached(
    position: Position,
    order_update: OrderUpdate,
    balance: float,
) -> Tuple[Position, float]:
    logger.info("Take profit order filled partially")

    assert isinstance(position.take_profit_order, Order)

    position.take_profit_order.status = order_update.status
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
            * (position.take_profit_order.price - position.entry_price)
        ),
        2,
    )

    balance += realized_position

    logger.info("Earned: %s", round(realized_position, 2))

    return position, balance


async def target_reached(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
    balance: float,
    ui_queue: asyncio.Queue,
) -> Tuple[Position, float]:
    logger.info("Take profit order filled")

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
            * (position.take_profit_order.price - position.entry_price)
        ),
        2,
    )

    balance += realized_position

    logger.info("Earned: %s", round(realized_position, 2))

    position, _ = await cancel_remaining_limit_orders(
        client=client, position=position, ui_queue=ui_queue
    )
    update_artifacts_and_save(
        position=position,
        order_update=order_update,
        balance=balance,
    )

    return position, balance


async def handle_order_partially_filled(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
    ui_queue: asyncio.Queue,
) -> Position:
    logger.info("Enter order update handle")

    for order in position.orders:
        if order_update.order_id == order.order_id:
            order.status = order_update.status
            order.price = order_update.price
            order.quantity = order_update.quantity
            order.realized_quantity = order_update.realized_quantity
            logger.info("Order: %s partially filled", order.order_id)

            (
                position.liquidation_price,
                position.entry_price,
                position.quantity,
            ) = await futures_get_position_info(client=client)

            position = await update_take_profit_order(
                client=client, position=position, ui_queue=ui_queue
            )

            logger.info("Exiting update position")

    logger.info("Exit order update handle")
    return position


async def handle_order_filled(
    client: binance.AsyncClient,
    position: Position,
    order_update: OrderUpdate,
    ui_queue: asyncio.Queue,
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
                logger.info("Order: %s filled", order.order_id)

            (
                position.liquidation_price,
                position.entry_price,
                position.quantity,
            ) = await futures_get_position_info(client=client)

            position = await update_take_profit_order(
                client=client, position=position, ui_queue=ui_queue
            )

            logger.info("Exiting update position: %s", position.quantity)

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
        if order_update.order_type in [
            "MARKET",
            "LIQUIDATION",
        ]:
            close_price = order_update.average_price
            artifacts.close_price = close_price
            artifacts.per_cent_earned = round(
                float(close_price / position.entry_price), 3
            )
            artifacts.stable_earned = position.quantity * (
                close_price - position.entry_price
            )
        else:
            artifacts.close_price = order_update.price
            artifacts.per_cent_earned = round(
                float(order_update.price / position.entry_price), 3
            )
            artifacts.stable_earned = artifacts.quantity * (
                order_update.price - artifacts.price
            )

        balance += artifacts.stable_earned
        artifacts.status = "PROFIT" if artifacts.per_cent_earned > 0 else "LOSS"

    else:
        artifacts.status = "NO_POSITION"

    artifacts.orders = position.orders
    artifacts.price = position.entry_price
    artifacts.quantity = position.quantity
    artifacts.end_balance = balance
    artifacts.market_order = position.market_order

    logger.info("Position artifacts: %s", pformat(artifacts))

    save_to_file(artifacts=artifacts)


async def market_order_filled(
    order_update: OrderUpdate, position: Position, balance: float
) -> Tuple[Position, float]:
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

    return position, balance


async def market_order_partially_filled(order_update: OrderUpdate, position: Position):
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


async def futures_position_close(
    client: binance.AsyncClient,
    position: Position,
    balance: float,
    ui_queue: asyncio.Queue,
):
    if position.status in [State.LONG, State.LONG_EXT, State.LONG_SPECIAL]:
        _ = await close_long(
            client=client, position=position, balance=balance, ui_queue=ui_queue
        )
    elif position.status in [State.SHORT, State.SHORT_EXT, State.SHORT_SPECIAL]:
        _ = await close_short(
            client=client, position=position, balance=balance, ui_queue=ui_queue
        )


async def futures_get_position_info(
    client: binance.AsyncClient,
) -> Tuple[float, float, float]:
    """
    Retrieve the liquidation price for a given symbol on the Binance Futures trading platform.

    :param client: An instance of the Binance async client
    :type client: binance.AsyncClient
    :return: A dictionary containing the symbol, liquidation price, entry price and position amount for the given symbol
    :rtype: dict
    """
    logger.info("Enter position information")

    resp = await client.futures_position_information(symbol=SYMBOL)
    logger.info("RESP: %s", resp)
    liquidation_price = round(float(resp[0]["liquidationPrice"]), 1)
    entry_price = round(float(resp[0]["entryPrice"]), 1)
    position_amt = float(resp[0]["positionAmt"])

    logger.info("Exit position information")

    return liquidation_price, entry_price, position_amt
