from kivy.factory import Factory
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button


class SearchableDropDown(BoxLayout):
    def __init__(self, **kwargs):
        super(SearchableDropDown, self).__init__(orientation="vertical", **kwargs)
        self.dropdown = DropDown()
        self.main_input = TextInput(multiline=False, size_hint_y=None, height=30)
        self.main_input.bind(on_text_validate=self.on_text_change)
        self.add_widget(self.main_input)
        self.all_symbols = ["BTCUSDT", "ETHUSDT"]  # Example symbols

    def on_text_change(self, instance):
        self.dropdown.dismiss()
        filtered_data = [
            coin for coin in self.all_symbols if instance.text.lower() in coin.lower()
        ]
        for coin in filtered_data:
            btn = Button(text=coin, size_hint_y=None, height=44)
            btn.bind(on_release=lambda btn=btn: self.dropdown_select(btn.text))
            self.dropdown.add_widget(btn)
        if filtered_data:
            self.dropdown.open(self.main_input)

    def dropdown_select(self, text):
        self.main_input.text = text
        self.dropdown.dismiss()


# # Register the class with Kivy's Factory directly after class definition
# Factory.register('SearchableDropDown', cls=SearchableDropDown)
