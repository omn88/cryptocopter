import logging
from datetime import datetime

from logging.handlers import RotatingFileHandler
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
# Set a higher logging level for transitions.extensions.asyncio to suppress INFO logs
logging.getLogger("transitions.extensions.asyncio").setLevel(logging.WARNING)

# Set a higher logging level for transitions.extensions.asyncio to suppress INFO logs
logging.getLogger("websockets.client").setLevel(logging.WARNING)
