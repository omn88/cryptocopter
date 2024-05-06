from kivy.properties import NumericProperty, ListProperty, StringProperty
from src.common.identifiers.common import PositionSide, PositionStatus

from src.gui.constants import GREEN_COLOR, RED_COLOR, WHITE_COLOR


class PositionData:
    def __init__(
        self,
        symbol: str,
        side: PositionSide,
        price_low: float,
        price_high: float,
        budget: float,
        order_trigger: float,
        orders_opened: int,
        orders_total: int,
        orders_filled: int,
        status: PositionStatus,
    ):
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
            f"PositionData(symbol={self.symbol}, "
            f"side={self.side}, "
            f"price_low={self.price_low}, "
            f"price_high={self.price_high}, "
            f"budget={self.budget}, "
            f"order_trigger={self.order_trigger}, "
            f"orders_opened={self.orders_opened}, "
            f"orders_total={self.orders_total}, "
            f"orders_filled={self.orders_filled})"
        )
