import asyncio
import logging
import logging_config  # noinspection PyUnresolvedReferences
import warnings
from src.trading_system import TradingSystem

warnings.simplefilter(action="ignore", category=FutureWarning)

logger = logging.getLogger("main")


async def main():
    # Instantiate and initialize the trading system
    trading_system = TradingSystem(strategy_name="RSI_Extended")
    await trading_system.initialize()

    try:
        # Start trading
        await trading_system.start_trading()
    except asyncio.exceptions.CancelledError:
        logging.info("Strategy cancelled")


if __name__ == "__main__":
    asyncio.run(main())
