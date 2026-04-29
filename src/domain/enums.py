from enum import Enum, auto
from typing import NamedTuple


class State(Enum):
    NEW = "NEW"
    BUYING = "BUYING"
    PARTIALLY_BOUGHT = "PARTIALLY_BOUGHT"
    BOUGHT = "BOUGHT"
    READY_TO_SELL = "READY_TO_SELL"
    SELLING = "SELLING"
    PARTIALLY_SOLD = "PARTIALLY_SOLD"
    SOLD = "SOLD"
    PART_SOLD_PART_BOUGHT = "PART_SOLD_PART_BOUGHT"
    SOLD_PART_BOUGHT = "SOLD_PART_BOUGHT"
    CLOSED = "CLOSED"
    WAITING_CHILD = "WAITING_CHILD"
    NONE = ""


class Signal(Enum):
    HP_ALL_ORDERS_FILLED = "HP_ALL_ORDERS_FILLED"
    NULL = "NULL"


class SignalUpdate(NamedTuple):
    signal: Signal = Signal.NULL

    def __repr__(self) -> str:
        return f"SignalUpdate(signal={self.signal})"


class EventName(Enum):
    # Binance WebSocket event types
    KLINE = "kline"
    TICKER_24HR = "24hrTicker"
    ACCOUNT_POSITION = "outboundAccountPosition"
    EXECUTION_REPORT = "executionReport"
    # Internal event types
    ERROR = "error"
    SIGNAL = "Signal"
    SENTINEL = "Sentinel"
    TICKER = "Ticker"
    ALL_TICKERS = "All"
    PRICE_UPDATES = "PriceUpdates"
    PORTFOLIO_INVENTORY = "PortfolioInventory"
    # HP Manager → Portfolio Events
    HP_SELL_POSITION_CREATED = "HP_SELL_POSITION_CREATED"
    HP_SELL_POSITION_PARTIALLY_FILLED = "HP_SELL_POSITION_PARTIALLY_FILLED"
    HP_SELL_POSITION_COMPLETED = "HP_SELL_POSITION_COMPLETED"
    HP_BUY_POSITION_CREATED = "HP_BUY_POSITION_CREATED"
    HP_BUY_ORDERS_PLACED = "HP_BUY_ORDERS_PLACED"
    HP_BUY_POSITION_FILLED = "HP_BUY_POSITION_FILLED"
    HP_BUY_POSITION_PARTIALLY_FILLED = "HP_BUY_POSITION_PARTIALLY_FILLED"
    HP_POSITION_CANCELLED = "HP_POSITION_CANCELLED"


class UiState(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    STAGNATED = "STAGNATED"
    CLOSED = "CLOSED"


class PositionSide(Enum):
    LONG = "BUY"
    SHORT = "SELL"
    FLAT = "FLAT"


class Mode(Enum):
    SINGLE = "SINGLE"
    DCA = "DCA"


class SellType(Enum):
    DIRECT = auto()
    TWOHOPS = auto()
    CONVERT = auto()


class SubscriptionType(Enum):
    PRICE = auto()
    USER = auto()
    KLINE = auto()


class SubscriptionTarget(Enum):
    FRONTEND = auto()
    BACKEND = auto()
    PORTFOLIO = auto()
