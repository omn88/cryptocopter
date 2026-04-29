import datetime
from dataclasses import dataclass
from typing import NamedTuple, Optional

from src.common.symbol import Symbol
from src.domain.enums import PositionSide, SellType, State, UiState
from src.domain.orders import Order


@dataclass
class StateInfo:
    state: State = State.NEW
    open_time: str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    close_time: str = ""
    side: PositionSide = PositionSide.LONG
    completeness: float = 0.0
    ui_state: UiState = UiState.NEW

    def __str__(self):
        return (
            f"StateInfo(state={self.state},"
            f"open_time='{self.open_time}', close_time='{self.close_time}', side={self.side}, ui_state={self.ui_state}, "
            f"completeness={self.completeness:.2f})"
        )

    def generate_open_time(self):
        self.open_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def get_completeness(self, order: Order):
        self.completeness = round(
            float(order.realized_quantity) / float(order.quantity), 2
        )


@dataclass
class HPBuyConfig:
    symbol: Symbol
    coin: str
    hp_id: str = "0"
    buy_price: float = 0
    order_trigger: float = 0
    order_cancel: float = 0
    budget: float = 0

    def __post_init__(self):
        """Ensure order_cancel is always set correctly based on order_trigger"""
        if self.order_trigger:
            self.order_cancel = 2 * self.order_trigger

    def __str__(self):
        return (
            f"HPBuyConfig(hp_id={self.hp_id}, symbol={self.symbol}"
            f"buy_price={self.buy_price}, "
            f"order_trigger={self.order_trigger}, budget={self.budget})"
        )


@dataclass
class HPBuy:
    config: HPBuyConfig
    state_info: StateInfo

    def __str__(self):
        return f"HPBuy(config={self.config}, state_info={self.state_info})"


@dataclass
class HPSellConfig:
    symbol: Symbol = Symbol()
    hp_id: str = ""
    coin: str = ""
    quantity: float = 0.0
    buy_price: float = 0.0
    sell_price: float = 0.0
    end_currency: str = "USDC"
    is_child: bool = False
    parent_hp_id: Optional[str] = None

    def __str__(self):
        return (
            f"HPSellConfig(hp_id={self.hp_id}, coin={self.coin}, "
            f"quantity={self.quantity}, buy_price={self.buy_price}, "
            f"sell_price={self.sell_price}, end_currency={self.end_currency}, symbol={self.symbol})"
        )


@dataclass
class SellPosition:
    sell_order: Order
    config: HPSellConfig
    state_info: StateInfo
    sell_type: SellType = SellType.DIRECT


@dataclass
class HPSell:
    config: HPSellConfig
    state_info: StateInfo

    def __str__(self):
        return f"HPSell(config={self.config}, state_info={self.state_info})"


class RemoveRecord(NamedTuple):
    hp_id: str
    symbol: str
    side: PositionSide

    def __str__(self):
        return f"RemoveRecord(hp_id='{self.hp_id}', symbol='{self.symbol}', side='{self.side}')"
