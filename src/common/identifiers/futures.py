"""
Module containing product identifiers.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple, List


from src.common.identifiers.common import Order, PositionStatus, PositionSide


class State(Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    LONG_EXT = "LONG_EXT"
    SHORT = "SHORT"
    SHORT_EXT = "SHORT_EXT"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"


class PositionMode(Enum):
    DCA = "DCA"
    FULL = "FULL"
    NEW = "NEW"


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


class StrategyConfig(NamedTuple):
    name: str
    symbol: str = "BTCUSDT"
    number_of_orders: int = 2
    budget: float = 0
    leverage: int = 25
    dca_span: float = 0.005
    asset: str = "USDT"
    interval: str = "15m"
    lookback: str = "4320"
    margin_type: str = "ISOLATED"
