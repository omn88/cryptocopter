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
from decouple import config
from src.common.identifiers import BinanceClient

os.environ["KIVY_LOG_MODE"] = "MIXED"

from kivy.core.window import Window
from src.gui.asyncapp import AsyncApp

warnings.simplefilter(action="ignore", category=FutureWarning)


logger = logging.getLogger("main")

# Set initial window size
Window.size = (960, 600)


async def main():
    """
    The main function of the module.

    This function creates an instance of AsyncApp and starts the application's main event loop.

    Returns:
        None
    """

    app = AsyncApp(
        client=BinanceClient(
            api_key=config("FUTURES_API_KEY"), api_secret=config("FUTURES_API_SECRET")
        )
    )
    logger.info("Created %s", app)
    await app.async_run()


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
