"""Main module for managing trading strategies.

This module contains the `AsyncApp` class, which is responsible for creating and managing instances
of `TradingSystem` and `StrategyTab` for each trading strategy. It also sets up a logging handler
for each strategy.
"""

import asyncio
import logging
from typing import Dict, List
from kivy.app import App
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import ListProperty
from kivy.uix.tabbedpanel import TabbedPanelItem
from logging_config import setup_logging_handler
from src.common.constants import LEVERAGE
from src.common.identifiers import BinanceClient
from src.gui.identifiers import PositionStatus, PriceData, StrategyData
from src.gui.strategytab import StrategyTab
from src.trading_system import TradingSystem
from src.common.identifiers import EventName, Event

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

    def __init__(self, client: BinanceClient, **kwargs):
        """Initializes the `AsyncApp` instance.

        Args:
            client (BinanceClient): The Binance client to use for trading.
            **kwargs: Additional keyword arguments.
        """
        super(AsyncApp, self).__init__(**kwargs)
        self.client = client
        self.main_ui_queue: asyncio.Queue = asyncio.Queue()
        self.tabs: Dict = {}
        self.strategy_mapping = {
            "RSI Basic": "RB",
            "RSI Extended": "RE",
            "RSI Special": "RS",
        }
        asyncio.create_task(self.update_ui())

    def __str__(self):
        return f"AsyncApp instance with {len(self.strategy_tabs)} strategy tabs and {len(self.trading_systems)} trading systems"

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
        if new_value not in ["Choose Strategy", "Choose Symbol"]:
            logger.info("%s spinner value changed to %s", spinner, new_value)

    def start_strategy(self):
        """Starts a new strategy."""
        asyncio.create_task(self.on_start_strategy())

    async def on_start_strategy(self):
        """Creates and starts a new trading strategy."""
        # Check if a strategy and symbol are selected
        strategy_name = self.root.ids.strategy_spinner.text
        symbol = self.root.ids.symbol_spinner.text
        number_of_orders = 2
        strategy_name_short = f"{self.strategy_mapping[strategy_name]}_{symbol}"
        if strategy_name != "Choose Strategy" and symbol != "Choose Symbol":
            logger.info("Starting new strategy: %s on pair %s", strategy_name, symbol)

            trading_system = TradingSystem(
                client=self.client,
                strategy_name=strategy_name,
                symbol=symbol,
                number_of_orders=number_of_orders,
                main_ui_queue=self.main_ui_queue,
            )
            await trading_system.initialize()
            self.trading_systems.append(trading_system)

            strategy_tab = StrategyTab(
                trading_system=trading_system,
                ui_queue=trading_system.strategy.ui_queue,
                strategy_name=strategy_name,
                symbol=symbol,
                main_ui_queue=self.main_ui_queue,
            )
            self.strategy_tabs.append(strategy_tab)

            tab = TabbedPanelItem(
                text=strategy_name_short,
                content=strategy_tab,
            )

            # Store a reference to the tab
            self.tabs[strategy_name_short] = tab

            # Add a new tab for the strategy
            self.root.add_widget(tab)
            self.root.ids.strategy_spinner.text = "Choose Strategy"
            self.root.ids.symbol_spinner.text = "Choose Symbol"

            # Set up a logging handler for the strategy
            setup_logging_handler(
                strategy_logger=strategy_tab.strategy_logger,
                log_display_widget=strategy_tab.log_display,
            )

            logger.info(
                "Strategy prepared, starting to initialize, total strategy tabs: %s, trading systems: %s",
                len(self.strategy_tabs),
                len(self.trading_systems),
            )
            await trading_system.start_trading()
        else:
            logger.info("App: Please select a strategy and a symbol.")

    async def on_close_strategy(self, strategy_name, symbol):
        # Get the tab for the strategy
        tab = self.tabs[f"{self.strategy_mapping[strategy_name]}_{symbol}"]

        # Remove the tab from the TabbedPanel
        self.root.remove_widget(tab)

        if len(self.root.tab_list) > 0:
            self.root.switch_to(self.root.tab_list[0])

    def cancel_all_strategies(self):
        asyncio.create_task(self.on_cancel())

    async def on_cancel(self):
        for trading_system in self.trading_systems:
            await trading_system.stop()

    async def update_ui(self):
        logger.info("Entered update UI method of the main UI queue.")
        while True:
            data = await self.main_ui_queue.get()
            if isinstance(data, Event):
                if data.name == EventName.SENTINEL:
                    logger.info(
                        "Strategy %s send a SENTINEL.", data.content["strategy_name"]
                    )
                    await self.on_close_strategy(
                        strategy_name=data.content["strategy_name"],
                        symbol=data.content["symbol"],
                    )

            if isinstance(data, StrategyData):
                self.update_strategies(data=data)

            if isinstance(data, PriceData):
                for strategy in self.active_strategies:
                    if (
                        strategy["symbol"] == data.symbol
                        and strategy["status"] != PositionStatus.CLOSED.value
                    ):
                        self.active_strategies = self.update_price_data(data=data)

    @staticmethod
    def calculate_pnl(quantity: float, index_price: float, entry_price: float) -> float:
        pnl = 0.0

        if quantity > 0:
            pnl = round((index_price / entry_price - 1) * 100 * LEVERAGE, 2)
        if quantity == 0:
            pnl = 0
        if quantity < 0:
            pnl = round((entry_price / index_price - 1) * 100 * LEVERAGE, 2)

        return pnl

    def update_price_data(self, data: PriceData) -> List:
        copied_strategies = [pos.copy() for pos in self.active_strategies]

        if len(copied_strategies) != 0:
            for strategy in copied_strategies:
                if strategy["symbol"] == data.symbol:
                    strategy["quantity"] = str(strategy["quantity"])
                    strategy["entry_price"] = str(strategy["entry_price"])
                    strategy["mark_price"] = str(data.mark_price)
                    strategy["liquidation_price"] = str(strategy["liquidation_price"])
                    strategy["pnl"] = str(
                        round(
                            self.calculate_pnl(
                                quantity=round(float(strategy["quantity"]), 3),
                                index_price=float(data.mark_price),
                                entry_price=float(strategy["entry_price"]),
                            ),
                            3,
                        )
                    )
                    strategy["state"] = str(strategy["state"])
                    strategy["status"] = str(strategy["status"])

        return copied_strategies

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
