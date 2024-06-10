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
from src.common.identifiers.common import BinanceClient

os.environ["KIVY_LOG_MODE"] = "MIXED"

from kivy.core.window import Window
from src.gui.asyncapp import AsyncApp
from src.common.database import Database

warnings.simplefilter(action="ignore", category=FutureWarning)


logger = logging.getLogger("main")


# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config = Config(RepositoryEnv(DOTENV_FILE))

# Set initial window size
Window.size = (960, 600)


async def main():
    """
    The main function of the module.

    This function creates an instance of AsyncApp and starts the application's main event loop.

    Returns:
        None
    """

    db = Database(
        host=config("DB_HOST"),
        port=int(config("DB_PORT")),
        user=config("DB_USER"),
        password=config("DB_PASSWORD"),
        db=config("DB_NAME"),
    )

    await db.create_pool()
    await db.setup_tables()

    app = AsyncApp(
        client=BinanceClient(
            api_key=config("API_KEY"), api_secret=config("API_SECRET")
        ),
        db=db,
    )
    logger.info("Created %s", app)

    try:
        await app.async_run()
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
