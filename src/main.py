import asyncio

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

import features

from producers import futures_user_socket, kline_futures_socket
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


def signals_from_features_generate(df: pandas.DataFrame) -> pandas.DataFrame:
    df = features.rsi_indicator_apply(df=df)
    df, conditions_basic, signals_basic = features.rsi_signal_basic_generate(df=df)
    df, conditions_extended, signals_extended = features.rsi_signal_extended_generate(
        df=df
    )

    return features.combined_signals_generate(
        df=df,
        condition_lists=[conditions_basic, conditions_extended],
        choice_lists=[signals_basic, signals_extended],
    )


def determine_start_position(df: pandas.DataFrame) -> features.Signals:
    signal = None
    last_signal = None
    last_signal_close_price = 0

    for index, row in df[::-1].iterrows():
        if row["signal"] != 0:
            last_signal = row["signal"]
            last_signal_close_price = row["Close"]

            break
        else:
            last_signal = features.Signals.FLAT

    latest_close = df.iloc[-1]["Close"]

    if last_signal in [features.Signals.LONG, features.Signals.LONG_20]:
        if latest_close < last_signal_close_price:
            signal = last_signal
        else:
            signal = features.Signals.FLAT

    if last_signal in [features.Signals.SHORT, features.Signals.SHORT_80]:
        if latest_close > last_signal_close_price:
            signal = last_signal
        else:
            signal = features.Signals.FLAT

    return signal


async def main():

    symbol = "BTCUSDT"
    interval = "15m"

    # Choose params, symbol, interval, saldo, FEATURES
    # Download data for 15min intervals 1050 intervals back
    # Apply indicators, features and create signals and desired position.
    # Wait for another row and in the meantime manage position(recalculate, open, close)
    # Based on new row's signals or info from socket, manage position

    # Queue to be created with producer consumer pattern (worker?)
    # In general output from new row will create signals as well as real time data from user socket.
    # Worker will manage

    logger.info("Start")
    client = await AsyncClient.create(
        api_key=config("API_KEY"), api_secret=config("API_SECRET")
    )
    bm = BinanceSocketManager(client)

    df = await lib.get_futures_historical_data(
        client=client,
        symbol=symbol,
        interval=interval,
        lookback="1680",  # 44000 is approximately one month
    )
    df = signals_from_features_generate(df=df)

    first_signal = determine_start_position(df=df)

    # logger.info(df.to_string())
    #
    # logger.info(signal)

    queue = asyncio.Queue()

    await queue.put(first_signal)

    producers = [
        asyncio.create_task(
            kline_futures_socket(symbol=symbol, bm=bm, queue=queue, interval=interval)
        ),
        asyncio.create_task(futures_user_socket(bm=bm, queue=queue)),
        asyncio.create_task(send_log()),
    ]

    workers = [asyncio.create_task(worker(queue)) for _ in range(len(producers))]

    # with both producers and consumers running, wait for
    # the producers to finish
    await asyncio.gather(*producers)
    print("---- done producing")

    # wait for the remaining tasks to be processed
    await queue.join()

    # cancel the consumers, which are now idle
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
