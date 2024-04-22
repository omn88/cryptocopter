from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button


class SearchableDropDown(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.dropdown = DropDown()
        self.main_input = TextInput(multiline=False, size_hint_y=None, height=30)
        self.main_input.bind(text=self.on_text_change)
        self.add_widget(self.main_input)

    def on_text_change(self, instance, value):
        self.dropdown.dismiss()
        self.dropdown.clear_widgets()  # Clear previous buttons
        filtered_data = [
            coin for coin in self.fetch_coin_list() if value.lower() in coin.lower()
        ]
        for coin in filtered_data:
            btn = Button(text=coin, size_hint_y=None, height=44)
            btn.bind(on_release=lambda btn: self.dropdown.select(btn.text))
            self.dropdown.add_widget(btn)
        if filtered_data:
            self.dropdown.open(self.main_input)

    def filter_symbols(self, text):
        self.ids.dropdown.clear_widgets()
        all_symbols = (
            get_all_spot_symbols()
        )  # Ensure this is called efficiently / this has to be provided from the file and checked for changes periodically.
        filtered_symbols = [
            symbol for symbol in all_symbols if text.lower() in symbol.lower()
        ]
        for symbol in filtered_symbols:
            btn = Button(text=symbol, size_hint_y=None, height=44)
            btn.bind(on_release=self.select_symbol)
            self.ids.dropdown.add_widget(btn)

    def select_symbol(self, btn):
        self.ids.text_input.text = btn.text
        self.ids.dropdown.dismiss()
