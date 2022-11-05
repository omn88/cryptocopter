import asyncio
import logging
from binance import BinanceSocketManager

logger = logging.getLogger("producer")


async def ticker_socket(bm: BinanceSocketManager, queue: asyncio.Queue):

    ticker = bm.symbol_miniticker_socket(symbol="BTCUSDT")
    async with ticker:
        while True:
            msg = await ticker.recv()
            await queue.put(msg)
            logger.info(msg)
            await asyncio.sleep(0.1)


async def futures_user_socket(bm: BinanceSocketManager, queue: asyncio.Queue):

    futures_user_socket = bm.futures_user_socket()
    async with futures_user_socket:
        while True:
            msg = await futures_user_socket.recv()
            await queue.put(msg)
            logger.info(msg)
            await asyncio.sleep(0.1)


async def kline_futures_socket(
    bm: BinanceSocketManager, symbol: str, interval: str, queue: asyncio.Queue
):

    kline_futures_socket = bm.kline_futures_socket(symbol=symbol, interval=interval)
    async with kline_futures_socket:
        while True:
            msg = await kline_futures_socket.recv()
            await queue.put(msg)
            logger.info(msg)
            await asyncio.sleep(0.1)
