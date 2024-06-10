from dataclasses import dataclass, field
from enum import Enum
from typing import List, NamedTuple

from src.common.identifiers.common import Order, PositionSide, PositionStatus


class State(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    STAGNATED = "STAGNATED"
    CLOSED = "CLOSED"


@dataclass
class Position:
    id: str = ""
    symbol: str = ""
    quantity: float = 0
    state: State = State.NEW
    side: PositionSide = PositionSide.FLAT
    orders: List[Order] = field(default_factory=lambda: [])
    status: PositionStatus = PositionStatus.NEW
    opened: bool = False

    def __str__(self):
        orders_str = ", ".join([str(order) for order in self.orders])
        return (
            f"Position(id={self.id}, symbol={self.symbol}, quantity={self.quantity}, state={self.state}, "
            f"side={self.side}, orders=[{orders_str}], status={self.status}, opened={self.opened})"
        )


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

    def __str__(self):
        return (
            f"StrategyConfig(system_id={self.system_id}, symbol={self.symbol}, side={self.side}, "
            f"price_low={self.price_low}, price_high={self.price_high}, order_trigger={self.order_trigger}, "
            f"name={self.name}, budget={self.budget})"
        )
