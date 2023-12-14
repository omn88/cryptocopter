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

# Load the .kv file
Builder.load_file("src/gui/main.kv")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(AsyncApp().app_func())
    loop.close()
