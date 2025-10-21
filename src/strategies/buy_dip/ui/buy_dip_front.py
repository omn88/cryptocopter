"""
Buy Dip Strategy Frontend UI

Kivy-based UI for configuring and monitoring Buy Dip positions.
"""

import logging
import queue
from typing import Optional
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import StringProperty, NumericProperty
from kivy.clock import Clock
from src.common.client import BinanceClient
from src.database import Database
from src.portfolio.usd_price_resolver import UsdPriceResolver

logger = logging.getLogger(__name__)


class BuyDipFront(BoxLayout):
    """
    Frontend UI for Buy Dip strategy.

    Displays:
    - Strategy configuration (budget, order size %)
    - Active positions with their states
    - Budget utilization
    - Recent order activity
    """

    # Observable properties
    total_budget = NumericProperty(0)
    available_budget = NumericProperty(0)
    locked_budget = NumericProperty(0)
    active_positions = NumericProperty(0)
    total_positions = NumericProperty(0)
    status_text = StringProperty("Initializing...")

    def __init__(
        self,
        client: BinanceClient,
        config_queue: queue.Queue,
        db: Database,
        ui_queue: queue.Queue,
        price_resolver: UsdPriceResolver,
        **kwargs,
    ):
        """
        Initialize Buy Dip frontend.

        Args:
            client: Binance client
            config_queue: Queue for strategy configuration
            db: Database instance
            ui_queue: Queue for UI updates from backend
            price_resolver: Price resolver for USD conversions
        """
        super().__init__(**kwargs)
        self.client = client
        self.config_queue = config_queue
        self.db = db
        self.ui_queue = ui_queue
        self.price_resolver = price_resolver

        # UI update scheduling
        self._update_interval = 0.1  # 100ms
        self._update_event = None

        logger.info("BuyDipFront initialized")

    def initialize(self) -> None:
        """
        Start UI update loop.
        """
        self._update_event = Clock.schedule_interval(
            self._process_ui_queue, self._update_interval
        )
        self.status_text = "Running"
        logger.info("BuyDipFront UI update loop started")

    def _process_ui_queue(self, dt) -> None:
        """
        Process UI updates from backend.

        Args:
            dt: Time delta (from Clock.schedule_interval)
        """
        try:
            while not self.ui_queue.empty():
                update = self.ui_queue.get_nowait()
                self._handle_ui_update(update)
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error processing UI queue: {e}")

    def _handle_ui_update(self, update: dict) -> None:
        """
        Handle a UI update from backend.

        Args:
            update: Update dictionary with type and data
        """
        update_type = update.get("type")

        if update_type == "budget":
            self.total_budget = update.get("total", 0)
            self.available_budget = update.get("available", 0)
            self.locked_budget = update.get("locked", 0)

        elif update_type == "positions":
            self.active_positions = update.get("active", 0)
            self.total_positions = update.get("total", 0)

        elif update_type == "position_created":
            logger.info(
                f"Position created: {update.get('position_id')} "
                f"for {update.get('symbol')}"
            )

        elif update_type == "order_placed":
            logger.info(
                f"Order placed: {update.get('order_id')} " f"@ {update.get('price')}"
            )

        elif update_type == "order_filled":
            logger.info(
                f"Order filled: {update.get('order_id')} " f"@ {update.get('price')}"
            )

        elif update_type == "position_closed":
            logger.info(
                f"Position closed: {update.get('position_id')} "
                f"PnL: ${update.get('pnl', 0):.2f}"
            )

    def on_stop(self) -> None:
        """
        Clean up when stopping.
        """
        if self._update_event:
            self._update_event.cancel()
        logger.info("BuyDipFront stopped")
