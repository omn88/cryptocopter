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
