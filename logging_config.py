import logging
from datetime import datetime

# get current date and time
now = datetime.now()

# setup basic config for all loggers
logging.basicConfig(
    level=logging.DEBUG,
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
