from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple, Union

from src.common.identifiers.common import (
    AccountUpdate,
    OrderUpdate,
    PositionSide,
    SentinelUpdate,
)


class State(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    STAGNATED = "STAGNATED"
    CLOSED = "CLOSED"


class Signal(Enum):
    HP_ALL_ORDERS_FILLED = "HP_ALL_ORDERS_FILLED"
    NULL = "NULL"


class SignalUpdate(NamedTuple):
    signal: Signal = Signal.NULL

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal})"


class EventName(Enum):
    ACCOUNT = "Account"
    ORDER = "Order"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"
    TICKER = "Ticker"


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


class Event(NamedTuple):
    name: EventName
    content: Union[
        OrderUpdate,
        AccountUpdate,
        SignalUpdate,
        TickerUpdate,
        SentinelUpdate,
    ]

    def __repr__(self) -> str:
        return f"Event(name={self.name}, content={self.content})"


@dataclass
class StrategyConfig:
    system_id: str = ""
    symbol: str = ""
    side: PositionSide = PositionSide.FLAT
    price_low: float = 0
    price_high: float = 0
    order_trigger: float = 0
    name: str = "HP Manager"
    budget: float = 0
    min_notional: float = 0

    def __str__(self):
        return (
            f"StrategyConfig(system_id={self.system_id}, symbol={self.symbol}, side={self.side}, "
            f"price_low={self.price_low}, price_high={self.price_high}, order_trigger={self.order_trigger}, "
            f"name={self.name}, budget={self.budget})"
        )
