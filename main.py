import asyncio
from binance import AsyncClient, BinanceSocketManager
import errno
import os
from datetime import datetime
import logging.config
import yaml
import shutil
import gui

import strategy_script
from socket_management import ticker_socket, user_socket
from strategy_script import Strategy


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
    client = await AsyncClient.create(
        api_key="oA6bheAMqRK8DGAKNnj2duGzIQepkOhhjz2OIJjgwRDVMbvF1uwuFOXhMA2Au8Lk",
        api_secret="i1C5VVg6W17vHTo5rQ6FJqZaP0e6eXc9k9NYZh0sUq6lRb4yN6mj1CKSw9jLld84",
    )
    bm = BinanceSocketManager(client)
    # strategy = Strategy(client, bm)

    await asyncio.gather(
        *[
            # strategy_script.rsi_based_futures(period=14, interval="15m"),
            # ticker_socket(bm=bm, strategy=strategy),
            # gui(strategy=strategy),
            # user_socket(bm, strategy),
            gui.gui()
        ]
    )

    await client.close_connection()
    # shutil.copyfile(f"{os.getcwd()}/artifacts/info.log", f"{artifacts_dir}/info.log")
    # shutil.copyfile(
    #     f"{os.getcwd()}/artifacts/list_of_orders.txt",
    #     f"{artifacts_dir}/list_of_orders.txt",
    # )


if __name__ == "__main__":

    artifacts_dir = create_directory_with_timestamp()
    with open("logging.yaml", "r") as f:
        config = yaml.safe_load(f.read())
        logging.config.dictConfig(config)

    logger = logging.getLogger("main")

    asyncio.run(main())
