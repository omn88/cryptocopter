import os
from datetime import datetime
import pytz


def set_kivy_log_mode(mode: str):
    os.environ["KIVY_LOG_MODE"] = mode.upper()
