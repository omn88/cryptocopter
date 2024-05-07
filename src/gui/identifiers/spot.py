


from src.common.identifiers.common import PositionSide, PositionStatus


class PositionData:
    def __init__(
        self,
        system_id: str,
        status: PositionStatus,
        symbol: str = "",
        side: PositionSide = PositionSide.FLAT,
        price_low: float = 0,
        price_high: float = 0,
        budget: float = 0,
        order_trigger: float = 0,
        orders_opened: int = 0,
        orders_total: int = 0,
        orders_filled: int = 0,
    ):
        self.system_id = system_id
        self.symbol = symbol
        self.side = side
        self.price_low = price_low
        self.price_high = price_high
        self.budget = budget
        self.order_trigger = order_trigger
        self.orders_opened = orders_opened
        self.orders_total = orders_total
        self.orders_filled = orders_filled
        self.status = status

    def __repr__(self) -> str:
        return (
            f"PositionData(system_id={self.system_id}, symbol={self.symbol}, "
            f"side={self.side}, status={self.status}, "
            f"price_low={self.price_low}, "
            f"price_high={self.price_high}, "
            f"budget={self.budget}, "
            f"order_trigger={self.order_trigger}, "
            f"orders_opened={self.orders_opened}, "
            f"orders_total={self.orders_total}, "
            f"orders_filled={self.orders_filled})"
        )
