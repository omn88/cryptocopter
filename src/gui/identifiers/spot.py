from dataclasses import dataclass
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
    open_time: Optional[str]
    system_id: str
    symbol: str
    side: str
    mode: str
    price_low: str
    price_high: str
    budget: str
    order_trigger: str
    state: str
    completeness: str
    stagnation_counter: str
    stagnation_limit: str


@dataclass
class ActivePosition:
    open_time: Optional[str]
    system_id: str
    symbol: str
    side: str
    mode: str
    price_low: str
    price_high: str
    budget: str
    order_cancel: str
    state: str
    completeness: str
    stagnation_counter: str
    stagnation_limit: str


@dataclass
class ArchivedPosition:
    open_time: Optional[str]
    close_time: Optional[str]
    system_id: str
    symbol: str
    side: str
    mode: str
    price_low: str
    price_high: str
    budget: str
    order_trigger: str
    completeness: str
