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

# Set initial window size
Window.size = (960, 600)


async def fetch_trading_symbols(client) -> List[str]:
    exchange_info = await client.get_exchange_info()
    return [
        symbol["symbol"]
        for symbol in exchange_info["symbols"]
        if symbol["status"] == "TRADING"
    ]


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
    await db.create_database_if_not_exists()
    await db.create_pool()
    await db.setup_tables()

    client = BinanceClient(
        api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
    )

    symbols = await fetch_trading_symbols(client=client)
    logger.info("Symbols: %s, count: %s", symbols, len(symbols))

    app = AsyncApp(client=client, db=db, symbols=symbols)
    logger.info("Created %s", app)

    try:
        await app.async_run()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
