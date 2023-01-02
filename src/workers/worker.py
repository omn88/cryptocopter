import asyncio
import logging
from typing import List

import binance

import pandas
from src import orders
from src.features import Signals
from src.orders import Position, Order
from src.producers import producers
from src.producers.producers import Event, EventName
from src.workers.handle_account import account_handle
from src.workers.handle_order import order_handle
from src.workers.handle_signal import signal_handle, kline_handle

logger = logging.getLogger("worker_main")


async def print_last_n_rows(df: pandas.DataFrame, rows: int = 5):
    logger.info(
        "Last %d rows from main df: %s" % (rows, "\n%s" % df.tail(rows).to_string())
    )


async def validate_order(
    client: binance.AsyncClient, symbol: str, order: Order, queue: asyncio.Queue
):

    resp = await client.get_order(symbol=symbol, orderId=order.order_id)
    logger.info("Validate order: %s", resp["orderId"])

    if resp["status"] == binance.AsyncClient.ORDER_STATUS_NEW:
        logger.info(
            "Validate order: %s, status %s, " % (resp["orderId"], resp["status"])
        )
        return order
    elif resp["status"] == binance.AsyncClient.ORDER_STATUS_PARTIALLY_FILLED:
        logger.info(
            "Validate order: %s, status %s, " % (resp["orderId"], resp["status"])
        )
        if resp["status"] == order.status:
            if resp["q"] == order.quantity:
                return order
            else:
                logger.info(
                    "Validate order: %s, response quantity %s, order.quantity: %s"
                    % (resp["orderId"], resp["q"], order.quantity)
                )
                await queue.put(Event(name=EventName.ORDER, content=resp))
                return order
        else:
            logger.info(
                "Validate order: %s, response status: %s, order.status: %s"
                % (resp["orderId"], resp["status"], order.status)
            )
            await queue.put(Event(name=EventName.ORDER, content=resp))
            return order
    elif resp["status"] == binance.AsyncClient.ORDER_STATUS_FILLED:
        logger.info(
            "Validate order: %s, status %s, " % (resp["orderId"], resp["status"])
        )
        if resp["status"] == order.status:
            return order
        else:
            logger.info(
                "Validate order: %s, response status: %s, order.status: %s"
                % (resp["orderId"], resp["status"], order.status)
            )
            await queue.put(Event(name=EventName.ORDER, content=resp))
            return order

    return order


async def validate_current_position(client: binance.AsyncClient, position: Position):
    """
    This function should validate whether there are no missed orders, hence issues in
    calculations and position handling.
    So first request for update of current position and orders should be sent and then
    the output should be parsed and compared to the current strategy state. All differences
    should be logged and handled. For example at start of the strategy, if order is filled
    immediately, there is no ORDER_TRADE_UPDATE msg coming from websocket, hence such checks
    are mandatory to be in sync with real state. First lets focus on orders on open orders!!
    """

    for order in position.orders:
        await validate_order(client=client, symbol=position.symbol, order=order)


async def worker(
    df: pandas.DataFrame,
    queue: asyncio.Queue,
    client: binance.AsyncClient,
    symbol: str,
    interval: str,
    position: orders.Position,
):
    while True:
        logger.info("Entering worker")
        logger.info("queue size: %s" % queue.qsize())
        event = await queue.get()
        assert isinstance(event, producers.Event)

        if producers.EventName.KLINE == event.name:
            df, position = await kline_handle(
                client=client,
                symbol=symbol,
                interval=interval,
                df=df,
                position=position,
            )

        elif producers.EventName.ORDER == event.name:
            position = await order_handle(
                client=client, position=position, order_update=event.content
            )

        elif producers.EventName.ACCOUNT == event.name:
            logger.info("Account update: %s" % event.content)
            df, position = await account_handle(df=df, position=position)
            logger.info("New DF: %s, new position: %s" % (df, position))

        elif producers.EventName.SIGNAL == event.name:
            logger.info("Event signal: %s" % event.content)
            df, position = await signal_handle(
                client=client,
                df=df,
                signal=event.content["signal"],
                position=position,
                entry_price=event.content["price"],
            )

            await print_last_n_rows(df=df)

        elif producers.EventName.SENTINEL == event.name:
            logger.info("SENTINEL -> exiting worker")
            return df, position

        await validate_current_position(client=client, position=position)

        logger.info("Done, Awaiting new Event")
        queue.task_done()
