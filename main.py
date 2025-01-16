"""
This is the main module of the Cryptocopter project.

This module initializes the Kivy application and starts the main event loop. It sets up
the initial window size and configures the logging settings. It also defines the main
asynchronous function that creates an instance of AsyncApp, which is responsible for
managing the trading systems and the user interface.

Functions:
    main: The main function of the module. It creates an instance of AsyncApp and starts
    the application's main event loop.
"""

import os
import asyncio
from typing import List
import warnings
import logging_config  # noinspection PyUnresolvedReferences
import logging
from decouple import Config, RepositoryEnv
from src.common.identifiers.common import BinanceClient
from src.common.portfolio import fetch_initial_balances
from src.common.symbol_info import fetch_symbol_info

os.environ["KIVY_LOG_MODE"] = "MIXED"

from kivy.core.window import Window
from src.gui.asyncapp import AsyncApp
from src.common.database import Database

warnings.simplefilter(action="ignore", category=FutureWarning)


logger = logging.getLogger("main")


# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))

DB_CONFIG_FILE = "config/.db_config"
config_db = Config(RepositoryEnv(DB_CONFIG_FILE))

window_width = 1200  # Set your desired width
window_height = 640  # Set your desired height

# Set window size
Window.size = (window_width, window_height)


async def main():
    """
    The main function of the module.

    This function creates an instance of AsyncApp and starts the application's main event loop.

    Returns:
        None
    """

    db = Database(
        host=config_db("DB_HOST"),
        port=int(config_db("DB_PORT")),
        user=config_db("DB_USER"),
        password=config_db("DB_PASSWORD"),
        name=config_db("DB_NAME"),
    )
    await db.initialize()
    db.run_db_task(db.create_database_if_not_exists())
    db.run_db_task(db.create_pool())
    db.run_db_task(db.setup_tables())

    client = BinanceClient(
        api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
    )

    symbols_info = await fetch_symbol_info(client=client)
    balances = await fetch_initial_balances(client=client)

    app = AsyncApp(client=client, db=db, symbols_info=symbols_info, balances=balances)

    logger.info("Created %s", app)

    try:
        await app.async_run()
    finally:
        await client.close_connection()
        await db.close_pool()
        logger.info("FINITO")


if __name__ == "__main__":
    asyncio.run(main())
