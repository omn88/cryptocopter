"""
Buy Dip Strategy Frontend UI

Kivy-based UI for configuring and monitoring Buy Dip positions.
Displays multi-position tracking with real-time state updates.
"""

import logging
import queue
from typing import Optional, Dict
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import StringProperty, NumericProperty
from kivy.clock import Clock
from kivy.lang import Builder
from src.common.client import BinanceClient
from src.database import Database
from src.portfolio.usd_price_resolver import UsdPriceResolver

logger = logging.getLogger(__name__)


class PositionRowWidget(BoxLayout):
    """Widget for displaying a single position row."""

    pass  # Properties defined in .kv file


class BuyDipFront(BoxLayout):
    """
    Frontend UI for Buy Dip strategy.

    Displays:
    - Budget summary (total/available/locked)
    - Scrollable position list with state tracking
    - Position details (DCA level, orders, PnL)
    """

    # Observable properties for budget
    total_budget = NumericProperty(0)
    available_budget = NumericProperty(0)
    locked_budget = NumericProperty(0)
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

        # Position tracking
        self._position_widgets: Dict[str, PositionRowWidget] = (
            {}
        )  # position_id -> widget

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
            logger.error(f"Error processing UI queue: {e}", exc_info=True)

    def _handle_ui_update(self, update: dict) -> None:
        """
        Handle a UI update from backend.

        Args:
            update: Update dictionary with type and data
        """
        update_type = update.get("type")

        if update_type == "budget":
            # Update budget display
            self.total_budget = update.get("total", 0)
            self.available_budget = update.get("available", 0)
            self.locked_budget = update.get("locked", 0)
            logger.debug(
                f"Budget updated: ${self.available_budget:.2f} / ${self.total_budget:.2f}"
            )

        elif update_type == "position_created":
            # Add new position to list
            self._add_position_row(update)
            logger.info(f"Position created: {update.get('position_id')}")

        elif update_type == "position_updated":
            # Update existing position
            self._update_position_row(update)

        elif update_type == "position_completed":
            # Mark position as completed (could remove or keep with COMPLETED state)
            self._update_position_row(update)
            logger.info(
                f"Position completed: {update.get('position_id')}, PnL: {update.get('pnl', 0):.2f}"
            )

    def _add_position_row(self, position_data: dict) -> None:
        """
        Add a new position row to the UI.

        Args:
            position_data: Position data dictionary
        """
        position_id = position_data.get("position_id")
        if not position_id:
            return

        # Check if position already exists
        if position_id in self._position_widgets:
            logger.warning(f"Position {position_id} already exists, updating instead")
            self._update_position_row(position_data)
            return

        # Hide empty state label
        container = self.ids.position_list_container
        empty_label = self.ids.get("empty_state_label")
        if empty_label and empty_label.parent:
            container.remove_widget(empty_label)

        # Create new position row widget
        row = PositionRowWidget()
        self._update_row_data(row, position_data)

        # Add to container
        container.add_widget(row)
        self._position_widgets[position_id] = row

        logger.debug(f"Added position row: {position_id}")

    def _update_position_row(self, position_data: dict) -> None:
        """
        Update an existing position row.

        Args:
            position_data: Position data dictionary
        """
        position_id = position_data.get("position_id")
        if not position_id:
            return

        row = self._position_widgets.get(position_id)
        if not row:
            logger.warning(f"Position {position_id} not found in UI, adding it")
            self._add_position_row(position_data)
            return

        self._update_row_data(row, position_data)
        logger.debug(f"Updated position row: {position_id}")

    def _update_row_data(self, row: PositionRowWidget, data: dict) -> None:
        """
        Update row widget properties from position data.

        Args:
            row: PositionRowWidget to update
            data: Position data dictionary
        """
        row.position_id = data.get("position_id", "")
        row.symbol = data.get("symbol", "")

        # State with color coding
        state = data.get("state", "UNKNOWN")
        row.state = state
        row.state_color = self._get_state_color(state)

        # Top price
        top_price = data.get("top_price", 0)
        row.top_price = f"${top_price:.2f}" if top_price > 0 else "-"

        # DCA level (e.g., "3/6")
        current_level = data.get("current_dca_level", 0)
        total_levels = data.get("total_dca_levels", 6)
        row.dca_level = f"{current_level}/{total_levels}" if current_level > 0 else "-"

        # Average entry price
        avg_entry = data.get("avg_entry_price", 0)
        row.avg_entry = f"${avg_entry:.4f}" if avg_entry > 0 else "-"

        # Total invested
        invested = data.get("total_invested", 0)
        row.invested = f"${invested:.2f}" if invested > 0 else "-"

        # Pending buy order
        pending_order = data.get("pending_order")
        if pending_order and pending_order.get("price"):
            price = pending_order["price"]
            qty = pending_order.get("quantity", 0)
            row.pending_order = f"${price:.2f}\n({qty:.4f})"
        else:
            row.pending_order = "-"

        # Sell order
        sell_order = data.get("sell_order")
        if sell_order and sell_order.get("price"):
            price = sell_order["price"]
            qty = sell_order.get("quantity", 0)
            row.sell_order = f"${price:.2f}\n({qty:.4f})"
        else:
            row.sell_order = "-"

        # PnL (unrealized or realized)
        pnl = data.get("pnl", 0)
        if pnl != 0:
            row.pnl = f"${pnl:+.2f}"
            row.pnl_color = (0, 1, 0, 1) if pnl > 0 else (1, 0, 0, 1)
        else:
            row.pnl = "-"
            row.pnl_color = (0.7, 0.7, 0.7, 1)

    def _get_state_color(self, state: str) -> tuple:
        """
        Get color for position state.

        Args:
            state: Position state string

        Returns:
            RGBA color tuple
        """
        color_map = {
            "WATCHING": (0.5, 0.5, 1, 1),  # Blue - watching for top
            "POTENTIAL_TOP": (1, 1, 0, 1),  # Yellow - top detected
            "ACTIVE": (0, 1, 0, 1),  # Green - position active
            "COMPLETED": (0.5, 1, 0.5, 1),  # Light green - closed
            "INVALIDATED": (1, 0.5, 0, 1),  # Orange - top invalidated
        }
        return color_map.get(state, (0.7, 0.7, 0.7, 1))  # Gray default

    def on_stop(self) -> None:
        """
        Clean up when stopping.
        """
        if self._update_event:
            self._update_event.cancel()
        logger.info("BuyDipFront stopped")
