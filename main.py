import asyncio

from kivy.core.window import Window
import logging_config  # noinspection PyUnresolvedReferences
import warnings

from src.gui.async_app import AsyncApp

warnings.simplefilter(action="ignore", category=FutureWarning)


# Set initial window size
Window.size = (960, 600)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(AsyncApp().app_func())
    loop.close()
