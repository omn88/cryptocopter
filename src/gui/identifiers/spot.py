from typing import Dict, List
from kivy.properties import NumericProperty, ListProperty, StringProperty
from src.common.identifiers.common import PositionSide, PositionStatus

from src.gui.constants import GREEN_COLOR, RED_COLOR, WHITE_COLOR


from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview import RecycleView


class RecordListItem(BoxLayout):
    symbol = StringProperty()
    side = StringProperty()
    price_low = StringProperty()
    price_high = StringProperty()
    budget = StringProperty()
    order_trigger = StringProperty()
    orders_opened = StringProperty()
    orders_total = StringProperty()
    orders_filled = StringProperty()

    def remove_self(self):
        print("Parent:", type(self.parent))
        print("Grandparent:", type(self.parent.parent))  # Should be RecycleView
        # Access the parent RecycleView through the parent of the RecycleBoxLayout
        recycle_view = self.parent.parent
        print("Recycle view: ", recycle_view.data)
        print("Self symbol, side, price_low ", self.symbol, self.side, self.price_low)
        rv_data: List[Dict] = recycle_view.data
        print("RV data: ", rv_data)
        # To remove the item, we need to find which dictionary in the data list corresponds to this widget
        for item in rv_data:
            print("Item no", item)
            condition = (
                item["symbol"] == self.symbol
                and item["side"] == self.side
                and item["price_low"] == self.price_low
            )
            print("Condition", condition)
            if (
                item["symbol"] == self.symbol
                and item["side"] == self.side
                and item["price_low"] == self.price_low
            ):
                rv_data.remove(item)
                break
        recycle_view.refresh_from_data()


class PositionData:
    def __init__(
        self,
        system_id: str,
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
            f"side={self.side}, "
            f"price_low={self.price_low}, "
            f"price_high={self.price_high}, "
            f"budget={self.budget}, "
            f"order_trigger={self.order_trigger}, "
            f"orders_opened={self.orders_opened}, "
            f"orders_total={self.orders_total}, "
            f"orders_filled={self.orders_filled})"
        )
