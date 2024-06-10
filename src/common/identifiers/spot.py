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
