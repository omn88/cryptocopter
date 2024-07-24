"""
Module containing product identifiers.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple, List, Union, Dict

from binance.enums import ORDER_STATUS_NEW, ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC
from src.common.identifiers.common import (
    PositionSide,
    SentinelUpdate,
)


class PositionStatus(Enum):
    NEW = "NEW"
    OPEN = "OPEN"  # orders are on the exchange
    STAGNATED = "STAGNATED"  # orders were on the market, but got stagnated
    RECOVERING = "RECOVERING"  # after crash, status for every price level
    CLOSING = "CLOSING"  # some temp status for proper gui working
    CLOSED = "CLOSED"


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


class EventName(Enum):
    KLINE = "Kline"
    ACCOUNT = "Account"
    ORDER = "Order"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"


class Signal(Enum):
    LONG = "LONG"
    LONG_EXT = "LONG_EXT"
    SHORT = "SHORT"
    SHORT_EXT = "SHORT_EXT"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"
    CLOSE_SPECIAL = "CLOSE_SPECIAL"
    NULL = "NULL"


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


class SignalUpdate(NamedTuple):
    signal: Signal = Signal.NULL
    price: float = 0

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal}, price={self.price})"


class Event(NamedTuple):
    name: EventName
    content: Union[
        OrderUpdate,
        KlineUpdate,
        AccountUpdate,
        SignalUpdate,
        SentinelUpdate,
    ]

    def __repr__(self) -> str:
        return f"Event(name={self.name}, content={self.content})"


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

    def __repr__(self):
        return (
            f"StrategyConfig(name={self.name!r}, symbol={self.symbol!r}, "
            f"number_of_orders={self.number_of_orders}, budget={self.budget}, "
            f"leverage={self.leverage}, dca_span={self.dca_span}, asset={self.asset!r}, "
            f"interval={self.interval!r}, lookback={self.lookback!r}, margin_type={self.margin_type!r})"
        )

    def __str__(self):
        return (
            f"StrategyConfig: {self.name} for {self.symbol}, Orders: {self.number_of_orders}, "
            f"Budget: {self.budget}, Leverage: {self.leverage}, DCA Span: {self.dca_span}, "
            f"Asset: {self.asset}, Interval: {self.interval}, Lookback: {self.lookback}, Margin Type: {self.margin_type}"
        )
