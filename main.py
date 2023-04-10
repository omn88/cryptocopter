import asyncio
import signal
from typing import List, Tuple
import pandas
import logging
import binance.exceptions
from binance import AsyncClient, BinanceSocketManager
from decouple import config

from constants import LEVERAGE, SYMBOL, ASSET, INTERVAL
from src.backtest.lib import get_futures_historical_data
from src.common import orders
from src.common.common import (
    create_directory_with_timestamp,
    insert_to_pandas,
    futures_get_balance,
)
from src.features.features import State, signals_from_features_generate
from src.common.orders import order_quantity_list_prepare, Position
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
import os
import shutil
import logging_config  # noinspection PyUnresolvedReferences

warnings.simplefilter(action="ignore", category=FutureWarning)


logger = logging.getLogger("main")


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
    tsm: TradingStateMachine,
    historical_data: List,
    position: Position,
    queue: asyncio.Queue,
):
    return [
        asyncio.create_task(
            worker(
                client=client,
                historical_data=historical_data,
                tsm=tsm,
                position=position,
                queue=queue,
            )
        )
    ]


async def prepare_initial_df(
    client: binance.AsyncClient, interval: str
) -> Tuple[pandas.DataFrame, List]:
    historical_data = await get_futures_historical_data(
        client=client,
        interval=interval,
        lookback="4320",  # 44000 is approximately one month
    )
    df = insert_to_pandas(data=historical_data)
    df = signals_from_features_generate(df=df)
    df["position"] = State.FLAT

    return df, historical_data


async def change_margin_type(client: binance.AsyncClient) -> None:
    try:
        await client.futures_change_margin_type(symbol=SYMBOL, marginType="ISOLATED")
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s" % e)


async def create_async_client() -> binance.AsyncClient:
    client = await AsyncClient.create(
        api_key=config("FUTURES_API_KEY"), api_secret=config("FUTURES_API_SECRET")
    )
    logger.info("Async client created")

    return client


async def create_socket_manager(client: binance.AsyncClient) -> BinanceSocketManager:
    bsm = BinanceSocketManager(client)
    logger.info("Binance socket manager ready")

    return bsm


async def create_async_queue() -> asyncio.Queue:
    queue = asyncio.Queue()
    logger.info("Async FIFO Queue started")

    return queue


async def main():

    logger.info(
        "RSI Based Futures: Start. Initial parameters: symbol %s, asset %s, interval %s",
        SYMBOL,
        ASSET,
        INTERVAL,
    )
    loop = asyncio.get_event_loop()

    client = await create_async_client()
    bsm = await create_socket_manager(client=client)
    queue = await create_async_queue()
    balance = await futures_get_balance(client=client, asset=ASSET)
    position = Position()

    register_signal_handlers(
        loop=loop, client=client, position=position, balance=balance
    )

    await change_margin_type(client=client)
    await client.futures_change_leverage(symbol=SYMBOL, leverage=LEVERAGE)

    df, historical_data = await prepare_initial_df(client=client, interval=INTERVAL)
    df = await determine_start_position(df=df, queue=queue)

    # Strategy returns trading state machine
    tsm = SpecialStrategy(
        client=client,
        balance=balance,
        order_quantity_list=order_quantity_list_prepare(),
        queue=queue,
        df=df,
    )

    await asyncio.gather(
        *prepare_producers(bsm=bsm, df=df, interval=INTERVAL, queue=queue),
        *prepare_workers(
            client=client,
            historical_data=historical_data,
            position=position,
            tsm=tsm,
            queue=queue,
        ),
        return_exceptions=True,
    )

    # shutil.copyfile(f"{os.getcwd()}/artifacts/info.log", f"{artifacts_dir}/info.log")
    # shutil.copyfile(
    #     f"{os.getcwd()}/artifacts/list_of_orders.txt",
    #     f"{artifacts_dir}/list_of_orders.txt",
    # )


if __name__ == "__main__":

    # artifacts_dir = create_directory_with_timestamp()

    try:
        asyncio.run(main())
    except asyncio.exceptions.CancelledError:
        logging.info("Strategy cancelled")
