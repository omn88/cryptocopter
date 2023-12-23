"""Main module for managing trading strategies.

This module contains the `AsyncApp` class, which is responsible for creating and managing instances
of `TradingSystem` and `StrategyTab` for each trading strategy. It also sets up a logging handler
for each strategy.
"""

import asyncio
import logging
from typing import Dict
from kivy.app import App
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import ListProperty
from kivy.uix.tabbedpanel import TabbedPanelItem
from logging_config import KivyGuiHandler
from src.common.identifiers import BinanceClient
from src.gui.identifiers import PositionStatus, StrategyData
from src.gui.strategytab import StrategyTab
from src.trading_system import TradingSystem
from src.common.identifiers import Position, EventName, Event, SentinelUpdate

logger = logging.getLogger("async_app")

# Load the common_widgets.kv file first
Builder.load_file("src/gui/common_widgets.kv")
Builder.load_file("src/gui/strategytab.kv")


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
    active_strategies = ListProperty([])
    closed_strategies = ListProperty([])
    main_ui_queue: asyncio.Queue = asyncio.Queue()

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
        self.tabs: Dict = {}
        asyncio.create_task(self.update_ui())

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
        self.root = Builder.load_file("src/gui/asyncapp.kv")
        return self.root

    def log_spinner_change(self, spinner, new_value):
        """Logs a message when a spinner value changes.

        Args:
            spinner (str): The name of the spinner.
            new_value (str): The new value of the spinner.
        """
        logger.info("%s spinner value changed to %s", spinner, new_value)

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
                main_ui_queue=self.main_ui_queue,
            )
            self.trading_systems.append(trading_system)

            strategy_tab = StrategyTab(
                trading_system=trading_system,
                ui_queue=ui_queue,
                strategy_name=strategy,
                symbol=symbol,
                main_ui_queue=self.main_ui_queue,
            )
            self.strategy_tabs.append(strategy_tab)

            # Set up a logging handler for the strategy
            self.setup_logging_handler(
                strategy_logger=strategy_tab.strategy_logger,
                log_display_widget=strategy_tab.log_display,
            )

            strategy_name = f"{self.strategy_mapping[strategy]}_{trading_system.symbol}"
            tab = TabbedPanelItem(
                text=strategy_name,
                content=strategy_tab,
            )

            # Store a reference to the tab
            self.tabs[strategy_name] = tab

            # Add a new tab for the strategy
            self.root.add_widget(tab)
            self.root.ids.strategy_spinner.text = "Choose Strategy"
            self.root.ids.symbol_spinner.text = "Choose Symbol"

            # Initialize and start trading system
            await trading_system.initialize()
            await trading_system.start_trading()
        else:
            Logger.info("App: Please select a strategy and a symbol.")

    async def on_close_strategy(self, strategy_name, symbol):
        # Get the tab for the strategy
        tab = self.tabs[f"{self.strategy_mapping[strategy_name]}_{symbol}"]

        # Remove the tab from the TabbedPanel
        self.root.remove_widget(tab)

    async def update_ui(self):
        while True:
            logger.info("Events in Main UI queue: %s", self.main_ui_queue.qsize())
            if self.main_ui_queue.qsize() == 0:
                logger.info("Awaiting new Event")
            data = await self.main_ui_queue.get()
            # Update the UI based on data
            # if isinstance(data, Event):
            #     if data.name == EventName.SENTINEL:
            #         logger.info("SENTINEL -> Exiting UI updates.")
            #         await asyncio.sleep(3)
            #         return
            if isinstance(data, StrategyData):
                self.update_strategies(data=data)
            if isinstance(data, Event):
                if data.name == EventName.SENTINEL:
                    logger.info("Sentinel came, closing the strategy.")
                    await self.on_close_strategy(
                        strategy_name=data.content["strategy_name"],
                        symbol=data.content["symbol"],
                    )

    def update_strategies(self, data: StrategyData):
        if len(self.active_strategies):
            if any(
                strategy["symbol"] == data.position_data.symbol
                for strategy in self.active_strategies
            ):
                self.update_active_strategies_tab(data=data)
            else:
                self.add_position_to_active_strategies_tab(data=data)
        else:
            logger.info("Adding new strategy to active strategies tab")
            self.add_position_to_active_strategies_tab(data=data)

    def update_active_strategies_tab(self, data: StrategyData) -> None:
        for strategy in self.active_strategies:
            if (
                strategy["symbol"] == data.position_data.symbol
                and strategy["name"] == data.strategy_name
            ):
                # If it exists, update the values
                strategy["quantity"] = str(data.position_data.quantity)
                strategy["entry_price"] = str(data.position_data.entry_price)
                strategy["mark_price"] = str(data.position_data.mark_price)
                strategy["liquidation_price"] = str(
                    data.position_data.liquidation_price
                )
                strategy["pnl"] = str(data.position_data.pnl)
                strategy["state"] = str(data.position_data.state.value)
                strategy["status"] = str(data.position_data.status)

                if strategy["status"] == str(PositionStatus.CLOSED):
                    logger.info("Position status: %s", data.position_data.status)
                    logger.info(
                        "Length of active strategies: %s", len(self.active_strategies)
                    )
                    logger.info(
                        "Length of closed strategies: %s",
                        len(self.closed_strategies),
                    )
                    self.closed_strategies.append(strategy)
                    self.active_strategies.remove(strategy)
                    logger.info(
                        "Length of active strategies after removal: %s",
                        len(self.active_strategies),
                    )
                    logger.info(
                        "Length of closed strategies after appending: %s",
                        len(self.closed_strategies),
                    )

                logger.info("Updated active strategies: %s", self.active_strategies)

    def add_position_to_active_strategies_tab(self, data: StrategyData):
        self.active_strategies.append(
            {
                "name": data.strategy_name,
                "symbol": data.position_data.symbol,
                "quantity": str(data.position_data.quantity),
                "entry_price": str(data.position_data.entry_price),
                "mark_price": str(data.position_data.mark_price),
                "liquidation_price": str(data.position_data.liquidation_price),
                "pnl": str(data.position_data.pnl),
                "state": str(data.position_data.state),
                "status": str(data.position_data.status),
            }
        )

        logger.info(
            "Active strategies after adding position: %s", self.active_strategies
        )
