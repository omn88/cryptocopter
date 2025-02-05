"""Main module for managing trading strategies.

This module contains the `AsyncApp` class, which is responsible for creating and managing instances
of `StrategyTab` for each trading strategy. It also sets up a logging handler
for each strategy.
"""

import asyncio
import logging
import queue
from typing import Dict, List, Optional
from kivy.app import App
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import ListProperty
from kivy.uix.tabbedpanel import TabbedPanelItem
from kivy.uix.spinner import Spinner
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from logging_config import StrategyLogger, setup_logging_handler
from src.common.identifiers.futures import (
    Event,
    EventName,
    Position,
    StrategyConfig,
)
from src.common.identifiers.spot import (
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
)
from src.common.portfolio import PortfolioManager
from src.common.symbol_info import SymbolInfo
from src.gui.hpfront import HpFront
from src.gui.gui_handler.futures import GuiHandler as GuiHandlerFutures
from src.gui.identifiers.futures import PositionStatus, PriceData, StrategyData
from src.gui.portfolio import PortfolioUI
from src.gui.strategytab import StrategyTab
from src.trading_system.futures import TradingSystem
from src.common.identifiers.common import BinanceClient
from src.common.database import Database
from src.workers.broker_spot import BrokerSpot
from src.workers.strategy_executor import StrategyExecutor

logger = logging.getLogger("async_app")

# Load the common_widgets.kv file first
Builder.load_file("src/gui/common_widgets.kv")
Builder.load_file("src/gui/strategytab.kv")

