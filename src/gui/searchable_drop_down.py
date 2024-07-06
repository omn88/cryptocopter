from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button
from kivy.properties import ListProperty, StringProperty


class SearchableDropDown(BoxLayout):
    options = ListProperty()
    selected_value = StringProperty()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.dropdown = DropDown()

        self.search_input = TextInput(size_hint_y=None, height=30, multiline=False)
        self.search_input.bind(text=self.update_dropdown)
        self.add_widget(self.search_input)

        self.main_button = Button(text="Select Symbol", size_hint_y=None, height=30)
        self.main_button.bind(on_release=self.dropdown.open)
        self.add_widget(self.main_button)

        self.dropdown.bind(
            on_select=lambda instance, x: setattr(self.main_button, "text", x)
        )
        self.dropdown.bind(
            on_select=lambda instance, x: setattr(self, "selected_value", x)
        )

    def update_dropdown(self, instance, value):
        self.dropdown.clear_widgets()
        for option in self.options:
            if value.lower() in option.lower():
                btn = Button(text=option, size_hint_y=None, height=30)
                btn.bind(on_release=lambda btn: self.dropdown.select(btn.text))
                self.dropdown.add_widget(btn)
