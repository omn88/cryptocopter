import logging
from datetime import datetime

import os

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

# setup basic config for all loggers
logging.basicConfig(
    level=logging.INFO,
    filename="artifacts/rsi_based_futures_{}.log".format(
        now.strftime("%Y-%m-%d_%H-%M-%S")
    ),
    filemode="w",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# create a console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logging.getLogger().addHandler(console_handler)


class KivyGuiHandler(logging.Handler):
    def __init__(self, log_display_widget):
        super().__init__()
        self.widget = log_display_widget

    def emit(self, record):
        log_entry = self.format(record)
        # Ensure that the update happens on the main thread
        if self.widget:
            self.widget.text += f"\n{log_entry}"
            # Auto-scroll to the bottom
            self.widget.parent.scroll_y = 0
