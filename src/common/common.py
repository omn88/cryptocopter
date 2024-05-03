import errno
import logging
import os
from datetime import datetime
import pytz
import uuid
from src.common.identifiers.futures import Signal, State, BinanceClient

logger = logging.getLogger("common")


def create_directory_with_timestamp():
    mydir = os.path.join(
        os.getcwd() + "/artifacts",
        datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
    )
    try:
        os.makedirs(mydir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise  # This was not a "directory exist" error..

    return mydir


async def futures_get_balance(client: BinanceClient, asset: str) -> float:
    account_balance = await client.futures_account_balance(asset=asset)
    for account in account_balance:
        if account["asset"] == asset:
            balance = round(float(account["balance"]), 2)
            logger.info("Balance %s: %s", account["asset"], balance)
            return balance

    raise KeyError(f"Asset: {asset} not found in account balance")


async def get_balance(client: BinanceClient, asset: str) -> float:
    account_balance = await client.futures_account_balance(asset=asset)
    for account in account_balance:
        if account["asset"] == asset:
            balance = round(float(account["balance"]), 2)
            logger.info("Balance %s: %s", account["asset"], balance)
            return balance

    raise KeyError(f"Asset: {asset} not found in account balance")


def signal_to_state(signal: Signal) -> State:
    return State(signal.value)


def convert_time(timestamp):
    # Binance timestamp is in milliseconds, convert it to seconds
    timestamp_s = timestamp / 1000

    # Create datetime object in UTC
    utc_time = datetime.utcfromtimestamp(timestamp_s)

    # Add timezone information
    utc_time = utc_time.replace(tzinfo=pytz.utc)

    # Convert to Polish timezone
    poland_time = utc_time.astimezone(pytz.timezone("Europe/Warsaw"))

    # Format the datetime object to a string with desired format
    formatted_poland_time = poland_time.strftime("%Y-%m-%d %H:%M:%S")

    return formatted_poland_time


def generate_position_id(strategy_name):
    current_time = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex
    return f"{strategy_name}_{current_time}_{unique_id}"
