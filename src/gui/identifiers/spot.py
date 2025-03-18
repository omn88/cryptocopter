from dataclasses import asdict, dataclass, field
from typing import NamedTuple, Optional
from src.identifiers.spot import HPBuyData, HPSellData, State


@dataclass
class HPUpdate:
    hp_id: str
    asset: str = ""
    buy_price: Optional[float] = None
    quantity: Optional[float] = None
    quantity_usdt: Optional[float] = None
    sell_price: Optional[float] = None
    expected_return: Optional[float] = None
    current_price: Optional[float] = None
    net: Optional[float] = None
    net_percent: Optional[float] = None
    state: State = State.NONE


@dataclass
class HPGuiDataBuy:
    data: HPBuyData
    hp_update: HPUpdate

    def __str__(self):
        return f"HPGuiDataBuy(data={self.data}, hp_update={self.hp_update})"


@dataclass
class HPGuiDataSell:
    def __init__(
        self,
        data: HPSellData,
        hp_update: HPUpdate,
    ):
        self.data = data
        self.hp_update = hp_update

    def __str__(self):
        return f"HPGuiDataSell(data={self.data}, hp_update={self.hp_update})"


@dataclass
class IdlePosition:
    open_time: Optional[str] = field(default=None)
    hp_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    mode: str = field(default="")
    price_low: str = field(default="")
    price_high: str = field(default="")
    budget: str = field(default="")
    order_trigger: str = field(default="")
    state: str = field(default="")
    completeness: str = field(default="")
    current_price: str = field(default="")

    def to_dict(self):
        return asdict(self)


@dataclass
class ActivePosition:
    open_time: Optional[str] = field(default=None)
    hp_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    mode: str = field(default="")
    price_low: str = field(default="")
    price_high: str = field(default="")
    budget: str = field(default="")
    order_cancel: str = field(default="")
    state: str = field(default="")
    completeness: str = field(default="")
    stagnation: str = field(default="")
    current_price: str = field(default="")

    def to_dict(self):
        return asdict(self)


@dataclass
class ArchivedPosition:
    open_time: Optional[str] = field(default=None)
    close_time: Optional[str] = field(default=None)
    hp_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    mode: str = field(default="")
    price_low: str = field(default="")
    price_high: str = field(default="")
    budget: str = field(default="")
    order_trigger: str = field(default="")
    completeness: str = field(default="")

    def to_dict(self):
        return asdict(self)


class PriceData(NamedTuple):
    price: float
    symbol: str
