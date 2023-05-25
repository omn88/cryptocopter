import os


def set_kivy_log_mode(mode: str):
    os.environ["KIVY_LOG_MODE"] = mode.upper()
