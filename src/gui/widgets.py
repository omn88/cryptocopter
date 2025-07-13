from kivy.uix.label import Label
from kivy.properties import NumericProperty, ListProperty, StringProperty


class ColorChangingQuantity(Label):
    quantity = NumericProperty(0)
    color_positive = ListProperty([0, 1, 0, 1])  # Green
    color_negative = ListProperty([1, 0, 0, 1])  # Red
    color_zero = ListProperty([1, 1, 1, 1])  # White

    def on_quantity(self, instance, value):
        if value > 0:
            self.color = self.color_positive
        elif value < 0:
            self.color = self.color_negative
        else:
            self.color = self.color_zero


class SymbolMarkPrice(Label):
    mark_price = NumericProperty(0)
    color_above = ListProperty([0, 1, 0, 1])  # Green
    color_below = ListProperty([1, 0, 0, 1])  # Red
    color_equal = ListProperty([1, 1, 1, 1])  # White
    reference_price = NumericProperty(0)

    def on_mark_price(self, instance, value):
        if value > self.reference_price:
            self.color = self.color_above
        elif value < self.reference_price:
            self.color = self.color_below
        else:
            self.color = self.color_equal
