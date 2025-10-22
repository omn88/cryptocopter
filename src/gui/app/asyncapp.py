"""Main module for managing trading strategies.

This module contains the `AsyncApp` class, which is responsible for creating and managing instance        for strategy in active_strategies:
            if strategy.get("name") == "HPManager":
                logger.info("Found instance of HPManager, restoring last known state.")
                self.setup_hp_manager(
                    strategy_id=strategy.get("strategy_id"), symbols=self.price_resolver.symbols
                )`StrategyTab` for each trading strategy. It also sets up a logging handler
for each strategy.
"""

import asyncio
import logging
import queue
import time
from typing import Optional
from kivy.app import App
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import ListProperty
from kivy.uix.tabbedpanel import TabbedPanelItem
from kivy.uix.widget import Widget
from src.common.client import BinanceClient
from src.common.identifiers import (
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
)
from src.portfolio.portfolio import PortfolioManager
from src.gui.hp_manager.hpfront import HpFront
from src.portfolio.portfolio_gui import PortfolioUI
from src.database import Database
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
        db: Database,
        price_resolver: UsdPriceResolver,
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
        self.price_resolver = price_resolver
        self.broker: BrokerSpot = BrokerSpot()
        self.portfolio: Optional[PortfolioManager] = None
        self.portfolio_ui: Optional[PortfolioUI] = (
            None  # Reference to portfolio UI for HP manager integration
        )

    def __str__(self) -> str:
        return f"AsyncApp instance with {len(self.strategy_tabs)} strategy tabs and {len(self.trading_systems)} trading systems"

    def build(self) -> Widget:
        """Builds the application.

        Returns:
            Widget: The root widget of the application.
        """
        # Set the minimum size of the application window
        Window.minimum_width = 920  # Minimum width in pixels
        Window.minimum_height = 600  # Minimum height in pixels
        self.root = Builder.load_file("src/gui/app/asyncapp.kv")
        return self.root

    def on_start(self) -> None:
        self.setup_portfolio_manager()
        # Always setup HP Manager as default strategy
        self.setup_hp_manager()
        # Optionally setup Buy Dip strategy (uncomment to enable)
        self.setup_buy_dip()

    def setup_buy_dip(self, strategy_id: Optional[str] = None) -> None:
        """Setup Buy Dip strategy."""
        from decimal import Decimal
        from kivy.lang import Builder
        from src.strategies.buy_dip.config import BuyDipConfig
        from src.strategies.buy_dip.executor import BuyDipExecutor
        from src.strategies.buy_dip.ui import BuyDipFront

        strategy_name = "BuyDip"
        if strategy_id is None:
            strategy_id = "buy_dip_default"

        logger.info("Setting up Buy Dip strategy with ID: %s", strategy_id)

        # Load UI (after imports so BuyDipFront class is registered)
        Builder.load_file("src/strategies/buy_dip/ui/buy_dip_front.kv")

        # Create UI queue and config queue
        ui_queue: queue.Queue = queue.Queue()
        config_queue: queue.Queue = queue.Queue()

        # Create strategy configuration
        config = BuyDipConfig(
            # Detection parameters
            min_consecutive_rising=3,
            min_total_gain_pct=0.3,
            atr_period=14,
            atr_multiplier=0.5,
            min_pullback_pct=0.5,
            # DCA levels (φ, e, π, 5%, 10%, 15%)
            dca_distances_pct=[1.618, 2.718, 3.142, 5.0, 10.0, 15.0],
        )

        # Create executor (but don't start yet - UI will control it)
        executor = BuyDipExecutor(
            db=self.db,
            broker=self.broker,
            client=self.client,
            ui_queue=ui_queue,
            config=config,
            total_budget=Decimal("10000"),  # $10k budget
            order_budget_pct=Decimal("2.0"),  # 2% per order
            symbols=["BTCUSDC"],
            config_queue=config_queue,  # Pass config queue for runtime updates
        )

        # Store in trading systems
        self.trading_systems.append(executor)

        # Create executor control callbacks
        executor_control = {
            "start": lambda: executor.start(),
            "stop": lambda: executor.stop(),
            "is_running": lambda: hasattr(executor, "thread")
            and executor.thread.is_alive(),
        }

        # Create frontend with executor control and portfolio reference
        frontend = BuyDipFront(
            client=self.client,
            config_queue=config_queue,  # Share config queue with executor
            db=self.db,
            ui_queue=ui_queue,
            price_resolver=self.price_resolver,
            executor_control=executor_control,
        )

        # Pass portfolio reference for getting USDC balance
        frontend.portfolio = self.portfolio

        # Set initial budget display from portfolio
        usdc_available = self._get_portfolio_usdc_balance()
        frontend.total_budget = usdc_available
        frontend.available_budget = usdc_available
        frontend.locked_budget = 0
        frontend.symbol_text = "BTCUSDC"
        frontend.status_text = "Stopped"

        frontend.initialize()

        # Create tab
        tab = TabbedPanelItem(
            text=strategy_name,
            content=frontend,
        )

        # Store strategy info
        strategy_info = {
            "name": strategy_name,
            "tab": tab,
            "backend": executor,
            "frontend": frontend,
        }
        self.active_strategies.append(strategy_info)

        # Add tab
        self.root.add_widget(tab)

        # Don't auto-start - let user start via UI button
        # executor.start()

        logger.info("Buy Dip strategy setup complete (not started).")

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
        logger.info("Subscribed portfolio to broker price updates.")

        # Set up backend for PortfolioManager
        self.portfolio = PortfolioManager(
            broker=self.broker,
            ui_queue=ui_queue,
            price_resolver=self.price_resolver,
            db=self.db,
        )

        # Set up frontend UI for PortfolioManager
        self.portfolio_ui = PortfolioUI(
            ui_queue=ui_queue,
            strategy_config_queue=queue.Queue(),
            price_resolver=self.price_resolver,
            db=self.db,
        )

        # Initialize the PortfolioUI to start UI queue processing
        self.portfolio_ui.initialize()

        # Add the PortfolioManager tab to the tabbed panel
        tab = TabbedPanelItem(
            text="Portfolio",
            content=self.portfolio_ui,
        )  # Add the tab to the root tab panel
        self.root.add_widget(tab)

        # Wait for portfolio initialization to complete before proceeding
        logger.info("Waiting for portfolio initialization to complete...")
        wait_time = 0.1  # Start with 100ms
        max_wait_time = 8.0  # Cap at 8 seconds
        total_wait_time = 0.0
        timeout = 30.0

        while (
            not self.portfolio.initialization_complete.is_set()
            and total_wait_time < timeout
        ):
            time.sleep(wait_time)
            total_wait_time += wait_time
            # Exponential backoff with cap
            wait_time = min(wait_time * 1.5, max_wait_time)
            logger.debug(
                f"Portfolio initialization check: waited {total_wait_time:.1f}s, next wait: {wait_time:.1f}s"
            )

        if self.portfolio.initialization_complete.is_set():
            logger.info(
                f"Portfolio initialization completed after {total_wait_time:.1f}s - ready to setup HP manager"
            )
        else:
            logger.error(
                f"Portfolio initialization timed out after {timeout}s - proceeding with potentially empty inventory"
            )

    def setup_hp_manager(self, strategy_id: Optional[str] = None) -> None:
        # Use existing strategy ID or generate new one
        strategy_name = "HPManager"
        if strategy_id is None:
            strategy_id = "hp_manager_default"

        logger.info("Setting up HP Manager with strategy ID: %s", strategy_id)
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
            db=self.db,
            broker=self.broker,
            ui_queue=ui_queue,
            inventory=self.portfolio.inventory,
            price_resolver=self.price_resolver,
            portfolio_ui_queue=(
                self.portfolio_ui.ui_queue if self.portfolio_ui else None
            ),
        )

        self.trading_systems.append(back_end)

        front_end = HpFront(
            client=self.client,
            config_queue=back_end.config_queue,
            db=self.db,
            ui_queue=ui_queue,
            price_resolver=self.price_resolver,
            portfolio_queue=self.portfolio.worker_queue,
        )

        front_end.initialize()

        if self.portfolio_ui:
            self.portfolio_ui.strategy_config_queue = back_end.config_queue

        tab = TabbedPanelItem(
            text=strategy_name,
            content=front_end,
        )
        # Store a reference to the strategy
        strategy_info = {
            "name": strategy_name,
            "tab": tab,
            "backend": back_end,
            "frontend": front_end,
        }
        self.active_strategies.append(strategy_info)
        # Add a new tab for the strategy as default
        self.root.add_widget(tab)
        # Make HP Manager the default active tab
        self.root.switch_to(tab)

        logger.info("HP Manager setup complete.")

    def start_strategy(self) -> None:
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
            self.root.ids.strategy_spinner.text = "Choose Strategy"

    def _get_portfolio_usdc_balance(self) -> float:
        """
        Get available USDC balance from Portfolio inventory.

        Returns:
            Total available USDC quantity
        """
        if not self.portfolio or not hasattr(self.portfolio, "inventory"):
            logger.warning("Portfolio not initialized, returning 0 USDC")
            return 0.0

        total_usdc = 0.0
        for item in self.portfolio.inventory:
            if item.coin == "USDC":
                total_usdc += item.available_quantity

        logger.info(f"Portfolio USDC available: ${total_usdc:.2f}")
        return total_usdc

    def cancel_all_strategies(self) -> None:
        asyncio.create_task(self.shutdown())

    def on_stop(self) -> None:
        """Override the on_stop method to handle application shutdown."""
        logger.info("Application is shutting down. Cleaning up resources.")
        asyncio.create_task(self.shutdown())

    async def shutdown(self) -> None:
        """Handle the shutdown process for gracefully stopping all systems and resources."""
        # First, cancel all running strategies
        if self.trading_systems:
            logger.info("Stopping all active strategies...")
            for system in self.trading_systems:
                logger.info("System: %s", system)
                # Handle both StrategyExecutor and BuyDipExecutor
                if hasattr(system, "stop"):
                    system.stop()

        logger.info("Stop portfolio")
        if self.portfolio:
            self.portfolio.stop()

        # Stop the broker
        logger.info("Stopping the broker...")
        self.broker.stop()

        logger.info("All systems stopped successfully. Application exiting.")

    def on_strategy_change(self, strategy_name: str) -> None:
        self.log_spinner_change("Strategy", strategy_name)

    def log_spinner_change(self, spinner: str, new_value: str) -> None:
        """Logs a message when a spinner value changes.

        Args:
            spinner (str): The name of the spinner.
            new_value (str): The new value of the spinner.
        """
        if new_value not in ["Choose Strategy", "Choose Symbol"]:
            logger.info("%s spinner value changed to %s", spinner, new_value)
