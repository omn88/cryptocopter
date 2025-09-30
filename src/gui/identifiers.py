from dataclasses import dataclass
from typing import Optional
from src.common.symbol import Symbol
from src.identifiers import HPBuyData, HPSellConfig, HPSellData, State, StateInfo


@dataclass
class HPUpdate:
    hp_id: str
    symbol: Symbol
    coin: str = ""
    buy_price: Optional[float] = None
    quantity: Optional[float] = None
    quantity_usd: Optional[float] = None
    realized_quantity: Optional[float] = None  # Added for actual filled quantity
    total_quantity: Optional[float] = (
        None  # Added for total bought quantity (before any sells)
    )
    expected_quantity: Optional[float] = (
        None  # Added for total expected quantity based on budget (budget/price_high)
    )
    orders_total_quantity: Optional[float] = (
        None  # Added for sum of all buy order quantities (total to be bought)
    )
    sell_price: Optional[float] = None
    expected_return: Optional[float] = None
    current_price: Optional[float] = None
    net: Optional[float] = None
    net_percent: Optional[float] = None
    state: State = State.NONE
    is_child: bool = False
    side: str = "UNKNOWN"  # Added to track BUY/SELL side
    sell_completeness: Optional[float] = None  # Added for sell position progress
    sell_state: Optional[str] = None  # Added for sell operation state
    buy_operation_state: Optional[str] = None  # Added for buy operation state


@dataclass
class HPGuiDataBuy:
    data: HPBuyData
    hp_update: HPUpdate

    def __str__(self):
        return f"HPGuiDataBuy(hp_update={self.hp_update}, data={self.data})"


@dataclass
class HPClose:
    config: HPSellConfig
    state_info: StateInfo

    def __str__(self):
        return f"HPClose(data={self.config}, hp_update={self.state_info})"


@dataclass
class HPGuiDataSell:
    data: HPSellData
    hp_update: HPUpdate

    def __str__(self):
        return f"HPGuiDataSell(hp_update={self.hp_update}, data={self.data})"
