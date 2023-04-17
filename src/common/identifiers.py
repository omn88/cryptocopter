"""
Module containing product identifiers.
"""
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple, Dict, List, Optional

import binance
import numpy


class State(Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    LONG_20 = "LONG_20"
    SHORT = "SHORT"
    SHORT_80 = "SHORT_80"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"


class Signal(Enum):
    LONG = "LONG"
    LONG_20 = "LONG_20"
    SHORT = "SHORT"
    SHORT_80 = "SHORT_80"
    LONG_SPECIAL = "LONG_SPECIAL"
    SHORT_SPECIAL = "SHORT_SPECIAL"
    CLOSE_SPECIAL = "CLOSE_SPECIAL"
    NULL = "NULL"


class OrderUpdate(NamedTuple):
    status: str
    price: float = 0
    quantity: float = 0
    realized_quantity: float = 0
    last_filled_quantity: float = 0
    order_id: int = 0
    average_price: float = 0
    order_type: str = binance.AsyncClient.ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return f"OrderUpdate(price={self.price}, quantity={self.quantity}, status={self.status}, order_id={self.order_id}, order_type={self.order_type})"


class AccountUpdate(NamedTuple):
    account_update: Dict

    def __repr__(self) -> str:
        return f"AccountUpdate(kline={self.account_update})"


class KlineUpdate(NamedTuple):
    kline: List

    def __repr__(self) -> str:
        return f"KlineUpdate(kline={self.kline})"


class SignalUpdate(NamedTuple):
    signal: Signal
    price: float

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal}, price={self.price})"


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


class PositionSide:
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
    time_in_force: str = binance.AsyncClient.TIME_IN_FORCE_GTC
    status: str = binance.AsyncClient.ORDER_STATUS_NEW
    order_type: str = binance.AsyncClient.ORDER_TYPE_LIMIT

    def __repr__(self) -> str:
        return (
            f"Order(price={self.price}, quantity={self.quantity}, "
            f"quantity_stable={self.quantity_stable}, order_id={self.order_id}, "
            f"realized_quantity={self.realized_quantity}, "
            f"time_in_force={self.time_in_force}, status={self.status})"
        )


@dataclass()
class Artifacts:
    start_balance: float = 0
    no_of_dca_orders: int = 0
    leverage: int = 0
    order_quantity_stable: int = 0
    order_level: int = 0
    max_position: float = 0
    price: float = 0
    quantity: float = 0
    side: str = "NEW"
    mode: PositionMode = PositionMode.NEW
    close_price: float = 0
    orders: Optional[List[Order]] = None
    per_cent_earned: float = 0
    stable_earned: float = 0
    end_balance: float = 0
    status: str = "NEW"

    def __repr__(self):
        return (
            f"Artifacts(start_balance={self.start_balance}, no_of_dca_orders={self.no_of_dca_orders},"
            f" leverage={self.leverage}, order_quantity_stable={self.order_quantity_stable},"
            f" max_position={self.max_position}, price={self.price}, quantity={self.quantity},"
            f" side='{self.side}', mode='{self.mode}', close_price={self.close_price}, orders={self.orders},"
            f" per_cent_earned={self.per_cent_earned}, stable_earned={self.stable_earned},"
            f" end_balance={self.end_balance}, status='{self.status}')"
        )


@dataclass()
class Position:
    entry_price: float = 0
    quantity: float = 0
    status: State = State.FLAT
    side: str = PositionSide.FLAT
    orders: Optional[List[Order]] = None
    liquidation_price: float = 0
    target_price: float = 0
    take_profit_order: Order = Order(price=0, quantity=0)
    market_order: Optional[Order] = None
    artifacts: Artifacts = Artifacts()

    def __post_init__(self):
        if self.orders is None:
            self.orders = []

    def __repr__(self) -> str:
        return (
            f"\nCurrentPosition(price={self.entry_price}, quantity={self.quantity}, side={self.side}, "
            f"liquidation_price={self.liquidation_price}, target_price={self.target_price}, "
            f"take_profit_order={self.take_profit_order})"
        )
