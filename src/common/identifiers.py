"""
Module containing product identifiers.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple, Dict, List
from binance import AsyncClient
from binance.enums import (
    ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
    ORDER_STATUS_NEW,
)


class State(Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    LONG_EXT = "LONG_EXT"
    SHORT = "SHORT"
    SHORT_EXT = "SHORT_EXT"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"


class Signal(Enum):
    LONG = "LONG"
    LONG_EXT = "LONG_EXT"
    SHORT = "SHORT"
    SHORT_EXT = "SHORT_EXT"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"
    CLOSE_SPECIAL = "CLOSE_SPECIAL"
    NULL = "NULL"


class OrderUpdate(NamedTuple):
    status: str = ORDER_STATUS_NEW
    price: float = 0
    quantity: float = 0
    realized_quantity: float = 0
    last_filled_quantity: float = 0
    order_id: int = 0
    average_price: float = 0
    order_type: str = ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return f"OrderUpdate(price={self.price}, quantity={self.quantity}, status={self.status}, order_id={self.order_id}, order_type={self.order_type})"


class AccountUpdate(NamedTuple):
    account_update: Dict

    def __repr__(self) -> str:
        return f"AccountUpdate(kline={self.account_update})"


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


class SignalUpdate(NamedTuple):
    signal: Signal = Signal.NULL
    price: float = 0

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal}, price={self.price})"


class SentinelUpdate(NamedTuple):
    sentinel: str


class EventName(Enum):
    KLINE = "Kline"
    ACCOUNT = "Account"
    ORDER = "Order"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"


class Event(NamedTuple):
    name: EventName
    content: NamedTuple

    def __repr__(self) -> str:
        return f"Event(name={self.name}, content={self.content})"


class PositionSide(Enum):
    LONG = "BUY"
    SHORT = "SELL"
    FLAT = "FLAT"


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"
    NEW = "NEW"


@dataclass
class Order:
    price: float
    quantity: float
    quantity_stable: float = 0
    order_id: int = 0
    realized_quantity: float = 0
    open_time = None
    time_in_force: str = TIME_IN_FORCE_GTC
    status: str = ORDER_STATUS_NEW
    order_type: str = ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return (
            f"Order(price={self.price}, quantity={self.quantity}, "
            f"quantity_stable={self.quantity_stable}, order_id={self.order_id}, "
            f"realized_quantity={self.realized_quantity}, open_time={self.open_time}, "
            f"time_in_force={self.time_in_force}, status={self.status}, "
            f"order_type={self.order_type})"
        )


class PositionStatus(Enum):
    OPEN = "OPEN"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


@dataclass()
class Position:
    id: str = ""
    symbol: str = ""
    entry_price: float = 0
    quantity: float = 0
    margin: float = 0
    state: State = State.FLAT
    side: PositionSide = PositionSide.FLAT  # ToDo: create a function
    orders: List[Order] = field(default_factory=lambda: [])
    liquidation_price: float = 0
    take_profit_order: Order = Order(price=0, quantity=0)
    market_order: Order = field(default_factory=lambda: Order(price=0, quantity=0))
    status: PositionStatus = PositionStatus.OPEN
    leverage: int = 0

    def __repr__(self) -> str:
        return (
            f"Position(entry_price={self.entry_price}, quantity={self.quantity}, margin={self.margin}, "
            f"state={self.state}, "
            f"side={self.side}, orders={self.orders}, liquidation_price={self.liquidation_price}, "
            f"take_profit_order={self.take_profit_order}, "
            f"market_order={self.market_order})"
        )


class BinanceClient(AsyncClient):
    def __init__(self, api_key, api_secret, sync_interval=60):
        super().__init__(api_key, api_secret)
        self.time_difference = None
        self.sync_interval = sync_interval
        self.last_sync = 0
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


class CoinTradeConfig(NamedTuple):
    name: str
    symbol: str
    side: PositionSide
    price: float
    budget: float = 0
    asset: str = "USDT"


class StrategyConfig(NamedTuple):
    name: str
    symbol: str
    number_of_orders: int = 2
    budget: float = 0
    leverage: int = 25
    dca_span: float = 0.005
    asset: str = "USDT"
    interval: str = "15m"
    lookback: str = "4320"
    margin_type: str = "ISOLATED"
