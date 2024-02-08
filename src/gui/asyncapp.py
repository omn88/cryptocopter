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
from kivy.uix.spinner import Spinner
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from logging_config import StrategyLogger, setup_logging_handler
from src.common.identifiers import BinanceClient, Position, StrategyConfig
from src.gui.gui_handler import GuiHandler
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
        self.dynamic_spinners: Dict = {}
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

    def strategy_config_retrieve(self):
        strategy_name = self.root.ids.strategy_spinner.text
        symbol = self.root.ids.symbol_spinner.text

        leverage_spinner = self.dynamic_spinners.get(strategy_name, {})
        orders_spinner = self.dynamic_spinners.get(strategy_name, {})
        dca_span_spinner = self.dynamic_spinners.get(strategy_name, {})

        if leverage_spinner:
            leverage = int(leverage_spinner.get("leverage_spinner").text)
        if orders_spinner:
            number_of_orders = int(orders_spinner.get("orders_spinner").text)
        if dca_span_spinner:
            dca_span = float(dca_span_spinner.get("dca_span_spinner").text)

        logger.info("lev: %s, ord: %s, dca: %s", leverage, number_of_orders, dca_span)

        return StrategyConfig(
            name=strategy_name,
            symbol=symbol,
            number_of_orders=number_of_orders,
            dca_span=dca_span,
            leverage=leverage,
            budget=20.0,
        )

    async def on_start_strategy(self):
        """Creates and starts a new trading strategy."""
        # Check if a strategy and symbol are selected
        config = self.strategy_config_retrieve()
        strategy_name_short = f"{self.strategy_mapping[config.name]}_{config.symbol}"
        if config.name != "Choose Strategy" and config.symbol != "Choose Symbol":
            for strategy in self.active_strategies:
                if (
                    strategy["name"] == config.name
                    and strategy["symbol"] == config.symbol
                ):
                    logger.info(
                        "Strategy %s with symbol %s is already running. Please select a different strategy or symbol.",
                        config.name,
                        config.symbol,
                    )
                    return  # Exit the method early
            logger.info(
                "Starting new strategy: %s on pair %s", config.name, config.symbol
            )

            strategy_logger = StrategyLogger(
                name=config.name, strategy_info=strategy_name_short
            )

            gui_handler = GuiHandler(
                main_ui_queue=self.main_ui_queue,
                ui_queue=asyncio.Queue(),
                logger=strategy_logger,
            )

            trading_system = TradingSystem(
                client=self.client,
                gui_handler=gui_handler,
                strategy_logger=strategy_logger,
                config=config,
            )
            await trading_system.initialize()
            self.trading_systems.append(trading_system)

            tab = TabbedPanelItem(
                text=strategy_name_short,
                content=StrategyTab(
                    trading_system=trading_system,
                    strategy_name=config.name,
                    symbol=config.symbol,
                    strategy_logger=strategy_logger,
                    gui_handler=gui_handler,
                ),
            )
            # Store a reference to the tab
            self.tabs[strategy_name_short] = tab
            # Add a new tab for the strategy
            self.root.add_widget(tab)
            self.root.ids.strategy_spinner.text = "Choose Strategy"
            self.root.ids.symbol_spinner.text = "Choose Symbol"

            await gui_handler.update_strategy(
                strategy_name=config.name,
                position=Position(symbol=config.symbol, leverage=config.leverage),
            )

            # Set up a logging handler for the strategy
            setup_logging_handler(
                strategy_logger=strategy_logger,
                log_display_widget=tab.content.log_display,
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

    def on_strategy_change(self, strategy_name):
        self.log_spinner_change("Strategy", strategy_name)
        self.update_dynamic_ui(strategy_name)

    def update_dynamic_ui(self, strategy_name):
        # Clear existing widgets in the dynamic UI container
        self.root.ids.dynamic_ui_container.clear_widgets()

        # Check the strategy and add relevant UI elements
        if strategy_name.startswith("RSI"):
            # Container for Leverage
            leverage_container = BoxLayout(
                orientation="vertical", size_hint_x=None, width=100
            )
            leverage_label = Label(text="Leverage", size_hint_y=None, height=20)
            leverage_spinner = Spinner(
                text="25",  # Default value
                values=[str(x) for x in range(1, 101)],
                size_hint_y=None,
                height=30,
            )
            leverage_spinner.id = "leverage_spinner"
            leverage_container.add_widget(leverage_label)
            leverage_container.add_widget(leverage_spinner)
            self.root.ids.dynamic_ui_container.add_widget(leverage_container)

            # Store reference to the leverage_spinner
            self.dynamic_spinners[strategy_name] = {
                "leverage_spinner": leverage_spinner
            }

            # Container for Number of DCA Orders
            orders_container = BoxLayout(
                orientation="vertical", size_hint_x=None, width=100
            )
            orders_label = Label(text="DCA orders", size_hint_y=None, height=20)
            orders_spinner = Spinner(
                text="2",  # Default value
                values=[str(x) for x in range(1, 9)],
                size_hint_y=None,
                height=30,
            )
            orders_spinner.id = "orders_spinner"
            orders_container.add_widget(orders_label)
            orders_container.add_widget(orders_spinner)
            self.root.ids.dynamic_ui_container.add_widget(orders_container)

            # Store reference to the orders_spinner
            self.dynamic_spinners[strategy_name]["orders_spinner"] = orders_spinner

            # Container for the DCA Span
            dca_span_container = BoxLayout(
                orientation="vertical", size_hint_x=None, width=100
            )
            dca_span_label = Label(text="DCA span", size_hint_y=None, height=20)
            dca_span_spinner = Spinner(
                text="0.005",  # Default value
                values=[str(x / 1000) for x in range(1, 11)],
                size_hint_y=None,
                height=30,
            )
            dca_span_spinner.id = "dca_span_spinner"
            dca_span_container.add_widget(dca_span_label)
            dca_span_container.add_widget(dca_span_spinner)
            self.root.ids.dynamic_ui_container.add_widget(dca_span_container)

            # Store reference to the dca_span_spinner
            self.dynamic_spinners[strategy_name]["dca_span_spinner"] = dca_span_spinner

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

    def calculate_pnl(
        self, quantity: float, index_price: float, entry_price: float, leverage: int
    ) -> float:
        pnl = 0.0

        if quantity > 0:
            pnl = round((index_price / entry_price - 1) * 100 * leverage, 2)
        if quantity == 0:
            pnl = 0
        if quantity < 0:
            pnl = round((entry_price / index_price - 1) * 100 * leverage, 2)

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
                                leverage=int(strategy["leverage"]),
                            ),
                            3,
                        )
                    )
                    strategy["state"] = str(strategy["state"])
                    strategy["status"] = str(strategy["status"])
                    strategy["leverage"] = str(strategy["leverage"])

        return copied_strategies

    def update_strategies(self, data: StrategyData):
        if any(
            strategy["symbol"] == data.position_data.symbol
            for strategy in self.active_strategies
        ):
            self.update_active_strategies_tab(data=data)
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

                if strategy["status"] == [
                    str(PositionStatus.CLOSED),
                    str(PositionStatus.CLOSING),
                ]:
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
                "leverage": str(data.position_data.leverage),
            }
        )

        logger.info(
            "Active strategies after adding position: %s", self.active_strategies
        )
