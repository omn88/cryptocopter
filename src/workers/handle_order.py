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

from src.gui.identifiers import PositionData, PositionStatus, StrategyData

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


async def update_take_profit_order(
    client: BinanceClient, position: Position, ui_queue: asyncio.Queue, symbol: str
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
            symbol=symbol,
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
        ui_queue=ui_queue,
        symbol=symbol,
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
    position: Position,
    balance: float,
) -> Tuple[Position, float]:
    logger.info("Position liquidation")

    loss = 0.0
    assert position.orders is not None
    for order in position.orders:
        logger.info("quantity: %s, price: %s", order.quantity, order.price)
        loss += order.quantity_stable

    balance -= round(loss, 2)

    position.state = State.FLAT

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
    client: BinanceClient,
    position: Position,
    order_update: OrderUpdate,
    balance: float,
    ui_queue: asyncio.Queue,
    symbol: str,
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
        client=client, position=position, ui_queue=ui_queue, symbol=symbol
    )
    # update_artifacts_and_save(
    #     position=position,
    #     order_update=order_update,
    #     balance=balance,
    # )

    return position, balance


async def handle_order_partially_filled(
    client: BinanceClient,
    position: Position,
    order_update: OrderUpdate,
    ui_queue: asyncio.Queue,
    symbol: str,
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
            ) = await futures_get_position_info(client=client, symbol=symbol)

            position = await update_take_profit_order(
                client=client, position=position, ui_queue=ui_queue, symbol=symbol
            )
            logger.info("Exiting update position")

    logger.info("Exit order update handle")
    return position


async def handle_order_filled(
    client: BinanceClient,
    position: Position,
    order_update: OrderUpdate,
    ui_queue: asyncio.Queue,
    symbol: str,
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
            ) = await futures_get_position_info(client=client, symbol=symbol)

            position = await update_take_profit_order(
                client=client, position=position, ui_queue=ui_queue, symbol=symbol
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


async def futures_position_close(
    client: BinanceClient,
    position: Position,
    ui_queue: asyncio.Queue,
    main_ui_queue,
    strategy_name,
    symbol: str,
):
    logger.info("FAAK position state: %s", position.state)
    if position.state in [State.LONG, State.LONG_EXT, State.LONG_SPECIAL]:
        _ = await close_long(
            client=client,
            position=position,
            ui_queue=ui_queue,
            symbol=symbol,
            main_ui_queue=main_ui_queue,
            strategy_name=strategy_name,
        )
    elif position.state in [State.SHORT, State.SHORT_EXT, State.SHORT_SPECIAL]:
        _ = await close_short(
            client=client,
            position=position,
            ui_queue=ui_queue,
            symbol=symbol,
            main_ui_queue=main_ui_queue,
            strategy_name=strategy_name,
        )


async def futures_get_position_info(
    client: BinanceClient, symbol: str
) -> Tuple[float, float, float]:
    """
    Retrieve the liquidation price for a given symbol on the Binance Futures trading platform.

    :param client: An instance of the Binance async client
    :type client: binance.AsyncClient
    :return: A dictionary containing the symbol, liquidation price, entry price and position amount for the given symbol
    :rtype: dict
    """
    logger.info("Enter position information")

    resp = await client.futures_position_information(symbol=symbol)
    logger.info("RESP: %s", resp)
    liquidation_price = round(float(resp[0]["liquidationPrice"]), 1)
    entry_price = round(float(resp[0]["entryPrice"]), 1)
    position_amt = float(resp[0]["positionAmt"])

    logger.info("Exit position information")

    return liquidation_price, entry_price, position_amt


def target_price_calculate(side: str, price: float) -> float:
    logger.info("Entering target price calculate")
    if side == PositionSide.LONG:
        target_price = round((1 + (100 / LEVERAGE / 100)) * price, 1)
    elif side == PositionSide.SHORT:
        target_price = round((1 - (100 / LEVERAGE / 100)) * price, 1)
    else:
        raise AssertionError(f"Wrong position side: {side}")

    logger.info("position side: %s, target: %s", side, target_price)
    return target_price


async def cancel_take_profit_order(
    client: BinanceClient,
    take_profit_order: Order,
    side: str,
    ui_queue: asyncio.Queue,
    symbol: str,
) -> str:
    take_profit_order.status = await cancel_order(
        client=client,
        order=take_profit_order,
        side=side,
        ui_queue=ui_queue,
        symbol=symbol,
    )
    logger.info(
        "Take profit order: %s, status: %s",
        take_profit_order.order_id,
        take_profit_order.status,
    )

    return take_profit_order.status


async def cancel_remaining_limit_orders(
    client: BinanceClient, position: Position, ui_queue: asyncio.Queue, symbol: str
) -> Tuple[Position, bool]:
    logger.info("Cancelling remaining limit orders")
    assert position.orders is not None
    new_orders_count = 0
    cancelled_orders_count = 0
    for order in position.orders:
        if order.status == ORDER_STATUS_PARTIALLY_FILLED:
            order.status = await cancel_order(
                client=client,
                order=order,
                ui_queue=ui_queue,
                side=position.side,
                symbol=symbol,
            )
            logger.info("Cancelled partially filled order_id: %s", order.order_id)
            cancelled_orders_count += 1
        elif order.status == ORDER_STATUS_NEW:
            new_orders_count += 1
            order.status = await cancel_order(
                client=client,
                order=order,
                ui_queue=ui_queue,
                side=position.side,
                symbol=symbol,
            )
            logger.info("Cancelled new order_id: %s", order.order_id)
            cancelled_orders_count += 1

    position_opened = new_orders_count != len(position.orders)

    return position, position_opened
