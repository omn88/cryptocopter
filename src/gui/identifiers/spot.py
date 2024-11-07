from dataclasses import asdict, dataclass, field
from typing import NamedTuple, Optional
from src.common.identifiers.spot import HPConfig, State, StateInfo


@dataclass
class HPUpdate:
    hp_id: str = ""
    asset: str = ""
    buy_price: float = 0.0
    quantity: float = 0.0
    quantity_usdt: float = 0.0
    sell_price: float = 0.0
    expected_return: float = 0.0
    current_price: float = 0.0
    net: float = 0.0
    net_percent: float = 0.0
    state: State = State.NEW


class PositionData:
    def __init__(
        self,
        config: HPConfig,
        state_info: StateInfo,
        hp_update: HPUpdate,
        recovering: bool = False,
    ):
        self.config = config
        self.state_info = state_info
        self.order_cancel = 2 * config.order_trigger
        self.hp_update = hp_update

        self.recovering = recovering

    def __repr__(self) -> str:
        return (
            f"PositionData(config={self.config}, "
            f"state_info={self.state_info}, "
            f"order_cancel={self.order_cancel}, "
            f"recovering={self.recovering})"
        )


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