strategy_mapping = {
    "RSI Basic": "RB",
    "RSI Extended": "RE",
    "RSI Special": "RS",
}


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

    def __init__(
        self,
        client: BinanceClient,
        db: Database,
        symbols_info: Dict[str, SymbolInfo],
        balances: Dict[str, float],
        **kwargs,
    ):
        """Initializes the `AsyncApp` instance.

        Args:
            client (BinanceClient): The Binance client to use for trading.
            db (Database): The database instance to use for database operations.
            **kwargs: Additional keyword arguments.
        """
        super(AsyncApp, self).__init__(**kwargs)
        self.client = client
        self.db = db
        self.symbols_info = symbols_info
        self.balances = balances
        self.main_ui_queue: asyncio.Queue = asyncio.Queue()
        self.broker: BrokerSpot = BrokerSpot()
        self.portfolio: Optional[PortfolioManager] = None
        self.strategies: Dict = {}
        self.dynamic_spinners: Dict = {}

    def __str__(self):
        return f"AsyncApp instance with {len(self.strategy_tabs)} strategy tabs and {len(self.trading_systems)} trading systems"

    def build(self):
        """Builds the application.

        Returns:
            Widget: The root widget of the application.
        """
        # Set the minimum size of the application window
        Window.minimum_width = 920  # Minimum width in pixels
        Window.minimum_height = 600  # Minimum height in pixels
        self.root = Builder.load_file("src/gui/asyncapp.kv")
        return self.root

    def on_start(self):
        self.setup_portfolio_manager()
        asyncio.create_task(self.load_all_active_strategies())
        asyncio.create_task(self.update_ui())

    def setup_portfolio_manager(self) -> None:
        # Load the portfolio UI from portfolio.kv
        Builder.load_file("src/gui/portfolio.kv")

        # Create a queue for frontend communication
        ui_queue: queue.Queue = queue.Queue()

        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol="ALL",
                target=SubscriptionTarget.PORTFOLIO,
                queue=ui_queue,
            ),
        )

        # Set up backend for PortfolioManager
        self.portfolio = PortfolioManager(
            broker=self.broker,
            ui_queue=ui_queue,
            balances=self.balances,
        )

        # Set up frontend UI for PortfolioManager
        frontend = PortfolioUI(ui_queue=ui_queue, symbols_info=self.symbols_info)

        # Add the PortfolioManager tab to the tabbed panel
        tab = TabbedPanelItem(
            text="Portfolio",
            content=frontend,
        )
        # Add the tab to the root tab panel
        self.root.add_widget(tab)

    async def load_all_active_strategies(self):
        active_strategies = self.db.run_db_task(self.db.fetch_all_active_strategies())
        if not active_strategies:
            logger.info("No active strategy found")
            return
        logger.info("Current active strategies: %s", active_strategies)
        for strategy in active_strategies:
            if strategy.get("name") == "HPManager":
                logger.info("Found instance of HPManager, restoring last known state.")
                self.setup_hp_manager(
                    strategy_id=strategy.get("id"), symbols_info=self.symbols_info
                )

    def setup_hp_manager(self, strategy_id: str, symbols_info: Dict[str, SymbolInfo]):
        Builder.load_file("src/gui/hpfront.kv")
        strategy_logger = StrategyLogger(name="HPManager")
        ui_queue: queue.Queue = queue.Queue()

        self.broker.subscribe(
            system_id=strategy_id,
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol="ALL",
                target=SubscriptionTarget.FRONTEND,
                queue=ui_queue,
            ),
        )
        assert self.portfolio is not None
        back_end = StrategyExecutor(
            strategy_logger=strategy_logger,
            symbols_info=self.symbols_info,
            db=self.db,
            broker=self.broker,
            ui_queue=ui_queue,
            balances=self.portfolio.balances,
        )

        self.trading_systems.append(back_end)

        logger.info("Await before HP manager starts")
        front_end = HpFront(
            strategy_logger=strategy_logger,
            client=self.client,
            strategy_id=strategy_id,
            symbols_info=symbols_info,
            config_queue=back_end.config_queue,
            db=self.db,
            ui_queue=ui_queue,
        )

        front_end.initialize_tasks()

        tab = TabbedPanelItem(
            text="HPManager",
            content=front_end,
        )
        # Set up a logging handler for the strategy
        setup_logging_handler(
            strategy_logger=strategy_logger,
            log_display_widget=tab.content.log_display,
        )
        # Store a reference to the tab
        self.strategies["HPManager"] = tab
        # Add a new tab for the strategy
        self.root.add_widget(tab)

    def start_strategy(self):
        """Starts a new strategy."""
        asyncio.create_task(self.on_start_strategy())

    def futures_strategy_config_retrieve(self) -> StrategyConfig:
        strategy_name: str = self.root.ids.strategy_spinner.text

        widgets = self.dynamic_spinners.get(strategy_name, {})

        return StrategyConfig(
            name=strategy_name,
            symbol=widgets.get("symbol_spinner").text,
            number_of_orders=int(widgets.get("orders_spinner").text),
            dca_span=float(widgets.get("dca_span_spinner").text),
            leverage=int(widgets.get("leverage_spinner").text),
            budget=20.0,
        )

    async def on_start_strategy(self) -> None:
        """Creates and starts a new trading strategy."""
        # Check if a strategy and symbol are selected
        strategy_name: str = self.root.ids.strategy_spinner.text
        if strategy_name.startswith("RSI"):
            config = self.futures_strategy_config_retrieve()
            strategy_name_short = f"{strategy_mapping[config.name]}_{config.symbol}"
            if config.symbol != "Choose Symbol":
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

                strategy_logger = StrategyLogger(name=config.name)

                gui_handler = GuiHandlerFutures(
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
                self.strategies[strategy_name_short] = tab
                # Add a new tab for the strategy
                self.root.add_widget(tab)
                self.root.ids.strategy_spinner.text = "Choose Strategy"

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

                strategy_id = self.db.run_db_task(
                    self.db.insert_strategy(name=config.name, description=str(config))
                )

                await trading_system.start_trading()
            else:
                logger.info("App: Please select a symbol.")

        if strategy_name == "HP Manager":
            self.db.run_db_task(self.db.create_hp_list_table())
            for strategy in self.active_strategies:
                if strategy["name"] == config.name:
                    logger.info(
                        "Strategy %s is already running. Please select a different strategy.",
                        config.name,
                    )
                    return
            strat = {}
            strat["name"] = strategy_name
            self.active_strategies.append(strat)
            logger.info("Starting HP manager strategy")

            strategy_id = self.db.run_db_task(
                self.db.insert_strategy(name="HPManager", description="HPManager")
            )
            self.setup_hp_manager(
                strategy_id=strategy_id, symbols_info=self.symbols_info
            )
            self.root.ids.strategy_spinner.text = "Choose Strategy"

    async def on_close_strategy(self, strategy_name, symbol):
        # Get the tab for the strategy
        tab = self.strategies[f"{strategy_mapping[strategy_name]}_{symbol}"]

        # Remove the tab from the TabbedPanel
        self.root.remove_widget(tab)

        if len(self.root.tab_list) > 0:
            self.root.switch_to(self.root.tab_list[0])

    def cancel_all_strategies(self):
        asyncio.create_task(self.shutdown())

    def on_stop(self):
        """Override the on_stop method to handle application shutdown."""
        logger.info("Application is shutting down. Cleaning up resources.")
        self.shutdown()

    def shutdown(self):
        """Handle the shutdown process for gracefully stopping all systems and resources."""
        # First, cancel all running strategies
        if self.trading_systems:
            logger.info("Stopping all active strategies...")
            for system in self.trading_systems:
                logger.info("System: %s", system)
                assert isinstance(system, StrategyExecutor)
                system.stop()

        logger.info("Stop portfolio")
        self.portfolio.stop()

        # Stop the broker
        logger.info("Stopping the broker...")
        self.broker.stop()

        # Stop the database worker
        logger.info("Stopping the database worker...")
        self.db.stop_worker()

        logger.info("All systems stopped successfully. Application exiting.")

    def on_strategy_change(self, strategy_name):
        self.log_spinner_change("Strategy", strategy_name)
        self.update_dynamic_ui(strategy_name)

    def update_dynamic_ui(self, strategy_name):
        # Clear existing widgets in the dynamic UI container
        self.root.ids.dynamic_ui_container.clear_widgets()

        # Check the strategy and add relevant UI elements
        if strategy_name.startswith("RSI"):
            # Container for Symbol
            symbol_container = BoxLayout(
                orientation="vertical", size_hint_x=None, width=100
            )
            symbol_label = Label(text="Symbol", size_hint_y=None, height=20)
            symbol_spinner = Spinner(
                text="BTCUSDT",  # Default value
                values=["BTCUSDT", "ETHUSDT", "ETHBTC"],
                size_hint_y=None,
                height=30,
            )
            symbol_spinner.id = "symbol_spinner"
            symbol_container.add_widget(symbol_label)
            symbol_container.add_widget(symbol_spinner)
            self.root.ids.dynamic_ui_container.add_widget(symbol_container)

            # Store reference to the symbol_spinner
            self.dynamic_spinners[strategy_name] = {"symbol_spinner": symbol_spinner}

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
            self.dynamic_spinners[strategy_name]["leverage_spinner"] = leverage_spinner

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
            try:
                data = await self.main_ui_queue.get()
                if isinstance(data, Event):
                    if data.name == EventName.SENTINEL:
                        logger.info(
                            "Strategy %s send a SENTINEL.",
                            data.content["strategy_name"],
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
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.1)

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
                    pnl = round(
                        self.calculate_pnl(
                            quantity=round(float(strategy["quantity"]), 3),
                            index_price=float(data.mark_price),
                            entry_price=float(strategy["entry_price"]),
                            leverage=int(strategy["leverage"]),
                        ),
                        3,
                    )
                    strategy["quantity"] = str(strategy["quantity"])
                    strategy["entry_price"] = str(strategy["entry_price"])
                    strategy["mark_price"] = str(data.mark_price)
                    strategy["liquidation_price"] = str(strategy["liquidation_price"])
                    strategy["pnl"] = str(pnl)
                    # strategy["pnl_fiat"] = str(
                    #     round(
                    #         pnl_percent * round(abs(float(strategy["quantity"])), 3), 2
                    #     )
                    # )
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
                strategy["margin"] = str(round(data.position_data.margin, 2))

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
                "margin": str(round(data.position_data.margin, 2)),
            }
        )

        logger.info(
            "Active strategies after adding position: %s", self.active_strategies
        )

    def log_spinner_change(self, spinner, new_value):
        """Logs a message when a spinner value changes.

        Args:
            spinner (str): The name of the spinner.
            new_value (str): The new value of the spinner.
        """
        if new_value not in ["Choose Strategy", "Choose Symbol"]:
            logger.info("%s spinner value changed to %s", spinner, new_value)
