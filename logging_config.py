import logging
from datetime import datetime

from logging.handlers import RotatingFileHandler
import os

os.environ["KIVY_LOG_MODE"] = "MIXED"
from kivy.clock import Clock

# Get the environment variable
env = os.getenv("ENVIRONMENT")


# Set the log directory based on the environment
if env == "GITLAB":
    LOG_DIR = "/builds/omn88/rsi_based_futures/artifacts"
else:
    LOG_DIR = os.path.join(os.getcwd(), "artifacts")

# Create the directory if it doesn't exist
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# get current date and time
now = datetime.now()
log_filename = os.path.join(
    LOG_DIR, f"cryptocopter_{now.strftime('%Y-%m-%d_%H-%M-%S')}.log"
)

# Configure the main logger with a basic configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Create a rotating file handler
file_handler = RotatingFileHandler(
    log_filename, maxBytes=32 * 1024 * 1024, backupCount=16
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logging.getLogger().addHandler(file_handler)


# create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logging.getLogger().addHandler(console_handler)

# Set a higher logging level for transitions.extensions.asyncio to suppress INFO logs
logging.getLogger("transitions.extensions.asyncio").setLevel(logging.WARNING)

# Set a higher logging level for transitions.extensions.asyncio to suppress INFO logs
logging.getLogger("websockets.client").setLevel(logging.WARNING)


class KivyGuiHandler(logging.Handler):
    def __init__(self, log_display_widget):
        super().__init__()
        self.widget = log_display_widget

    def emit(self, record):
        log_entry = self.format(record)
        # Ensure that the update happens on the main thread
        if self.widget:
            Clock.schedule_once(lambda dt: self.update_widget(log_entry), 0)

    def update_widget(self, log_entry):
        self.widget.text += f"\n{log_entry}"
        # Auto-scroll to the bottom
        if self.widget.parent:
            self.widget.parent.scroll_y = 0


class StrategyLogger:
    def __init__(self, name):
        self.logger = logging.getLogger(name)

    def add_handler(self, handler):
        self.logger.addHandler(handler)

    def set_level(self, level):
        self.logger.setLevel(level)

    def info(self, message, *args, **kwargs):
        if self.logger.isEnabledFor(logging.INFO):
            self.logger.info(message, *args)

    def debug(self, message, *args, **kwargs):
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(message, *args)

    def error(self, message, *args, **kwargs):
        if self.logger.isEnabledFor(logging.ERROR):
            self.logger.error(message, *args)


def setup_logging_handler(strategy_logger: StrategyLogger, log_display_widget) -> None:
    """Sets up a logging handler for a strategy.

    Parameters:
        strategy_logger (Logger): The logger to set up the handler for.
        log_display_widget (Widget): The widget to display the logs in.
    """
    gui_log_handler = KivyGuiHandler(log_display_widget)

    gui_log_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    gui_log_handler.setFormatter(formatter)

    strategy_logger.add_handler(gui_log_handler)
    strategy_logger.debug("Logging handler configured with success")
