from dataclasses import asdict, dataclass, field
from typing import NamedTuple, Optional
from src.common.identifiers.spot import State, StrategyConfig


class PositionData:
    def __init__(
        self,
        config: StrategyConfig,
        state: State,
        stagnation_counter: int,
        completeness: float,
        stagnation_limit: int = 8,
        recovering: bool = False,
    ):
        self.config = config
        self.state = state
        self.stagnation_counter = stagnation_counter
        self.stagnation_limit = stagnation_limit
        self.order_cancel = 2 * config.order_trigger
        self.completeness = completeness
        self.recovering = recovering

    def __repr__(self) -> str:
        return (
            f"PositionData(config={self.config}, "
            f"state={self.state}, "
            f"stagnation_counter={self.stagnation_counter}, "
            f"stagnation_limit={self.stagnation_limit}, "
            f"order_cancel={self.order_cancel}, "
            f"completeness={self.completeness:.2f}, "
            f"recovering={self.recovering})"
        )


@dataclass
class IdlePosition:
    open_time: Optional[str] = field(default=None)
    system_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    mode: str = field(default="")
    price_low: str = field(default="")
    price_high: str = field(default="")
    budget: str = field(default="")
    order_trigger: str = field(default="")
    state: str = field(default="")
    completeness: str = field(default="")
    stagnation_counter: str = field(default="")
    stagnation_limit: str = field(default="")

    def to_dict(self):
        return asdict(self)


@dataclass
class ActivePosition:
    open_time: Optional[str] = field(default=None)
    system_id: str = field(default="")
    symbol: str = field(default="")
    side: str = field(default="")
    mode: str = field(default="")
    price_low: str = field(default="")
    price_high: str = field(default="")
    budget: str = field(default="")
    order_cancel: str = field(default="")
    state: str = field(default="")
    completeness: str = field(default="")
    stagnation_counter: str = field(default="")
    stagnation_limit: str = field(default="")

    def to_dict(self):
        return asdict(self)


@dataclass
class ArchivedPosition:
    open_time: Optional[str] = field(default=None)
    close_time: Optional[str] = field(default=None)
    system_id: str = field(default="")
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
