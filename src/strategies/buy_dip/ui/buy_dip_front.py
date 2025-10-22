"""
Buy Dip Strategy Frontend UI

Kivy-based UI for configuring and monitoring Buy Dip positions.
Displays multi-position tracking with real-time state updates.
"""

import logging
import queue
import time
from decimal import Decimal
from typing import Optional, Dict, TYPE_CHECKING

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

from src.common.client import BinanceClient
from src.database import Database
from src.portfolio.usd_price_resolver import UsdPriceResolver

if TYPE_CHECKING:
    from src.portfolio.portfolio import PortfolioManager

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
    status_text = StringProperty("Stopped")
    symbol_text = StringProperty("BTCUSDC")

    def __init__(
        self,
        client: BinanceClient,
        config_queue: queue.Queue,
        db: Database,
        ui_queue: queue.Queue,
        price_resolver: UsdPriceResolver,
        executor_control=None,  # Callback to control executor (start/stop)
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
            executor_control: Dict with start/stop callbacks for executor control
        """
        super().__init__(**kwargs)
        self.client = client
        self.config_queue = config_queue
        self.db = db
        self.ui_queue = ui_queue
        self.price_resolver = price_resolver
        self.executor_control = executor_control or {}
        self.portfolio: Optional["PortfolioManager"] = None  # Will be set by AsyncApp

        # Position tracking
        self._position_widgets: Dict[str, PositionRowWidget] = (
            {}
        )  # position_id -> widget
        self._completed_positions: Dict[str, float] = (
            {}
        )  # position_id -> completion_timestamp

        # Strategy state
        self._is_running = False
        self._current_order_pct = 2.0  # Track current order percentage
        self._pending_config: Optional[Dict] = None  # Config to apply on start

        # UI update scheduling
        self._update_interval = 0.1  # 100ms
        self._update_event = None
        self._cleanup_interval = 60.0  # 60 seconds - check for old completed positions
        self._cleanup_event = None

        logger.info("BuyDipFront initialized")

    def initialize(self) -> None:
        """
        Start UI update loop.
        """
        self._update_event = Clock.schedule_interval(
            self._process_ui_queue, self._update_interval
        )
        self._cleanup_event = Clock.schedule_interval(
            self._cleanup_old_positions, self._cleanup_interval
        )
        # Don't set status here - it's set by asyncapp.py
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

            # Track INVALIDATED positions for auto-removal
            state = update.get("state")
            position_id = update.get("position_id")
            if state == "INVALIDATED" and position_id:
                self._completed_positions[position_id] = time.time()
                logger.info(f"Position invalidated: {position_id}")

        elif update_type == "position_completed":
            # Mark position as completed and schedule for removal after 5 minutes
            self._update_position_row(update)
            position_id = update.get("position_id")
            if position_id:
                self._completed_positions[position_id] = time.time()
            logger.info(
                f"Position completed: {position_id}, PnL: {update.get('pnl', 0):.2f}"
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

    def _get_portfolio_usdc(self) -> float:
        """
        Get available USDC from Portfolio inventory.

        Returns:
            Total available USDC
        """
        if not self.portfolio or not hasattr(self.portfolio, "inventory"):
            logger.warning("Portfolio not available, returning current total_budget")
            return float(self.total_budget)

        total_usdc = 0.0
        for item in self.portfolio.inventory:
            if item.coin == "USDC":
                total_usdc += item.available_quantity

        return total_usdc

    def toggle_strategy(self) -> None:
        """
        Toggle strategy start/stop.
        """
        if self._is_running:
            # Stop strategy
            self._stop_strategy()
        else:
            # Start strategy
            self._start_strategy()

    def _start_strategy(self) -> None:
        """
        Start the strategy executor.
        """
        if self.executor_control.get("start"):
            self.executor_control["start"]()
            self._is_running = True
            self.status_text = "Running"
            logger.info("Buy Dip strategy started via UI")

            # If there's a pending config, apply it now that executor is running
            if self._pending_config:
                logger.info(f"Applying pending config: {self._pending_config}")
                self.config_queue.put(self._pending_config)
                self._pending_config = None  # Clear pending
        else:
            logger.warning("No executor start callback configured")

    def _stop_strategy(self) -> None:
        """
        Stop the strategy executor.
        """
        if self.executor_control.get("stop"):
            self.executor_control["stop"]()
            self._is_running = False
            self.status_text = "Stopped"
            logger.info("Buy Dip strategy stopped via UI")

            # Clear all positions from UI when stopping
            self._clear_all_positions()
        else:
            logger.warning("No executor stop callback configured")

    def _clear_all_positions(self) -> None:
        """
        Clear all position rows from UI.
        """
        # Get the position container
        position_container = self.ids.position_list_container

        # Remove all position widgets
        for widget in list(self._position_widgets.values()):
            position_container.remove_widget(widget)

        # Clear tracking dicts
        self._position_widgets.clear()
        self._completed_positions.clear()

        logger.info("Cleared all position rows from UI")

    def _cleanup_old_positions(self, dt) -> None:
        """
        Remove COMPLETED/INVALIDATED positions older than 5 minutes.

        Args:
            dt: Time delta (from Clock.schedule_interval)
        """
        current_time = time.time()
        positions_to_remove = []

        # Find positions older than 5 minutes (300 seconds)
        for position_id, completion_time in self._completed_positions.items():
            if current_time - completion_time > 300:  # 5 minutes
                positions_to_remove.append(position_id)

        # Remove old positions
        if positions_to_remove:
            container = self.ids.position_list_container
            for position_id in positions_to_remove:
                if position_id in self._position_widgets:
                    widget = self._position_widgets[position_id]
                    container.remove_widget(widget)
                    del self._position_widgets[position_id]
                    logger.info(f"Removed old completed position: {position_id}")

                del self._completed_positions[position_id]

    def show_config_dialog(self) -> None:
        """
        Show configuration dialog for strategy parameters.
        """
        # Create config form
        content = BoxLayout(orientation="vertical", padding=10, spacing=10)

        # Title
        content.add_widget(
            Label(
                text="Buy Dip Strategy Configuration",
                size_hint_y=None,
                height=40,
                font_size="16sp",
                bold=True,
            )
        )

        # Config grid
        grid = GridLayout(cols=2, spacing=10, size_hint_y=None, height=200)

        # Symbol
        grid.add_widget(Label(text="Symbol:", halign="right", size_hint_x=0.4))
        symbol_input = TextInput(
            text=self.symbol_text, multiline=False, size_hint_x=0.6
        )
        grid.add_widget(symbol_input)

        # Budget - show available from Portfolio
        available_usdc = self._get_portfolio_usdc()
        grid.add_widget(Label(text="Budget ($):", halign="right", size_hint_x=0.4))
        budget_input = TextInput(
            text=f"{available_usdc:.2f}", multiline=False, size_hint_x=0.6
        )
        grid.add_widget(budget_input)

        # Show portfolio info
        grid.add_widget(Label(text="", size_hint_x=0.4))
        grid.add_widget(
            Label(
                text=f"Available in Portfolio: ${available_usdc:.2f}",
                font_size="10sp",
                color=(0, 0.8, 0, 1),
                size_hint_x=0.6,
                halign="left",
            )
        )

        # Order %
        grid.add_widget(Label(text="Order Size (%):", halign="right", size_hint_x=0.4))

        # Get current order % from budget manager if available
        current_order_pct = "2.0"
        if hasattr(self, "_current_order_pct"):
            current_order_pct = str(self._current_order_pct)

        order_pct_input = TextInput(
            text=current_order_pct, multiline=False, size_hint_x=0.6
        )
        grid.add_widget(order_pct_input)

        # Info label
        grid.add_widget(Label(text="", size_hint_x=0.4))
        grid.add_widget(
            Label(
                text="Applied immediately when you click Apply",
                font_size="10sp",
                color=(0.8, 0.8, 0, 1),
                size_hint_x=0.6,
            )
        )

        content.add_widget(grid)

        # Create popup first (so it can be referenced in callbacks)
        popup = Popup(
            title="Configuration",
            content=content,
            size_hint=(0.5, 0.6),
            auto_dismiss=True,
        )

        # Buttons
        btn_box = BoxLayout(size_hint_y=None, height=40, spacing=10)

        def apply_config(instance):
            try:
                # Parse values
                new_symbol = symbol_input.text.strip().upper()
                new_budget = Decimal(budget_input.text.strip())
                new_order_pct = Decimal(order_pct_input.text.strip())

                # Validate
                if not new_symbol:
                    logger.error("Symbol cannot be empty")
                    return

                if new_budget <= 0:
                    logger.error("Budget must be positive")
                    return

                if new_order_pct <= 0 or new_order_pct > 100:
                    logger.error("Order % must be between 0 and 100")
                    return

                # Update UI display
                self.symbol_text = new_symbol
                self.total_budget = float(new_budget)
                self._current_order_pct = float(new_order_pct)

                # Build config update
                config_update = {
                    "type": "update_config",
                    "symbol": new_symbol,
                    "total_budget": new_budget,
                    "order_budget_pct": new_order_pct,
                }

                # If strategy is running, send immediately
                # Otherwise, store for when Start is clicked
                if self._is_running:
                    logger.info("Strategy running - applying config immediately")
                    self.config_queue.put(config_update)
                else:
                    logger.info("Strategy stopped - config will apply on Start")
                    self._pending_config = config_update

                logger.info(
                    f"Config updated: symbol={new_symbol}, "
                    f"budget=${new_budget}, order_pct={new_order_pct}%"
                )

                popup.dismiss()

            except ValueError as e:
                logger.error(f"Invalid configuration values: {e}")
            except Exception as e:
                logger.error(f"Error applying config: {e}", exc_info=True)

        apply_btn = Button(text="Apply", on_release=apply_config)
        cancel_btn = Button(text="Cancel", on_release=lambda x: popup.dismiss())

        btn_box.add_widget(apply_btn)
        btn_box.add_widget(cancel_btn)
        content.add_widget(btn_box)

        popup.open()

    def on_stop(self) -> None:
        """
        Clean up when stopping.
        """
        if self._update_event:
            self._update_event.cancel()
        logger.info("BuyDipFront stopped")
