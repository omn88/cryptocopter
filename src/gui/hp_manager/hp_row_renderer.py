"""
HP Row Renderer Module

This module handles the rendering of individual HP position rows in the UI,
including widget creation, styling, and layout management.

Single Responsibility: UI widget creation and visual presentation
"""

from typing import Dict, Callable
from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.graphics import Color, Rectangle, Line


class HPRowRenderer:
    """
    Responsible for creating and styling HP position row widgets.

    Handles:
    - Widget creation for HP rows
    - Visual styling based on row type
    - Column label creation
    - Button layout and state management
    """

    def __init__(
        self,
        toggle_expansion_callback: Callable[[str], None],
        sell_callback: Callable[[str, str, str, str], None],
        cancel_callback: Callable[[str, str, str], None],
    ):
        """
        Initialize renderer with callbacks to main UI.

        Args:
            toggle_expansion_callback: Callback for expand/collapse actions
            sell_callback: Callback for sell button clicks
            cancel_callback: Callback for cancel button clicks
        """
        self.toggle_expansion_callback = toggle_expansion_callback
        self.sell_callback = sell_callback
        self.cancel_callback = cancel_callback

    def create_hp_row_widget(self, hp_data: Dict) -> Widget:
        """
        Create a widget for an HP row.

        Args:
            hp_data: Dictionary containing HP position data

        Returns:
            BoxLayout widget representing the row
        """
        # Create the main row container
        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=40,
            spacing=2,
            padding=[5, 2, 5, 2],
        )

        # Apply styling
        self._apply_row_styling(row, hp_data)

        # Left padding for child rows
        if hp_data.get("is_child", False):
            row.add_widget(Label(text="", size_hint_x=None, width=20))

        # Add expand/collapse button
        self._add_expansion_button(row, hp_data)

        # Add data columns
        self._add_data_columns(row, hp_data)

        # Add action buttons
        self._add_action_buttons(row, hp_data)

        return row

    def _apply_row_styling(self, row: BoxLayout, hp_data: Dict) -> None:
        """Apply background color and border to row based on type."""
        is_child = hp_data.get("is_child", False)
        side = hp_data.get("side", "")

        # Determine background color
        if not is_child and side == "PARENT":
            bg_color = [0.15, 0.25, 0.35, 0.8]  # Parent: Blue
        elif is_child and side == "BUY":
            bg_color = [0.15, 0.3, 0.2, 0.7]  # Buy child: Green
        elif is_child and side == "SELL":
            bg_color = [0.3, 0.15, 0.15, 0.7]  # Sell child: Red
        else:
            bg_color = [0.2, 0.2, 0.2, 0.5]  # Default: Gray

        # Add background and border graphics
        with row.canvas.before:
            Color(*bg_color)
            rect = Rectangle(size=row.size, pos=row.pos)
            Color(1, 1, 1, 0.1)
            line = Line(width=1)

        # Bind graphics update to size/position changes
        def update_graphics(*args):
            rect.size = row.size
            rect.pos = row.pos
            line.points = [row.x, row.y, row.x + row.width, row.y]

        row.bind(size=update_graphics, pos=update_graphics)

    def _add_expansion_button(self, row: BoxLayout, hp_data: Dict) -> None:
        """Add expand/collapse button for parent rows."""
        has_children = hp_data.get("has_children", False)
        is_expanded = hp_data.get("is_expanded", False)

        if has_children:
            expand_btn = Button(
                text="▼" if is_expanded else "▶",
                size_hint_x=None,
                width=30,
                height=30,
            )
            hp_id = hp_data.get("hp_id", "")
            expand_btn.bind(on_release=lambda x: self.toggle_expansion_callback(hp_id))
            row.add_widget(expand_btn)
        else:
            row.add_widget(Label(text="", size_hint_x=None, width=30))

    def _add_data_columns(self, row: BoxLayout, hp_data: Dict) -> None:
        """Add all data columns to the row."""
        is_child = hp_data.get("is_child", False)
        side = hp_data.get("side", "")

        # Column 1: Side/Type
        row.add_widget(self.create_column_label(side if is_child else "HP", 0.08))

        # Column 2: HP ID
        row.add_widget(self.create_column_label(hp_data.get("hp_id", ""), 0.1))

        # Column 3: Coin
        row.add_widget(self.create_column_label(hp_data.get("coin", ""), 0.08))

        # Column 4: Quantity
        row.add_widget(self.create_column_label(hp_data.get("quantity", "0.0"), 0.12))

        # Column 5: Buy Price
        row.add_widget(self.create_column_label(hp_data.get("buy_price", "0.0"), 0.09))

        # Column 6: Sell Price
        row.add_widget(self.create_column_label(hp_data.get("sell_price", "—"), 0.09))

        # Column 7: Current Price
        row.add_widget(
            self.create_column_label(hp_data.get("current_price", "0.0"), 0.09)
        )

        # Column 8: Progress
        progress_text = self._calculate_progress(hp_data)
        row.add_widget(self.create_column_label(progress_text, 0.07))

        # Column 9: Net
        row.add_widget(self.create_column_label(hp_data.get("net", "0.0"), 0.09))

        # Column 10: State
        row.add_widget(self.create_column_label(hp_data.get("state", ""), 0.1))

    def _calculate_progress(self, hp_data: Dict) -> str:
        """Calculate progress percentage for the position."""
        progress_value = 0.0

        if hp_data.get("sell_completeness"):
            # For SELL positions, use sell_completeness as percentage
            try:
                progress_value = float(hp_data.get("sell_completeness", 0.0)) * 100
            except (ValueError, TypeError):
                progress_value = 0.0
        elif hp_data.get("realized_quantity") and hp_data.get("quantity"):
            # For other positions, calculate based on realized vs total quantity
            try:
                realized = float(hp_data.get("realized_quantity", 0))
                total = float(hp_data.get("quantity", 1))  # Avoid division by zero
                progress_value = (realized / total) * 100 if total > 0 else 0.0
            except (ValueError, TypeError):
                progress_value = 0.0

        return f"{progress_value:.1f}%"

    def _add_action_buttons(self, row: BoxLayout, hp_data: Dict) -> None:
        """Add action buttons (Sell, Cancel) to the row."""
        action_layout = BoxLayout(orientation="horizontal", size_hint_x=0.18, spacing=2)
        action_buttons = hp_data.get("action_buttons", [])
        button_states = hp_data.get("button_states", {})

        # Add Sell button if needed
        if "SELL" in action_buttons:
            self._add_sell_button(action_layout, hp_data, button_states)

        # Add Cancel button if needed
        if "CANCEL" in action_buttons:
            self._add_cancel_button(action_layout, hp_data, button_states)

        # Fill remaining space if no buttons
        if not action_buttons:
            action_layout.add_widget(Label(text=""))

        row.add_widget(action_layout)

    def _add_sell_button(
        self, action_layout: BoxLayout, hp_data: Dict, button_states: Dict
    ) -> None:
        """Add sell button to action layout."""
        sell_btn = Button(text="Sell", size_hint_x=0.5)

        # Apply button state
        sell_state = button_states.get("SELL", {"enabled": True, "text": "Sell"})
        sell_btn.text = sell_state["text"]
        sell_btn.disabled = not sell_state["enabled"]

        if sell_state["enabled"]:
            hp_id = hp_data.get("hp_id", "")
            coin = hp_data.get("coin", "")
            quantity = hp_data.get("quantity", "0.0")
            buy_price = hp_data.get("buy_price", "0.0")
            sell_btn.bind(
                on_release=lambda x: self.sell_callback(
                    hp_id, coin, quantity, buy_price
                )
            )

        action_layout.add_widget(sell_btn)

    def _add_cancel_button(
        self, action_layout: BoxLayout, hp_data: Dict, button_states: Dict
    ) -> None:
        """Add cancel button to action layout."""
        cancel_btn = Button(text="Cancel", size_hint_x=0.5)

        # Apply button state
        cancel_state = button_states.get("CANCEL", {"enabled": True, "text": "Cancel"})
        cancel_btn.text = cancel_state["text"]
        cancel_btn.disabled = not cancel_state["enabled"]

        if cancel_state["enabled"]:
            hp_id = hp_data.get("hp_id", "")
            symbol = hp_data.get("coin", "")
            # Map side correctly to PositionSide enum values
            if hp_data.get("side") == "BUY":
                side_value = "LONG"
            else:
                side_value = "LONG"  # Default to LONG for buy positions

            cancel_btn.bind(
                on_release=lambda x: self.cancel_callback(hp_id, symbol, side_value)
            )

        action_layout.add_widget(cancel_btn)

    def create_column_label(self, text: str, width_hint: float) -> Label:
        """
        Create a standardized column label.

        Args:
            text: Label text content
            width_hint: Relative width (0.0-1.0)

        Returns:
            Configured Label widget
        """
        label = Label(
            text=str(text), size_hint_x=width_hint, halign="center", valign="middle"
        )
        label.bind(size=label.setter("text_size"))
        return label
