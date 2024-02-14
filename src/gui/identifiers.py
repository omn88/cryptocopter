from enum import Enum
from typing import NamedTuple

from kivy.properties import NumericProperty, ListProperty, StringProperty
from kivy.uix.label import Label
from src.common.identifiers import Position, PositionStatus, State

from src.gui.constants import GREEN_COLOR, RED_COLOR, WHITE_COLOR


class SymbolMarkPrice(Label):
    mark_price = NumericProperty(0)


class PnL(Label):
    pnl = NumericProperty(0)

    def on_pnl(self, instance, value):
        pnl = float(value)
        if pnl > 0:
            self.color = GREEN_COLOR
        elif pnl < 0:
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR


class ColorChangingQuantity(Label):
    quantity = NumericProperty(0)
    color = ListProperty(WHITE_COLOR)  # Default color is white

    def on_quantity(self, instance, value):
        quantity = float(value)
        if quantity > 0:
            self.color = GREEN_COLOR
        elif quantity < 0:
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR


class ColorChangingSide(Label):
    side = StringProperty("")
    color = ListProperty([1, 1, 1, 1])  # Default color is white

    def on_side(self, instance, value):
        if value.lower() == "buy":
            self.color = GREEN_COLOR
        elif value.lower() == "sell":
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR


class PriceData(NamedTuple):
    index_price: float
    mark_price: float
    symbol: str


class PositionData:
    def __init__(
        self,
        symbol: str,
        quantity: float,
        margin: float,
        entry_price: float,
        mark_price: float,
        liquidation_price: float,
        pnl: float,
        status: PositionStatus,
        state: State,
        leverage: int,
    ):
        self.symbol: str = symbol
        self.quantity: float = quantity
        self.margin: float = margin
        self.entry_price: float = entry_price
        self.mark_price: float = mark_price
        self.liquidation_price: float = liquidation_price
        self.pnl: float = pnl
        self.status: PositionStatus = status
        self.state: State = state
        self.leverage: int = leverage

    def __repr__(self) -> str:
        return (
            f"PositionData("
            f"symbol={self.symbol}, "
            f"quantity={self.quantity}, "
            f"margin={self.margin}, "
            f"entry_price={self.entry_price}, "
            f"mark_price={self.mark_price}, "
            f"liquidation_price={self.liquidation_price}, "
            f"pnl={self.pnl}, "
            f"status={self.status}, "
            f"state={self.state}, "
            f"leverage={self.leverage})"
        )


class StrategyData:
    def __init__(self, strategy_name: str, position_data: PositionData):
        self.strategy_name: str = strategy_name
        self.position_data: PositionData = position_data

    def __repr__(self) -> str:
        return (
            f"StrategyData("
            f"strategy_name={self.strategy_name}, "
            f"position_data={self.position_data})"
        )


class AccountData:
    def __init__(self, balance):
        self.balance = balance


class OrderData:
    def __init__(
        self,
        order_id,
        open_time,
        symbol,
        order_type,
        side,
        price,
        quantity,
        realized_quantity,
        status,
    ):
        self.order_id = order_id
        self.open_time = open_time
        self.symbol = symbol
        self.order_type = order_type
        self.side = side
        self.price = price
        self.quantity = quantity
        self.realized_quantity = realized_quantity
        self.status = status

    def __repr__(self):
        return (
            f"OrderData(order_id={self.order_id}, open_time={self.open_time}, symbol={self.symbol}, "
            f"order_type={self.order_type}, side={self.side}, price={self.price}, quantity={self.quantity}, "
            f"realized_quantity={self.realized_quantity})"
        )
