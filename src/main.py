import asyncio

import binance.exceptions
import pandas
from binance import AsyncClient, BinanceSocketManager
import errno
import os
from datetime import datetime
import logging.config
import yaml
import shutil
from decouple import config
import lib
import orders

import features

from producers import (
    futures_user_socket,
    kline_futures_socket,
    determine_start_position,
)
from workers import worker

import warnings

warnings.simplefilter(action="ignore", category=FutureWarning)


def create_directory_with_timestamp():
    mydir = os.path.join(
        os.getcwd() + "/artifacts", datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    )
    try:
        os.makedirs(mydir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # This was not a "directory exist" error..

    return mydir


async def main():

    logger.info("RSI Based Futures: Start")
    symbol = "BTCUSDT"
    asset = "USDT"
    interval = "15m"
    leverage = 25
    logger.info(
        "Initial params: symbol %s, asset %s, interval %s" % (symbol, asset, interval)
    )

    # Choose params, symbol, interval, saldo, FEATURES
    # Download data for 15min intervals 1050 intervals back
    # Apply indicators, features and create signals and desired position.
    # Wait for another row and in the meantime manage position(recalculate, open, close)
    # Based on new row's signals or info from socket, manage position

    # Queue to be created with producer consumer pattern (worker?)
    # In general output from new row will create signals as well as real time data from user socket.
    # Worker will manage

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
    saldo = float(balance[6]["balance"])

    logger.info("Asset: %s, Saldo: %d " % (balance[6]["asset"], saldo))

    try:
        await client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s" % e)
    await client.futures_change_leverage(symbol=symbol, leverage=leverage)

    position = orders.Position(symbol=symbol)

    # logger.info("Server time %s" % await client.get_server_time())
    #
    # logger.info("My time %s" % time.time())

    df = await lib.get_futures_historical_data(
        client=client,
        symbol=symbol,
        interval=interval,
        lookback="3360",  # 44000 is approximately one month
    )
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
                start_df=df,
                queue=queue,
                client=client,
                symbol=symbol,
                interval=interval,
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

            # wait for the remaining tasks to be processed
            await queue.join()

            await asyncio.gather(*workers)

    await client.close_connection()
    # shutil.copyfile(f"{os.getcwd()}/artifacts/info.log", f"{artifacts_dir}/info.log")
    # shutil.copyfile(
    #     f"{os.getcwd()}/artifacts/list_of_orders.txt",
    #     f"{artifacts_dir}/list_of_orders.txt",
    # )


if __name__ == "__main__":

    artifacts_dir = create_directory_with_timestamp()
    with open("src/logging.yaml", "r") as f:
        logging_conf = yaml.safe_load(f.read())
        logging.config.dictConfig(logging_conf)

    logger = logging.getLogger("main")

    asyncio.run(main())
