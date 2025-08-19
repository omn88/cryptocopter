"""Main module for managing trading strategies.

This module contains the `AsyncApp` class, which is responsible for creating and managing instance        for strategy in active_strategies:
            if strategy.get("name") == "HPManager":
                logger.info("Found instance of HPManager, restoring last known state.")
                self.setup_hp_manager(
                    strategy_id=strategy.get("strategy_id"), symbols_info=self.symbols_info
                )`StrategyTab` for each trading strategy. It also sets up a logging handler
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
from src.identifiers import (
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    BinanceClient,
    CoinBalance,
)
from src.database.models import Strategy
from src.portfolio.portfolio import PortfolioManager
from src.common.symbol_info import SymbolInfo
from src.gui.hp_manager.hpfront import HpFront
from src.portfolio.portfolio_gui import PortfolioUI
from src.database import TradingDatabase
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.strategy_executor import StrategyExecutor

logger = logging.getLogger("async_app")

# Load the common_widgets.kv file first
Builder.load_file("src/gui/common_widgets.kv")


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
        db: TradingDatabase,
        symbols_info: Dict[str, SymbolInfo],
        price_resolver: UsdPriceResolver,
        balances: Dict[str, CoinBalance],
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
        self.price_resolver = price_resolver
        self.balances = balances  # Dict[str, CoinBalance]
        self.main_ui_queue: asyncio.Queue = asyncio.Queue()
        self.broker: BrokerSpot = BrokerSpot()
        self.portfolio: Optional[PortfolioManager] = None
        self.portfolio_ui: Optional[PortfolioUI] = (
            None  # Reference to portfolio UI for HP manager integration
        )
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

    def setup_portfolio_manager(self) -> None:
        # Load the portfolio UI from portfolio.kv
        Builder.load_file("src/portfolio/portfolio.kv")

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
            symbols_info=self.symbols_info,
            price_resolver=self.price_resolver,
            db=self.db,
        )

        # Set up frontend UI for PortfolioManager
        self.portfolio_ui = PortfolioUI(
            ui_queue=ui_queue,
            symbols_info=self.symbols_info,
            db=self.db,
            balances=self.balances,
        )

        # Add the PortfolioManager tab to the tabbed panel
        tab = TabbedPanelItem(
            text="Portfolio",
            content=self.portfolio_ui,
        )  # Add the tab to the root tab panel
        self.root.add_widget(tab)

    async def load_all_active_strategies(self):
        active_strategies = await self.db.fetch_all_active_strategies()
        if not active_strategies:
            logger.info("No active strategy found")
            return
        logger.info("Current active strategies: %s", active_strategies)

        for strategy in active_strategies:
            strategy_name = strategy.get("name")
            if strategy_name == "HP Manager":
                logger.info("Found instance of HPManager, restoring last known state.")
                strat = {}
                strat["name"] = strategy_name
                self.active_strategies.append(strat)
                self.setup_hp_manager(
                    strategy_id=strategy.get("strategy_id"),
                    symbols_info=self.symbols_info,
                )

    def setup_hp_manager(self, strategy_id: str, symbols_info: Dict[str, SymbolInfo]):
        Builder.load_file("src/gui/hp_manager/hpfront.kv")
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
            symbols_info=self.symbols_info,
            db=self.db,
            broker=self.broker,
            ui_queue=ui_queue,
            balances=self.portfolio.balances,
            price_resolver=self.price_resolver,
            portfolio_ui_queue=(
                self.portfolio_ui.ui_queue if self.portfolio_ui else None
            ),
        )

        self.trading_systems.append(back_end)

        logger.info("Await before HP manager starts")
        front_end = HpFront(
            client=self.client,
            strategy_id=strategy_id,
            symbols_info=symbols_info,
            config_queue=back_end.config_queue,
            db=self.db,
            ui_queue=ui_queue,
            price_resolver=self.price_resolver,
            portfolio_queue=self.portfolio.worker_queue,
        )

        front_end.initialize()

        # Set HP manager reference in portfolio for sell functionality
        if self.portfolio_ui:
            self.portfolio_ui.set_hp_manager_reference(front_end, self)

        tab = TabbedPanelItem(
            text="HPManager",
            content=front_end,
        )
        # Store a reference to the tab
        self.strategies["HPManager"] = tab
        # Add a new tab for the strategy
        self.root.add_widget(tab)

    def start_strategy(self):
        """Starts a new strategy."""
        asyncio.create_task(self.on_start_strategy())

    async def on_start_strategy(self) -> None:
        """Creates and starts a new trading strategy."""
        # Check if a strategy and symbol are selected
        strategy_name: str = self.root.ids.strategy_spinner.text
        if strategy_name == "HP Manager":
            for strategy in self.active_strategies:
                if strategy["name"] == strategy_name:
                    logger.info(
                        "Strategy %s is already running. Please select a different strategy.",
                        strategy_name,
                    )
                    return
            strat = {}
            strat["name"] = strategy_name
            self.active_strategies.append(strat)
            logger.info("Starting HP manager strategy")

            strategy = Strategy(name="HP Manager", description="HP Manager")
            strategy_id = await self.db.save_strategy(strategy)

            self.setup_hp_manager(
                strategy_id=strategy_id, symbols_info=self.symbols_info
            )
            self.root.ids.strategy_spinner.text = "Choose Strategy"

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

        # Stop the broker        logger.info("Stopping the broker...")
        self.broker.stop()

        logger.info("All systems stopped successfully. Application exiting.")

    def on_strategy_change(self, strategy_name):
        self.log_spinner_change("Strategy", strategy_name)

    def log_spinner_change(self, spinner, new_value):
        """Logs a message when a spinner value changes.

        Args:
            spinner (str): The name of the spinner.
            new_value (str): The new value of the spinner.
        """
        if new_value not in ["Choose Strategy", "Choose Symbol"]:
            logger.info("%s spinner value changed to %s", spinner, new_value)
