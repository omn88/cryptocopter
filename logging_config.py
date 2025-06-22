import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
import os

# Get the environment variable
env = os.getenv("ENVIRONMENT")

# Set the log directory
if env == "GITLAB":
    LOG_DIR = "/builds/omn88/rsi_based_futures/artifacts"
else:
    LOG_DIR = os.path.join(os.getcwd(), "artifacts")

os.makedirs(LOG_DIR, exist_ok=True)

now = datetime.now()
log_filename = os.path.join(
    LOG_DIR, f"cryptocopter_{now.strftime('%Y-%m-%d_%H-%M-%S')}.log"
)

# Clear existing root handlers
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Console handler with visible logger name and preserved native colors
console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)

# File handler (rotating logs)
file_handler = RotatingFileHandler(
    log_filename, maxBytes=32 * 1024 * 1024, backupCount=16
)
file_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s - [%(name)s] - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        console_handler,
        file_handler,
    ],
)

# Reduce noise from verbose libraries
logging.getLogger("transitions.extensions.asyncio").setLevel(logging.WARNING)
logging.getLogger("websockets.client").setLevel(logging.WARNING)
logging.getLogger("binance.streams").setLevel(logging.WARNING)
logging.getLogger("binance.ws.reconnecting_websocket").setLevel(logging.ERROR)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)  # Suppress aiosqlite debug logs


# Add WebSocket error filter to suppress keepalive timeout messages
class WebSocketErrorFilter(logging.Filter):
    """Filter to suppress noisy WebSocket keepalive timeout messages"""

    def filter(self, record):
        message = record.getMessage()
        # Suppress keepalive timeout messages
        if "keepalive ping timeout" in message:
            return False
        if (
            "BinanceWebsocketClosed" in message
            and "Connection closed. Reconnecting" in message
        ):
            return False
        if "ConnectionClosedError" in message and "keepalive ping timeout" in message:
            return False
        return True


# Apply the filter to the root logger and specific WebSocket loggers
websocket_filter = WebSocketErrorFilter()
logging.getLogger("root").addFilter(websocket_filter)
logging.getLogger("binance.ws.reconnecting_websocket").addFilter(websocket_filter)
logging.getLogger("websockets.protocol").addFilter(websocket_filter)
