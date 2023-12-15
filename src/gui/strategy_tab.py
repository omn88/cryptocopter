import asyncio
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button


class StrategyTab(BoxLayout):
    def __init__(self, trading_system, **kwargs):
        super().__init__(**kwargs)
        self.trading_system = trading_system

        # Add details of the strategy

        self.add_widget(Button(text="Cancel", on_press=self.on_cancel))

    def on_cancel(self, instance):
        # Stop the trading system
        asyncio.create_task(self.trading_system.stop())
