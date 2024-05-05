from dataclasses import dataclass, field
from enum import Enum
from typing import List, NamedTuple

from src.common.identifiers.common import Order, PositionSide, PositionStatus


class State(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    STAGNATED = "STAGNATED"
    CLOSED = "CLOSED"


@dataclass()
class Position:
    id: str = ""
    symbol: str = ""
    quantity: float = 0
    state: State = State.NEW
    side: PositionSide = PositionSide.FLAT  # ToDo: create a function
    orders: List[Order] = field(default_factory=lambda: [])
    status: PositionStatus = PositionStatus.NEW
    opened: bool = False


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


class StrategyConfig(NamedTuple):
    symbol: str
    side: PositionSide
    price_low: float
    price_high: float
    order_trigger_buffer: float
    name: str = "Coin Sniper"
    budget: float = 0
