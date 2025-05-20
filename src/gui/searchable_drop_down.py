import asyncio
from typing import Dict, List
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button
from kivy.properties import ListProperty, StringProperty

from src.common.symbol_info import SymbolInfo


class SearchableDropDown(BoxLayout):
    options = ListProperty()
    selected_value = StringProperty()

    def __init__(self, client, symbols_info: Dict[str, SymbolInfo], **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.symbols_info = symbols_info
        self.orientation = "vertical"
        self.dropdown = DropDown()

        # Adding search label and input fields
        search_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=30)
        search_box.add_widget(Label(text="Search:", size_hint_x=0.2))
        self.search_input = TextInput(size_hint_x=0.8, multiline=False)
        self.search_input.bind(text=self.update_dropdown)
        search_box.add_widget(self.search_input)
        self.add_widget(search_box)

        # Adding main button for dropdown
        self.main_button = Button(text="Select Symbol", size_hint_y=None, height=30)
        self.main_button.bind(on_release=self.dropdown.open)
        self.add_widget(self.main_button)

        # Binding dropdown selection
        self.dropdown.bind(
            on_select=lambda instance, x: setattr(self.main_button, "text", x)
        )
        self.dropdown.bind(
            on_select=lambda instance, x: setattr(self, "selected_value", x)
        )
        self.dropdown.bind(on_select=self.update_prices)

        # Adding price input fields in a single horizontal BoxLayout
        price_box = BoxLayout(orientation="horizontal", size_hint_y=None, height=30)
        price_box.add_widget(Label(text="Price Low:", size_hint_x=0.2))
        self.price_low_input = TextInput(
            hint_text="0.0", size_hint_x=0.3, height=30, multiline=False
        )
        price_box.add_widget(self.price_low_input)
        price_box.add_widget(Label(text="Price High:", size_hint_x=0.2))
        self.price_high_input = TextInput(
            hint_text="0.0", size_hint_x=0.3, height=30, multiline=False
        )
        price_box.add_widget(self.price_high_input)
        self.add_widget(price_box)

    async def fetch_bid_ask_price(self, symbol: str):
        ticker = await self.client.get_orderbook_ticker(symbol=symbol)
        return float(ticker["bidPrice"]), float(ticker["askPrice"])

    def update_prices(self, instance, value):
        asyncio.create_task(self._update_prices_async(value))

    async def _update_prices_async(self, symbol: str):
        bid, ask = await self.fetch_bid_ask_price(symbol)
        self.price_low_input.text = self.symbols_info[symbol].format_price(bid)
        self.price_high_input.text = self.symbols_info[symbol].format_price(ask)

    def update_dropdown(self, instance, value):
        self.dropdown.clear_widgets()
        for option in self.options:
            if value.lower() in option.lower():
                btn = Button(text=option, size_hint_y=None, height=30)
                btn.bind(on_release=lambda btn: self.dropdown.select(btn.text))
                self.dropdown.add_widget(btn)
