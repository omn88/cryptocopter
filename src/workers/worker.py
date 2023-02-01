import asyncio
import logging
from typing import List
from pprint import pformat
import binance
import pandas
from binance.exceptions import BinanceAPIException

from src import orders
from src.common import print_last_n_rows
from src.orders import (
    Position,
    Order,
    PositionSide,
)
from src.producers import producers
from src.producers.producers import (
    Event,
    EventName,
    OrderUpdate,
    SignalUpdate,
    KlineUpdate,
)
from src.workers.handle_account import account_handle
from src.workers.handle_order import order_handle
from src.workers.handle_signal import signal_handle
from src.workers.kline_handle import kline_handle

logger = logging.getLogger("worker_main")


async def validate_order(
    client: binance.AsyncClient, symbol: str, order: Order, queue: asyncio.Queue
):
    resp = await client.futures_get_order(symbol=symbol, orderId=order.order_id)
    updated_status = resp["status"]
    realized_quantity = round(float(resp["executedQty"]), 3)
    logger.info(
        "Order: %s, realized qty: %s, status: %s",
        resp["orderId"],
        realized_quantity,
        updated_status,
    )

    if updated_status != order.status or realized_quantity != order.realized_quantity:
        order_update = OrderUpdate(
            price=round(float(resp["price"]), 1),
            quantity=round(float(resp["origQty"]), 3),
            status=updated_status,
            realized_quantity=realized_quantity,
            order_id=int(resp["orderId"]),
            last_filled_quantity=0,
        )

        await queue.put(Event(name=EventName.ORDER, content=order_update))
        logger.info(
            "Validation discrepancy status: %s -> %s, realized qty: %s -> %s",
            order.status,
            updated_status,
            order.realized_quantity,
            realized_quantity,
        )


async def validate_open_orders(
    client: binance.AsyncClient, position: Position, queue: asyncio.Queue
):
    """
    This function should validate whether there are no missed orders, hence issues in
    calculations and position handling.
    So first request for update of current position and orders should be sent and then
    the output should be parsed and compared to the current strategy state. All differences
    should be logged and handled. For example at start of the strategy, if order is filled
    immediately, there is no ORDER_TRADE_UPDATE msg coming from websocket, hence such checks
    are mandatory to be in sync with real state. First lets focus on orders on open orders!!
    """
    logger.info("Enter order validation")

    # ToDo: Add take profit order
    for order in position.orders:
        await validate_order(
            client=client, symbol=position.symbol, order=order, queue=queue
        )

    logger.info("Order validation finished")


async def worker(
    df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    historical_data: List,
    position: orders.Position,
):

    while True:
        logger.info("Current position: %s", pformat(position.current_position))
        logger.info("Orders: \n%s", pformat(position.orders))
        logger.info("Events in queue: %s", queue.qsize())
        if queue.qsize() == 0:
            logger.info("Awaiting new event...")

        event = await queue.get()
        assert isinstance(event, producers.Event)
        logger.info("New event from queue: %s", event)

        if producers.EventName.KLINE == event.name:
            assert isinstance(event.content, KlineUpdate)
            historical_data, df, position = await kline_handle(
                client=client,
                historical_data=historical_data,
                df=df,
                position=position,
                kline=event.content.kline,
            )

        elif producers.EventName.ORDER == event.name:
            assert isinstance(event.content, OrderUpdate)
            position = await order_handle(
                client=client, position=position, order_update=event.content
            )

        elif producers.EventName.ACCOUNT == event.name:
            df, position = await account_handle(df=df, position=position)

        elif producers.EventName.SIGNAL == event.name:
            assert isinstance(event.content, SignalUpdate)
            df, position = await signal_handle(
                client=client,
                df=df,
                signal_update=event.content,
                position=position,
            )

            await print_last_n_rows(df=df)

        elif producers.EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> Exiting worker")
            # await cancel_remaining_limit_orders(client=client, position=position)
            # if position.current_position.take_profit_order is not None:
            #     await cancel_order(
            #         client=client,
            #         order=position.current_position.take_profit_order,
            #         symbol=position.symbol,
            #     )
            return historical_data, df, position

        if event.name == EventName.ORDER and event.content.status in [
            client.ORDER_STATUS_FILLED,
            client.ORDER_STATUS_PARTIALLY_FILLED,
        ]:
            await validate_open_orders(client=client, position=position, queue=queue)
        logger.info("Task Done: %s", event.content)
        queue.task_done()
