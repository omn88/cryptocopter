import asyncio
import logging
from binance import BinanceSocketManager
import strategy_script

logger = logging.getLogger("socket")


async def ticker_socket(bm: BinanceSocketManager, strategy: strategy_script.Strategy):

    ticker = bm.symbol_miniticker_socket(symbol="BTCUSDT")
    async with ticker:
        while True:
            if strategy.status != strategy_script.Status.CANCELLED:
                msg = await ticker.recv()
                logger.info(msg)
                await asyncio.sleep(1)
            else:
                break

    logger.info("Po wyjsciu z socketa")


async def user_socket(bm: BinanceSocketManager, strategy: strategy_script.Strategy):

    user_socket = bm.user_socket()
    async with user_socket:
        while True:
            if strategy.status != strategy_script.Status.CANCELLED:
                msg = await user_socket.recv()
                logger.info(msg)
            else:
                break
            await asyncio.sleep(0.01)

    logger.info("Po wyjsciu z socketa")
