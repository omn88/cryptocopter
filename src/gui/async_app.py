"""Main module for managing trading strategies.

This module contains the `AsyncApp` class, which is responsible for creating and managing instances
of `TradingSystem` and `StrategyTab` for each trading strategy. It also sets up a logging handler
for each strategy.
"""

import asyncio
import logging
from kivy.app import App
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import ListProperty
from kivy.uix.tabbedpanel import TabbedPanelItem
from logging_config import KivyGuiHandler
from src.common.identifiers import BinanceClient
from src.gui.strategytab import StrategyTab
from src.trading_system import TradingSystem

logger = logging.getLogger("async_app")


class AsyncApp(App):
    """Main application class for managing trading strategies.

    This class is responsible for creating and managing instances of `TradingSystem` and `StrategyTab`
    for each trading strategy. It also sets up a logging handler for each strategy.

    Attributes:
        strategy_tabs (ListProperty): A list of `StrategyTab` instances for each strategy.
        trading_systems (ListProperty): A list of `TradingSystem` instances for each strategy.
        strategy_mapping (dict): A mapping from strategy names to abbreviations.
    """

    strategy_tabs = ListProperty([])
    trading_systems = ListProperty([])

    # root_tabbed_panel = ObjectProperty(None)  # Add this line

    strategy_mapping = {
        "RSI Basic": "RB",
        "RSI Extended": "RE",
        "RSI Special": "RS",
    }

    def __init__(self, client: BinanceClient, **kwargs):
        """Initializes the `AsyncApp` instance.

        Args:
            client (BinanceClient): The Binance client to use for trading.
            **kwargs: Additional keyword arguments.
        """
        super(AsyncApp, self).__init__(**kwargs)
        self.trading_systems = []
        self.client = client

    def setup_logging_handler(self, strategy_logger, log_display_widget):
        """Sets up a logging handler for a strategy.

        Args:
            strategy_logger (Logger): The logger to set up the handler for.
            log_display_widget (Widget): The widget to display the logs in.
        """
        gui_log_handler = KivyGuiHandler(log_display_widget)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        gui_log_handler.setFormatter(formatter)

        strategy_logger.addHandler(gui_log_handler)

        strategy_logger.info("Logging handler configured with success")

    def build(self):
        """Builds the application.

        Returns:
            Widget: The root widget of the application.
        """
        Builder.load_file("src/gui/common_widgets.kv")
        Builder.load_file("src/gui/strategytab.kv")
        self.root = Builder.load_file("src/gui/main.kv")
        return self.root

    def log_spinner_change(self, spinner, new_value):
        """Logs a message when a spinner value changes.

        Args:
            spinner (str): The name of the spinner.
            new_value (str): The new value of the spinner.
        """
        Logger.info("%s spinner value changed to %s", spinner, new_value)

    def start_strategy(self):
        """Starts a new strategy."""
        asyncio.create_task(self.on_start_strategy())

    async def on_start_strategy(self):
        """Creates and starts a new trading strategy."""
        # Check if a strategy and symbol are selected
        strategy = self.root.ids.strategy_spinner.text
        symbol = self.root.ids.symbol_spinner.text
        if strategy != "Choose Strategy" and symbol != "Choose Symbol":
            # Create a new TradingSystem instance
            ui_queue = asyncio.Queue()
            trading_system = TradingSystem(
                client=self.client,
                strategy_name=strategy,
                symbol=symbol,
                ui_queue=ui_queue,
            )
            self.trading_systems.append(trading_system)

            strategy_tab = StrategyTab(
                trading_system=trading_system,
                ui_queue=ui_queue,
                strategy_name=strategy,
                symbol=symbol,
            )
            self.strategy_tabs.append(strategy_tab)

            # Set up a logging handler for the strategy
            self.setup_logging_handler(
                strategy_tab.strategy_logger, strategy_tab.log_display
            )

            # Add a new tab for the strategy
            self.root.add_widget(
                TabbedPanelItem(
                    text=f"{self.strategy_mapping[strategy]}_{trading_system.symbol}",
                    content=strategy_tab,
                )
            )
            self.root.ids.strategy_spinner.text = "Choose Strategy"
            self.root.ids.symbol_spinner.text = "Choose Symbol"

            # Initialize and start trading system
            await trading_system.initialize()
            await trading_system.start_trading()
        else:
            Logger.info("App: Please select a strategy and a symbol.")
