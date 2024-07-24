import asyncio
from dataclasses import dataclass
from enum import Enum
import logging
import time
from typing import NamedTuple

from binance.enums import ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC
from binance import AsyncClient


class SentinelUpdate(NamedTuple):
    sentinel: str


class Mode(Enum):
    SINGLE = "SINGLE"
    DCA = "DCA"


class PositionSide(Enum):
    LONG = "BUY"
    SHORT = "SELL"
    FLAT = "FLAT"


class BinanceClient(AsyncClient):
    def __init__(self, api_key: str, api_secret: str, sync_interval: int = 60):
        super().__init__(api_key, api_secret)
        self.time_difference: float = 0.0
        self.sync_interval: int = sync_interval
        self.last_sync: float = 0.0
        self.logger = logging.getLogger(__name__)
        asyncio.create_task(self.time_sync_loop())

    async def time_sync_loop(self):
        while True:
            try:
                self.time_difference = await self.get_server_time_difference()
                self.last_sync = time.time()
            except Exception as e:
                self.logger.info("Failed to sync time: %s", e)
            await asyncio.sleep(self.sync_interval)

    async def get_server_time_difference(self) -> float:
        server_time = await self.get_server_time()
        server_time = server_time["serverTime"] / 1000  # Convert from ms to s
        local_time = time.time()
        return local_time - server_time

    async def get_adjusted_time(self) -> float:
        if time.time() - self.last_sync > self.sync_interval:
            self.time_difference = await self.get_server_time_difference()
            self.last_sync = time.time()
        return time.time() - self.time_difference
