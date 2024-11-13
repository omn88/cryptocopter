import errno
import logging
import os
from datetime import datetime, timezone
from typing import List
import pytz
from src.common.identifiers.common import BinanceClient
from src.common.identifiers.futures import Signal, State
from src.common.identifiers.spot import HPConfig

logger = logging.getLogger("common")


def generate_hp_id(hp_list: List[HPConfig]) -> str:
    """
    Generate the next HP ID starting from 1000.
    It checks the list of HP entries to find the highest existing ID.
    """
    # Extract all the existing HP IDs, ignoring any with value '0'
    hp_ids = [int(entry.hp_id) for entry in hp_list if entry.hp_id != "0"]

    logger.info("HP IDs: %s", hp_ids)

    if not hp_ids:
        logger.info("Returning 1000")
        return "1000"  # Start from 1000 if no valid entries are present

    # Get the highest HP ID and increment it
    next_id = str(max(hp_ids) + 1)
    logger.info("Next HP ID generated: %s", next_id)

    return next_id


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
