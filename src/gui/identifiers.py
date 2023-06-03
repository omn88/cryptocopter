from kivy.properties import NumericProperty, ListProperty, StringProperty
from kivy.uix.label import Label

from src.gui.constants import GREEN_COLOR, RED_COLOR, WHITE_COLOR


class SymbolMarkPrice(Label):
    mark_price = NumericProperty(0)


class PnL(Label):
    pnl = NumericProperty(0)

    def on_pnl(self, instance, value):
        pnl = float(value)
        if pnl > 0:
            self.color = GREEN_COLOR
        elif pnl < 0:
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR


class ColorChangingQuantity(Label):
    quantity = NumericProperty(0)
    color = ListProperty(WHITE_COLOR)  # Default color is white

    def on_quantity(self, instance, value):
        quantity = float(value)
        if quantity > 0:
            self.color = GREEN_COLOR
        elif quantity < 0:
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR


class ColorChangingSide(Label):
    side = StringProperty("")
    color = ListProperty([1, 1, 1, 1])  # Default color is white

    def on_side(self, instance, value):
        if value.lower() == "buy":
            self.color = GREEN_COLOR
        elif value.lower() == "sell":
            self.color = RED_COLOR
        else:
            self.color = WHITE_COLOR
