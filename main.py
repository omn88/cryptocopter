import asyncio
import os
import shutil
import logging_config  # noinspection PyUnresolvedReferences
import logging
import binance.exceptions
from binance import AsyncClient, BinanceSocketManager
import yaml
from decouple import config
from src.backtest.lib import get_futures_historical_data
from src import orders, features
from src.common import create_directory_with_timestamp, insert_to_pandas
from src.producers.producers import (
    futures_user_socket,
    kline_futures_socket,
    determine_start_position,
)
from src.workers.worker import worker

import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)


async def main():

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
    logger.info("FIFO Queue started")

    balance = await client.futures_account_balance(asset=asset)
    assert asset == balance[6]["asset"]
    saldo = round(float(balance[6]["balance"]), 2)

    logger.info("Asset: %s, Saldo: %s " % (balance[6]["asset"], saldo))

    try:
        await client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s" % e)
    await client.futures_change_leverage(symbol=symbol, leverage=leverage)

    position = orders.Position(symbol=symbol, saldo=saldo)

    # logger.info("Server time %s" % await client.get_server_time())
    #
    # logger.info("My time %s" % time.time())

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

    cancelled = False

    while True:
        if cancelled:
            break
        else:
            # with both producers and consumers running, wait for
            # the producers to finish
            await asyncio.gather(*producers)
            logger.info("---- done producing")

            await asyncio.gather(*workers)

    await client.close_connection()
    # shutil.copyfile(f"{os.getcwd()}/artifacts/info.log", f"{artifacts_dir}/info.log")
    # shutil.copyfile(
    #     f"{os.getcwd()}/artifacts/list_of_orders.txt",
    #     f"{artifacts_dir}/list_of_orders.txt",
    # )


if __name__ == "__main__":

    # artifacts_dir = create_directory_with_timestamp()
    logger = logging.getLogger("main")

    asyncio.run(main())
