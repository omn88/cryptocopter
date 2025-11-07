import errno
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List
import pytz

from src.common.symbol import Symbol
from src.common.identifiers import HPSellConfig

logger = logging.getLogger("common")


def generate_hp_id(hp_list: List[str]) -> str:
    """
    Generate the next HP ID starting from 1000.
    It checks the list of HP entries to find the highest existing ID.
    """

    if not hp_list:
        logger.info("Next HP ID generated: 1000")
        return "1000"  # Start from 1000 if no valid entries are present

    # Get the highest HP ID and increment it
    next_id = str(max(int(hp) for hp in hp_list) + 1)
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


def determine_sell_strategy(
    config: HPSellConfig, symbols: Dict[str, Symbol]
) -> List[Symbol]:
    delisted_coins = {
        "USDT",
        "FDUSD",
        "TUSD",
        "USDP",
        "DAI",
        "AEUR",
        "UST",
        "USTC",
        "PAXG",
    }

    strategy = []
    coin = config.coin
    end_currency = config.end_currency

    if end_currency == "PLN":
        # Priority 1: Direct pair to PLN
        if f"{coin}PLN" in symbols:
            strategy.append(symbols[f"{coin}PLN"])
            return strategy

        # Priority 2: coinUSDC + USDCPLN
        if f"{coin}USDC" in symbols and "USDCPLN" in symbols:
            strategy.append(symbols[f"{coin}USDC"])
            strategy.append(symbols["USDCPLN"])
            return strategy

        # Priority 3: coinBTC + BTCPLN
        if (
            coin not in delisted_coins
            and f"{coin}BTC" in symbols
            and "BTCPLN" in symbols
        ):
            strategy.append(symbols[f"{coin}BTC"])
            strategy.append(symbols["BTCPLN"])
            return strategy

        # Priority 4: coinBNB + BNBPLN
        if (
            coin not in delisted_coins
            and f"{coin}BNB" in symbols
            and "BNBPLN" in symbols
        ):
            strategy.append(symbols[f"{coin}BNB"])
            strategy.append(symbols["BNBPLN"])
            return strategy

        # Priority 5: Converting
        # Use USDT symbol for convert operations - ending with USDT indicates conversion
        symbol = symbols[f"{coin}USDT"]
        symbol.is_convert_only = True
        strategy.append(symbol)
        return strategy

    if end_currency == "USDC":
        # Priority 1: coinUSDC
        if f"{coin}USDC" in symbols:
            strategy.append(symbols[f"{coin}USDC"])
            return strategy

        # Priority 2: coinBTC + BTCUSDC
        if (
            coin not in delisted_coins
            and f"{coin}BTC" in symbols
            and "BTCUSDC" in symbols
        ):
            strategy.append(symbols[f"{coin}BTC"])
            strategy.append(symbols["BTCUSDC"])
            return strategy

        # Priority 3: Exotic coinXYZ + XYZUSDC
        if coin not in delisted_coins:
            for pair in symbols:
                if pair.startswith(coin):
                    quote = pair.replace(coin, "")
                    if quote in delisted_coins:
                        continue
                    if f"{quote}USDC" in symbols:
                        strategy.append(symbols[pair])
                        strategy.append(symbols[f"{quote}USDC"])
                        return strategy

        # Priority 4: Converting
        # Use USDT symbol for convert operations - ending with USDT indicates conversion
        symbol = symbols[f"{coin}USDT"]
        symbol.is_convert_only = True
        strategy.append(symbol)
        return strategy
    return []
