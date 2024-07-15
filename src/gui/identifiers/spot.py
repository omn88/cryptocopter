from src.common.identifiers.spot import State, StrategyConfig


class PositionData:
    def __init__(
        self,
        config: StrategyConfig,
        state: State,
        orders_opened: int = 0,
        orders_total: int = 0,
        orders_filled: int = 0,
        recovering: bool = False,
    ):
        self.config = config
        self.state = state
        self.orders_opened = orders_opened
        self.orders_total = orders_total
        self.orders_filled = orders_filled
        self.recovering = recovering

    def __repr__(self) -> str:
        return (
            f"PositionData(config={self.config}, "
            f"state={self.state}, "
            f"orders_opened={self.orders_opened}, "
            f"orders_total={self.orders_total}, "
            f"orders_filled={self.orders_filled}, recovering={self.recovering})"
        )
