import asyncio
import signal
import os
import shutil

import pandas

import logging_config  # noinspection PyUnresolvedReferences
import logging
import binance.exceptions
from binance import AsyncClient, BinanceSocketManager
from decouple import config

from constants import LEVERAGE, SYMBOL
from src.backtest.lib import get_futures_historical_data
from src import orders
from src.common.common import (
    create_directory_with_timestamp,
    insert_to_pandas,
    futures_get_balance,
)
from src.features.features import State, signals_from_features_generate
from src.orders import order_quantity_list_prepare, Position
from src.producers.producers import (
    futures_user_socket,
    kline_futures_socket,
    determine_start_position,
)
from src.strategies.rsi_special import SpecialStrategy
from src.workers.handle_order import futures_position_close
from src.workers.trading_state_machine import TradingStateMachine
from src.workers.worker import worker

import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)


async def shutdown(
    client: binance.AsyncClient,
    posix_signal: signal.Signals,
    position: orders.Position,
    balance: float,
):
    """Cleanup tasks tied to the service's shutdown."""
    logging.info("Received exit signal %s...", posix_signal.name)

    position = await futures_position_close(
        client=client, position=position, balance=balance
    )

    logging.info("Nacking outstanding messages")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    [task.cancel() for task in tasks]

    logging.info(f"Flushing metrics")
    await client.close_connection()


def register_signal_handlers(loop, client, position, balance):
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s,
            lambda s=s: asyncio.create_task(
                shutdown(
                    client=client,
                    posix_signal=s,
                    position=position,
                    balance=balance,
                )
            ),
        )


def prepare_producers(
    bsm: BinanceSocketManager, queue: asyncio.Queue, interval: str, df: pandas.DataFrame
):
    return [
        asyncio.create_task(
            kline_futures_socket(
                bsm=bsm,
                queue=queue,
                interval=interval,
                last_index=df.index[-1],
            )
        ),
        asyncio.create_task(futures_user_socket(bm=bsm, queue=queue)),
    ]


def prepare_workers(
    client: binance.AsyncClient,
    strategy,
    historical_data: pandas.DataFrame,
    position: Position,
):
    return [
        asyncio.create_task(
            worker(
                client=client,
                historical_data=historical_data,
                strategy=strategy,
                position=position,
            )
        )
    ]


async def main():

    logger.info("RSI Based Futures: Start")
    asset = "USDT"
    interval = "15m"
    logger.info(
        "Initial params: symbol %s, asset %s, interval %s" % (SYMBOL, asset, interval)
    )

    loop = asyncio.get_event_loop()

    client = await AsyncClient.create(
        api_key=config("FUTURES_API_KEY"), api_secret=config("FUTURES_API_SECRET")
    )
    logger.info("Async client created")
    bsm = BinanceSocketManager(client)
    logger.info("Binance socket manager ready")
    queue = asyncio.Queue()
    logger.info("Async FIFO Queue started")
    balance = await futures_get_balance(client=client, asset=asset)
    position = Position()

    # May want to catch other signals too
    register_signal_handlers(
        loop=loop, client=client, position=position, balance=balance
    )

    try:
        await client.futures_change_margin_type(symbol=SYMBOL, marginType="ISOLATED")
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s" % e)
    await client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)

    historical_data = await get_futures_historical_data(
        client=client,
        interval=interval,
        lookback="4320",  # 44000 is approximately one month
    )
    df = insert_to_pandas(data=historical_data)
    df = signals_from_features_generate(df=df)
    df["position"] = State.FLAT

    df = await determine_start_position(df=df, queue=queue)

    order_quantity_list = order_quantity_list_prepare()

    strategy = SpecialStrategy(
        client=client,
        balance=balance,
        order_quantity_list=order_quantity_list,
        queue=queue,
        df=df,
    )

    # tsm = TradingStateMachine(
    #     client=client,
    #     df=df,
    #     balance=balance,
    #     order_quantity_list=order_quantity_list,
    #     queue=queue,
    # )

    producers = prepare_producers(bsm=bsm, df=df, interval=interval, queue=queue)

    workers = prepare_workers(
        client=client,
        historical_data=historical_data,
        position=position,
        strategy=strategy,
    )

    await asyncio.gather(*producers, return_exceptions=True)
    await asyncio.gather(*workers, return_exceptions=True)

    # try:
    #     await asyncio.gather(*producers)
    #     await asyncio.gather(*workers)
    # except KeyboardInterrupt:
    #     await queue.put(Event(name=EventName.SENTINEL, content=KlineUpdate(kline=[])))
    #     await client.close_connection()

    # shutil.copyfile(f"{os.getcwd()}/artifacts/info.log", f"{artifacts_dir}/info.log")
    # shutil.copyfile(
    #     f"{os.getcwd()}/artifacts/list_of_orders.txt",
    #     f"{artifacts_dir}/list_of_orders.txt",
    # )


if __name__ == "__main__":

    # artifacts_dir = create_directory_with_timestamp()
    logger = logging.getLogger("main")

    try:
        asyncio.run(main())
    except asyncio.exceptions.CancelledError:
        # loop = asyncio.get_event_loop()
        logging.info("Strategy cancelled")
        # loop.close()
