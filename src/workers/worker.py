import asyncio
import logging
from typing import List

import binance

import pandas
from src import orders
from src.orders import Position, Order
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


async def print_last_n_rows(df: pandas.DataFrame, rows: int = 5):
    logger.info(
        "Last %d rows from main df: %s" % (rows, "\n%s" % df.tail(rows).to_string())
    )


async def validate_order(
    client: binance.AsyncClient, symbol: str, order: Order, queue: asyncio.Queue
):
    resp = await client.futures_get_order(symbol=symbol, orderId=order.order_id)

    updated_status = resp["status"]
    realized_quantity = resp["executedQty"]

    if updated_status == binance.AsyncClient.ORDER_STATUS_NEW:
        logger.info("Order: %s, status %s, ", order.order_id, updated_status)
        return
    elif updated_status == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED:
        logger.info("Validate order: %s, status %s, ", order.order_id, updated_status)
        if updated_status == order.status:
            logger.info("Order: %s was already filled partially", order.order_id)
            if realized_quantity == order.realized_quantity:
                logger.info(
                    "Order's: %s realized quantity has not changed.", order.order_id
                )
                return
            else:
                logger.info(
                    "Order: %s, quantity mismatch: update quantity %s, order.quantity: %s",
                    order.order_id,
                    realized_quantity,
                    order.realized_quantity,
                )

                order_update = OrderUpdate(
                    price=order.price,
                    quantity=realized_quantity - order.realized_quantity,
                    status=updated_status,
                )
                await queue.put(Event(name=EventName.ORDER, content=order_update))
                logger.info("Order trade update msg: %s", resp)
                return
        else:
            logger.info(
                "Order: %s, status changed from: %s to %s"
                % (order.order_id, order.status, updated_status)
            )
            order_update = OrderUpdate(
                price=order.price, quantity=realized_quantity, status=updated_status
            )
            await queue.put(Event(name=EventName.ORDER, content=order_update))
            return
    elif updated_status == binance.AsyncClient.ORDER_STATUS_FILLED:
        logger.info("Validate order: %s, status %s", order.order_id, updated_status)
        if updated_status == order.status:
            logger.info("Order: %s already filled: %s", order.order_id, order.status)
            return
        else:
            logger.info(
                "Order: %s, status changed from: %s to: %s",
                order.order_id,
                order.status,
                updated_status,
            )
            order_update = OrderUpdate(
                price=order.price, quantity=realized_quantity, status=updated_status
            )
            await queue.put(Event(name=EventName.ORDER, content=order_update))
            logger.info("Order trade update msg: %s", order_update)
            return

    return


async def validate_current_position(
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
        logger.info("Current position: %s", position.current_position)
        logger.info("Orders: %s", position.orders)
        logger.info("Events in queue: %s" % queue.qsize())
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
            return df, position

        await validate_current_position(client=client, position=position, queue=queue)
        logger.info("Task Done: %s", event.content)
        queue.task_done()
