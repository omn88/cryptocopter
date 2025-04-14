from dataclasses import asdict, dataclass, field
from typing import NamedTuple, Optional
from src.identifiers.spot import HPBuyData, HPSellConfig, HPSellData, State, StateInfo


@dataclass
class HPUpdate:
    hp_id: str
    coin: str = ""
    buy_price: Optional[float] = None
    quantity: Optional[float] = None
    quantity_usd: Optional[float] = None
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


@dataclass
class IdlePositionBuy:
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
class ActivePositionBuy:
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
class ArchivedPositionBuy:
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


@dataclass
class IdlePositionSell:
    open_time: Optional[str] = field(default=None)
    hp_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    buy_price: str = field(default="")
    sell_price: str = field(default="")
    quantity: str = field(default="")
    end_currency: str = field(default="")
    state: str = field(default="")
    completeness: str = field(default="")
    current_price: str = field(default="")

    def to_dict(self):
        return asdict(self)


@dataclass
class ActivePositionSell:
    open_time: Optional[str] = field(default=None)
    hp_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    buy_price: str = field(default="")
    sell_price: str = field(default="")
    quantity: str = field(default="")
    end_currency: str = field(default="")
    state: str = field(default="")
    completeness: str = field(default="")
    stagnation: str = field(default="")
    current_price: str = field(default="")

    def to_dict(self):
        return asdict(self)


@dataclass
class ArchivedPositionSell:
    open_time: Optional[str] = field(default=None)
    close_time: Optional[str] = field(default=None)
    hp_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    buy_price: str = field(default="")
    sell_price: str = field(default="")
    quantity: str = field(default="")
    end_currency: str = field(default="")
    completeness: str = field(default="")

    def to_dict(self):
        return asdict(self)


class PriceData(NamedTuple):
    price: float
    symbol: str
