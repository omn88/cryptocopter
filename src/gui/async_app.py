import asyncio
import logging
from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import (
    ListProperty,
    StringProperty,
    ObjectProperty,
    NumericProperty,
)
from kivy.uix.tabbedpanel import TabbedPanelItem

from logging_config import KivyGuiHandler
from src.gui.strategytab import StrategyTab
from src.trading_system import TradingSystem

logger = logging.getLogger("async_app")


class AsyncApp(App):
    balance_label = StringProperty("0")
    price_label = StringProperty("0")
    open_positions = ListProperty([])
    open_orders = ListProperty([])
    closed_orders = ListProperty([])
    closed_positions = ListProperty([])
    log_display = ObjectProperty(None)
    order_count = NumericProperty(0)
    position_count = NumericProperty(0)

    trading_systems = ListProperty([])
    root_tabbed_panel = ObjectProperty(None)  # Add this line

    strategy_mapping = {
        "RSI Basic": "RB",
        "RSI Extended": "RE",
        "RSI Special": "RS",
    }

    def __init__(self, **kwargs):
        super(AsyncApp, self).__init__(**kwargs)
        self.trading_systems = []

    def on_start(self):
        Clock.schedule_once(self.setup_logging_handler, 0.1)

    def setup_logging_handler(self, *args):
        log_display_widget = self.log_display

        gui_log_handler = KivyGuiHandler(log_display_widget)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        gui_log_handler.setFormatter(formatter)

        logging.getLogger().addHandler(gui_log_handler)

        logger.info("Logging handler configured with success")

    def build(self):
        Builder.load_file("src/gui/common_widgets.kv")
        Builder.load_file("src/gui/strategytab.kv")
        self.root = Builder.load_file("src/gui/main.kv")
        return self.root

    def log_spinner_change(self, spinner, new_value):
        Logger.info("%s spinner value changed to %s", spinner, new_value)

    def start_strategy(self):
        asyncio.create_task(self.on_start_strategy())

    async def on_start_strategy(self):
        # Check if a strategy and symbol are selected
        strategy = self.root.ids.strategy_spinner.text
        symbol = self.root.ids.symbol_spinner.text
        if strategy != "Choose Strategy" and symbol != "Choose Symbol":
            # Create a new TradingSystem instance
            ui_queue = asyncio.Queue()
            trading_system = TradingSystem(
                strategy_name=strategy,
                symbol=symbol,
                ui_queue=ui_queue,
            )
            self.trading_systems.append(trading_system)

            # Add a new tab for the strategy
            self.root.add_widget(
                TabbedPanelItem(
                    text=f"{self.strategy_mapping[strategy]}_{trading_system.symbol}",
                    content=StrategyTab(
                        trading_system=trading_system, ui_queue=ui_queue
                    ),
                )
            )
            self.root.ids.strategy_spinner.text = "Choose Strategy"
            self.root.ids.symbol_spinner.text = "Choose Symbol"

            # Initialize and start trading system
            await trading_system.initialize()
            await trading_system.start_trading()
        else:
            Logger.info("App: Please select a strategy and a symbol.")
