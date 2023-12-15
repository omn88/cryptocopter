import os

os.environ["KIVY_LOG_MODE"] = "MIXED"
import asyncio

from kivy.core.window import Window
import logging_config  # noinspection PyUnresolvedReferences
import warnings
from kivy.lang import Builder
from src.gui.async_app import AsyncApp


warnings.simplefilter(action="ignore", category=FutureWarning)


# Set initial window size
Window.size = (960, 600)


async def main():
    app = AsyncApp()
    await app.async_run()


if __name__ == "__main__":
    asyncio.run(main())
