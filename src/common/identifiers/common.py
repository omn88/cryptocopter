import asyncio
from dataclasses import dataclass
from enum import Enum
import logging
import time
from typing import Dict, NamedTuple, Union

from binance.enums import ORDER_STATUS_NEW, ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC
from binance import AsyncClient


class PositionStatus(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    STAGNATED = "STAGNATED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


@dataclass()
class OrderUpdate:
    status: str = ORDER_STATUS_NEW
    price: float = 0
    quantity: float = 0
    realized_quantity: float = 0
    last_filled_quantity: float = 0
    order_id: int = 0
    average_price: float = 0
    order_type: str = ORDER_TYPE_LIMIT
    symbol: str = ""

    def __repr__(self) -> str:
        return f"OrderUpdate(price={self.price}, quantity={self.quantity}, status={self.status}, order_id={self.order_id}, order_type={self.order_type}, symbol={self.symbol})"


class AccountUpdate(NamedTuple):
    account_update: Dict

    def __repr__(self) -> str:
        return f"AccountUpdate(kline={self.account_update})"


class EventName(Enum):
    KLINE = "Kline"
    ACCOUNT = "Account"
    ORDER = "Order"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"
    TICKER = "Ticker"


class SentinelUpdate(NamedTuple):
    sentinel: str


class TickerUpdate(NamedTuple):
    symbol: str = ""
    last_price: float = 0
    best_bid_price: float = 0
    best_ask_price: float = 0
    high_price: float = 0
    low_price: float = 0
    volume: float = 0

    def __repr__(self):
        return (
            f"TickerUpdate(symbol={self.symbol}, last_price={self.last_price}, best_bid_price={self.best_bid_price}, "
            f"best_ask_price={self.best_ask_price}, high_price={self.high_price}, "
            f"low_price={self.low_price}, volume={self.volume})"
        )


class Signal(Enum):
    LONG = "LONG"
    LONG_EXT = "LONG_EXT"
    SHORT = "SHORT"
    SHORT_EXT = "SHORT_EXT"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"
    CLOSE_SPECIAL = "CLOSE_SPECIAL"
    NULL = "NULL"


class SignalUpdate(NamedTuple):
    signal: Signal = Signal.NULL
    price: float = 0

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal}, price={self.price})"


class KlineUpdate(NamedTuple):
    start_time: int = 0
    open_price: float = 0
    high_price: float = 0
    low_price: float = 0
    close_price: float = 0
    volume: float = 0
    open_interest: float = 0

    def __repr__(self) -> str:
        return (
            f"KlineUpdate(start_time={self.start_time}, open_price={self.open_price}, "
            f"high_price={self.high_price}, low_price={self.low_price}, "
            f"close_price={self.close_price}, volume={self.volume}, "
            f"open_interest={self.open_interest})"
        )


class Event(NamedTuple):
    name: EventName
    content: Union[
        OrderUpdate,
        KlineUpdate,
        AccountUpdate,
        SignalUpdate,
        TickerUpdate,
        SentinelUpdate,
    ]

    def __repr__(self) -> str:
        return f"Event(name={self.name}, content={self.content})"


class PositionSide(Enum):
    LONG = "BUY"
    SHORT = "SELL"
    FLAT = "FLAT"


@dataclass
class Order:
    quantity: float
    price: float = 0
    quantity_stable: float = 0
    order_id: int = 0
    realized_quantity: float = 0
    open_time = None
    time_in_force: str = TIME_IN_FORCE_GTC
    status: str = "PREPARED"
    order_type: str = ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return (
            f"Order(price={self.price}, quantity={self.quantity}, "
            f"quantity_stable={self.quantity_stable}, order_id={self.order_id}, "
            f"realized_quantity={self.realized_quantity}, open_time={self.open_time}, "
            f"time_in_force={self.time_in_force}, status={self.status}, "
            f"order_type={self.order_type})"
        )


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
