import asyncio
import logging
import logging_config  # noinspection PyUnresolvedReferences
import warnings

from src.common.constants import SYMBOL, ASSET, INTERVAL
from src.trading_system import TradingSystem

warnings.simplefilter(action="ignore", category=FutureWarning)

logger = logging.getLogger("main")


async def main():
    logger.info(
        "RSI Based Futures: Start. Initial parameters: symbol %s, asset %s, interval %s",
        SYMBOL,
        ASSET,
        INTERVAL,
    )

    trading_system = TradingSystem(
        strategy_name="RSI_Extended"
    )  # Or fetch the strategy name from some configuration or user input.
    await trading_system.initialize()
    await trading_system.start_trading()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except asyncio.exceptions.CancelledError:
        logging.info("Strategy cancelled")
