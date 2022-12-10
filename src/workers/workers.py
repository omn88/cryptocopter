import asyncio
import logging

import binance

import pandas
from src import orders, features
from src.backtest import lib
from src.producers import producers
from src.workers.account import account_handle
from src.workers.order import order_handle
from src.workers.signal import signal_handle

logger = logging.getLogger("worker")


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
            logger.info("Entering Kline handling")
            # await print_last_n_rows(df=df)

            temp_df = await lib.get_futures_historical_data(
                client=client,
                symbol=symbol,
                interval=interval,
                lookback="3360",  # 44000 is approximately one month
            )
            temp_df = features.signals_from_features_generate(df=temp_df)
            temp_df["position"] = df.at[df.index[-1], "position"]
            kline_signal = temp_df.iloc[-1]["signal"]
            if kline_signal == 0:
                kline_signal = features.Signals.NULL

            logger.info("Kline produced new signal: %s" % kline_signal.value)

            df = df.append(temp_df.iloc[-1])
            await print_last_n_rows(df=df)

            df, position = await signal_handle(
                client=client,
                df=df,
                signal=kline_signal,
                position=position,
                entry_price=df.at[df.index[-1], "Close"],
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
                signal=event.content["last_signal"],
                position=position,
                entry_price=event.content["last_signal_close_price"],
            )

            await print_last_n_rows(df=df)

        logger.info("Done, Awaiting new Event")
        queue.task_done()
