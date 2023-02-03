import asyncio
import signal
import os
import shutil
import logging_config  # noinspection PyUnresolvedReferences
import logging
import binance.exceptions
from binance import AsyncClient, BinanceSocketManager
from decouple import config
from src.backtest.lib import get_futures_historical_data
from src import orders, features
from src.common import (
    create_directory_with_timestamp,
    insert_to_pandas,
    futures_get_balance,
)
from src.orders import futures_position_close
from src.producers.producers import (
    futures_user_socket,
    kline_futures_socket,
    determine_start_position,
)
from src.workers.worker import worker

import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)


async def shutdown(
    client: binance.AsyncClient,
    posix_signal: signal.Signals,
    current_position: orders.CurrentPosition,
    symbol: str,
):
    """Cleanup tasks tied to the service's shutdown."""
    logging.info("Received exit signal %s...", posix_signal.name)

    current_position = await futures_position_close(
        client=client, current_position=current_position, symbol=symbol
    )

    logging.info("Nacking outstanding messages")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    [task.cancel() for task in tasks]

    logging.info(f"Flushing metrics")
    await client.close_connection()


async def main():

    loop = asyncio.get_event_loop()
    # May want to catch other signals too
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(
            s,
            lambda s=s: asyncio.create_task(
                shutdown(
                    client=client,
                    posix_signal=s,
                    current_position=position.current_position,
                    symbol=position.symbol,
                )
            ),
        )

    logger.info("RSI Based Futures: Start")
    symbol = "BTCUSDT"
    asset = "USDT"
    interval = "15m"
    leverage = 25
    logger.info(
        "Initial params: symbol %s, asset %s, interval %s" % (symbol, asset, interval)
    )

    client = await AsyncClient.create(
        api_key=config("FUTURES_API_KEY"), api_secret=config("FUTURES_API_SECRET")
    )
    logger.info("Async client created")

    bm = BinanceSocketManager(client)
    logger.info("Binance socket manager ready")

    queue = asyncio.Queue()
    logger.info("Async FIFO Queue started")

    balance = await futures_get_balance(client=client, asset=asset)

    try:
        await client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s" % e)
    await client.futures_change_leverage(symbol=symbol, leverage=leverage)

    position = orders.Position(symbol=symbol, balance=balance)

    logger.info("Order quantity list: \n%s", position.order_quantity_list)

    historical_data = await get_futures_historical_data(
        client=client,
        symbol=symbol,
        interval=interval,
        lookback="4320",  # 44000 is approximately one month
    )

    df = insert_to_pandas(data=historical_data)
    df = features.signals_from_features_generate(df=df)
    df["position"] = features.Signals.FLAT

    df = await determine_start_position(df=df, queue=queue)

    producers = [
        asyncio.create_task(
            kline_futures_socket(
                symbol=symbol,
                bm=bm,
                queue=queue,
                interval=interval,
                last_index=df.index[-1],
            )
        ),
        asyncio.create_task(futures_user_socket(bm=bm, queue=queue)),
    ]

    workers = [
        asyncio.create_task(
            worker(
                df=df,
                queue=queue,
                client=client,
                historical_data=historical_data,
                position=position,
            )
        )
    ]

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
