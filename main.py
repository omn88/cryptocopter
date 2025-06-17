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
import warnings
import logging_config  # noinspection PyUnresolvedReferences
import logging
from decouple import Config, RepositoryEnv
from src.identifiers import BinanceClient
from src.portfolio.portfolio import fetch_initial_balances
from src.common.symbol_info import fetch_symbol_info
from src.portfolio.usd_price_resolver import UsdPriceResolver

os.environ["KIVY_NO_CONSOLELOG"] = "1"
from kivy.core.window import Window
from src.gui.asyncapp import AsyncApp
from src.database import Database

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

    client = BinanceClient(
        api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
    )

    symbols_info = await fetch_symbol_info(client=client)
    price_resolver = UsdPriceResolver(client=client, symbols_info=symbols_info)
    await price_resolver.fetch_all_prices()
    balances = await fetch_initial_balances(client=client, resolver=price_resolver)

    app = AsyncApp(
        client=client,
        db=db,
        symbols_info=symbols_info,
        balances=balances,
        price_resolver=price_resolver,
    )

    logger.info("Created %s", app)

    try:
        await app.async_run()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down gracefully...")
    except Exception as e:
        logger.error(f"Unexpected error in main application: {e}")
    finally:
        try:
            await client.close_connection()
        except Exception as e:
            logger.error(f"Error closing client connection: {e}")

        try:
            db.close_pool()
        except Exception as e:
            logger.error(f"Error closing database pool: {e}")

        logger.info("FINITO")


if __name__ == "__main__":
    asyncio.run(main())
