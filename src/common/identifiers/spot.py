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


@dataclass()
class StrategyConfig:
    system_id: str = ""
    symbol: str = ""
    side: PositionSide = PositionSide.FLAT
    price_low: float = 0
    price_high: float = 0
    order_trigger: float = 0
    name: str = "HP Manager"
    budget: float = 0
