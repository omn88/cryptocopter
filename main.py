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
import kivy_config  # noinspection PyUnresolvedReferences
import logging_config  # noinspection PyUnresolvedReferences
import logging
from decouple import Config, RepositoryEnv
from src.broker.exchange_manager import ExchangeManager
from src.portfolio.usd_price_resolver import UsdPriceResolver

os.environ["KIVY_NO_CONSOLELOG"] = "1"
from kivy.core.window import Window
from src.gui.app.asyncapp import AsyncApp
from src.database import Database

warnings.simplefilter(action="ignore", category=FutureWarning)


logger = logging.getLogger("main")


# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))

window_width = 1200  # Set your desired width
window_height = 640  # Set your desired height

# Set window size
Window.size = (window_width, window_height)


async def main() -> None:
    """
    The main function of the module.

    This function creates an instance of AsyncApp and starts the application's main event loop.

    Returns:
        None
    """
    # Initialize SQLite database
    db = Database()  # Uses default "trading.db" file

    # Initialize exchange manager for multi-exchange support
    exchange_manager = ExchangeManager(config=config_env)
    initialization_results = await exchange_manager.initialize_all()

    logger.info(f"Exchange initialization results: {initialization_results}")

    # Get default exchange client (Binance for backward compatibility)
    default_exchange = "binance" if initialization_results.get("binance") else "kraken"
    client = exchange_manager.get_client(default_exchange)

    if client is None:
        logger.error("No exchange client available. Please check API credentials.")
        return

    # Fetch symbols from default exchange
    symbols = await client.fetch_symbols()

    price_resolver = UsdPriceResolver(
        client=(
            client.get_native_client()
            if hasattr(client, "get_native_client")
            else client
        ),
        symbols=symbols,
    )
    await price_resolver.fetch_all_prices()

    app = AsyncApp(
        client=(
            client.get_native_client()
            if hasattr(client, "get_native_client")
            else client
        ),
        db=db,
        price_resolver=price_resolver,
        exchange_manager=exchange_manager,
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
            if hasattr(client, "close_connection"):
                await client.close_connection()
        except Exception as e:
            logger.error(f"Error closing client connection: {e}")

        try:
            await exchange_manager.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up exchange manager: {e}")

        try:
            await db.close()
        except Exception as e:
            logger.error(f"Error closing database pool: {e}")

        logger.info("FINITO")


if __name__ == "__main__":
    asyncio.run(main())
