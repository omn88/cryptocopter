import asyncio
from typing import Dict
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button
from kivy.properties import ListProperty, StringProperty

from src.common.symbol import Symbol


class SearchableDropDown(BoxLayout):
    options = ListProperty()
    selected_value = StringProperty()

    def __init__(self, client, symbols: Dict[str, Symbol], **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.symbols = symbols
        self.orientation = "vertical"
        self.spacing = 8
        self.size_hint_y = None
        self.height = 145  # Fixed height for 3 rows
        self.dropdown = DropDown()

        # Search row - compact design
        search_box = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=45, spacing=20
        )
        search_label = Label(
            text="Search:", size_hint_x=0.35, halign="right", valign="middle"
        )
        search_label.bind(size=search_label.setter("text_size"))
        search_box.add_widget(search_label)
        self.search_input = TextInput(size_hint_x=0.65, multiline=False)
        self.search_input.bind(text=self.update_dropdown)
        search_box.add_widget(self.search_input)
        self.add_widget(search_box)

        # Symbol selection row
        symbol_box = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=45, spacing=20
        )
        symbol_label = Label(
            text="Symbol:", size_hint_x=0.35, halign="right", valign="middle"
        )
        symbol_label.bind(size=symbol_label.setter("text_size"))
        symbol_box.add_widget(symbol_label)
        self.main_button = Button(text="Select Symbol", size_hint_x=0.65)
        self.main_button.bind(on_release=self.dropdown.open)
        symbol_box.add_widget(self.main_button)
        self.add_widget(symbol_box)

        # Binding dropdown selection
        self.dropdown.bind(
            on_select=lambda instance, x: setattr(self.main_button, "text", x)
        )
        self.dropdown.bind(
            on_select=lambda instance, x: setattr(self, "selected_value", x)
        )
        self.dropdown.bind(on_select=self.update_prices)

        # Buy price row
        price_box = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=45, spacing=20
        )
        price_label = Label(
            text="Buy Price:", size_hint_x=0.35, halign="right", valign="middle"
        )
        price_label.bind(size=price_label.setter("text_size"))
        price_box.add_widget(price_label)
        self.buy_price_input = TextInput(
            hint_text="0.0", size_hint_x=0.65, multiline=False
        )
        price_box.add_widget(self.buy_price_input)
        self.add_widget(price_box)

    async def fetch_bid_ask_price(self, symbol: str):
        ticker = await self.client.get_orderbook_ticker(symbol=symbol)
        return float(ticker["bidPrice"]), float(ticker["askPrice"])

    def update_prices(self, instance, value):
        asyncio.create_task(self._update_prices_async(value))

    async def _update_prices_async(self, symbol: str):
        bid, ask = await self.fetch_bid_ask_price(symbol)
        self.buy_price_input.text = self.symbols[symbol].format_price(ask)

    def update_dropdown(self, instance, value):
        self.dropdown.clear_widgets()
        for option in self.options:
            if value.lower() in option.lower():
                btn = Button(text=option, size_hint_y=None, height=30)
                btn.bind(on_release=lambda btn: self.dropdown.select(btn.text))
                self.dropdown.add_widget(btn)
