import asyncio
from binance import AsyncClient, BinanceSocketManager
import errno
import os
from datetime import datetime
import logging.config
import yaml
import shutil
from decouple import config
import lib

import features

from producers import (
    futures_user_socket,
    kline_futures_socket,
    determine_start_position,
)
from workers import worker


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

    logger.info("Start")
    symbol = "BTCUSDT"
    asset = "USDT"
    interval = "15m"

    # Choose params, symbol, interval, saldo, FEATURES
    # Download data for 15min intervals 1050 intervals back
    # Apply indicators, features and create signals and desired position.
    # Wait for another row and in the meantime manage position(recalculate, open, close)
    # Based on new row's signals or info from socket, manage position

    # Queue to be created with producer consumer pattern (worker?)
    # In general output from new row will create signals as well as real time data from user socket.
    # Worker will manage

    client = await AsyncClient.create(
        api_key=config("API_KEY"), api_secret=config("API_SECRET")
    )
    bm = BinanceSocketManager(client)

    balance = await client.futures_account_balance(asset=asset)
    assert asset == balance[6]["asset"]
    saldo = float(balance[6]["balance"])

    logger.info("Asset to: %s, Saldo: %d " % (balance[6]["asset"], saldo))

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

    df["position"] = 0

    df, start_position = determine_start_position(df=df)

    assert isinstance(start_position, features.Signals)

    logger.info("Start df: %s" % df.to_string())

    logger.info("Start position: %s" % start_position)

    queue = asyncio.Queue()

    await queue.put(start_position)

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
                saldo=saldo,
            )
        )
    ]

    # with both producers and consumers running, wait for
    # the producers to finish
    await asyncio.gather(*producers)
    print("---- done producing")

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
