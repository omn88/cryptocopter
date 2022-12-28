import asyncio
import logging

import binance

import pandas
from src import orders
from src.producers import producers
from src.workers.handle_account import account_handle
from src.workers.handle_order import order_handle
from src.workers.handle_signal import signal_handle, kline_handle

logger = logging.getLogger("worker_main")


async def print_last_n_rows(df: pandas.DataFrame, rows: int = 5):
    logger.info(
        "Last %d rows from main df: %s" % (rows, "\n%s" % df.tail(rows).to_string())
    )


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

        logger.info("Done, Awaiting new Event")
        queue.task_done()
