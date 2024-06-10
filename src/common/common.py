import errno
import logging
import os
from datetime import datetime, timezone
import pytz
import uuid
from src.common.identifiers.common import Signal, BinanceClient
from src.common.identifiers.futures import State

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

    # Create a timezone-aware datetime object in UTC
    utc_time = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)

    # Convert to Polish timezone
    poland_time = utc_time.astimezone(pytz.timezone("Europe/Warsaw"))

    # Format the datetime object to a string with the desired format
    formatted_poland_time = poland_time.strftime("%Y-%m-%d %H:%M:%S")

    return formatted_poland_time
