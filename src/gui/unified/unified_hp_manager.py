"""Unified HP Manager widget.

This widget replaces the tabbed Buy/Sell interface with a hierarchical view
of all HP positions and modal configurators for creating new ones.
"""

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.gridlayout import GridLayout
from kivy.properties import StringProperty, ObjectProperty
from kivy.clock import Clock
from typing import Dict, List, Optional, Callable, Any
import logging

from .models import UnifiedPosition, UnifiedHPData, PositionType, PositionState
from .modal_configurators import BuyHPModal, SellHPModal
from .models import HPConfiguration

logger = logging.getLogger(__name__)


class HPRowWidget(BoxLayout):  # type: ignore[misc]
    """Widget representing a single HP position row."""

    def __init__(
        self,
        position: UnifiedPosition,
        on_expand_callback: Optional[Callable[[str], None]] = None,
        on_action_callback: Optional[Callable[[UnifiedPosition, str], None]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.position = position
        self.on_expand_callback = on_expand_callback
        self.on_action_callback = on_action_callback

        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = 40
        self.spacing = 5

        # Determine colors based on position type and state
        self.setup_styling()
        self.build_row()

    def setup_styling(self) -> None:
        """Setup row styling based on position type and state."""
        if self.position.position_type == PositionType.HP:
            self.bg_color = [0.2, 0.3, 0.4, 1.0]  # Dark blue for parent
        elif self.position.is_dummy:
            self.bg_color = [0.3, 0.3, 0.2, 1.0]  # Dark yellow for dummy
        elif self.position.position_type == PositionType.BUY:
            self.bg_color = [0.2, 0.4, 0.2, 1.0]  # Dark green for buy
        else:  # SELL
            self.bg_color = [0.4, 0.2, 0.2, 1.0]  # Dark red for sell

        # Add indentation for child positions
        self.padding_left = 20 if self.position.is_child else 0

    def build_row(self) -> None:
        """Build the row layout with all columns."""
        # Add left padding for child positions
        if self.position.is_child:
            self.add_widget(Label(text="", size_hint_x=None, width=20))

        # Expand/Collapse button (only for parent positions with children)
        if (
            self.position.position_type == PositionType.HP
            and self.position.has_children
        ):
            expand_btn = Button(
                text="▼" if self.position.is_expanded else "▶",
                size_hint_x=None,
                width=30,
                height=30,
            )
            expand_btn.bind(on_release=self.on_expand_clicked)
            self.add_widget(expand_btn)
        else:
            self.add_widget(Label(text="", size_hint_x=None, width=30))

        # Essential columns
        self.add_column("Type", self.position.get_type_display(), 0.08)
        self.add_column("ID", self.position.hp_id, 0.1)
        self.add_column("Coin", self.position.coin, 0.08)
        self.add_column("Qty", self.position.get_quantity_display(), 0.12)
        self.add_column("Price", self.position.get_price_display(), 0.12)
        self.add_column("Progress", self.position.get_progress_display(), 0.1)
        self.add_column("Net", self.position.get_net_display(), 0.12)
        self.add_column("State", self.position.get_state_display(), 0.1)

        # Action buttons
        self.add_action_buttons()

    def add_column(self, header: str, value: str, width_hint: float) -> None:
        """Add a column to the row."""
        label = Label(
            text=value, size_hint_x=width_hint, halign="center", valign="middle"
        )
        label.bind(size=label.setter("text_size"))
        self.add_widget(label)

    def add_action_buttons(self) -> None:
        """Add action buttons based on position type and state."""
        action_layout = BoxLayout(orientation="horizontal", size_hint_x=0.18, spacing=2)

        # Get action buttons from position data (if available)
        available_actions = getattr(self.position, "action_buttons", None)
        if available_actions is None:
            # Fallback to determine actions based on position properties
            available_actions = self._determine_available_actions()

        # Add buttons based on available actions
        if "SELL" in available_actions:
            sell_btn = Button(text="Sell", size_hint_x=0.5)
            sell_btn.bind(on_release=lambda x: self.on_action("sell"))
            action_layout.add_widget(sell_btn)

        if "CANCEL" in available_actions:
            cancel_btn = Button(text="Cancel", size_hint_x=0.5)
            cancel_btn.bind(on_release=lambda x: self.on_action("cancel"))
            action_layout.add_widget(cancel_btn)

        if "REMOVE" in available_actions:
            remove_btn = Button(text="Remove", size_hint_x=0.5)
            remove_btn.bind(on_release=lambda x: self.on_action("remove"))
            action_layout.add_widget(remove_btn)

        # If no actions available, add empty space
        if not available_actions:
            action_layout.add_widget(Label(text=""))

        self.add_widget(action_layout)

    def _determine_available_actions(self) -> List[str]:
        """Determine available actions based on position properties."""
        actions = []

        if self.position.position_type == PositionType.HP:
            # Parent position: Sell action if it has children
            if self.position.has_children:
                actions.append("SELL")
                actions.append("CANCEL")
        elif self.position.is_child:
            # Child position actions based on side
            side = getattr(self.position, "side", "")
            if side == "BUY":
                # Buy child can sell
                actions.append("SELL")
                actions.append("CANCEL")
            elif side == "SELL":
                # Sell child can typically only cancel
                if self.position.state in ["ACTIVE", "SELLING", "NEW"]:
                    actions.append("CANCEL")
            elif side == "DUMMY_BUY":
                # Dummy buy has no actions
                pass
            else:
                # Generic child actions
                if self.position.state in ["ACTIVE", "BUYING", "SELLING", "NEW"]:
                    actions.append("CANCEL")
                elif self.position.state in ["COMPLETED", "SOLD", "CLOSED"]:
                    actions.append("REMOVE")
        else:
            # Fallback for other position types
            if self.position.state in ["ACTIVE", "BUYING", "SELLING", "NEW"]:
                actions.append("CANCEL")
            elif self.position.state in ["COMPLETED", "SOLD", "CLOSED"]:
                actions.append("REMOVE")

        return actions

    def on_expand_clicked(self, instance: Any) -> None:
        """Handle expand/collapse button click."""
        logger.info(f"Expand button clicked for position: {self.position.hp_id}")
        if self.on_expand_callback:
            self.on_expand_callback(self.position.hp_id)
        else:
            logger.warning(
                f"No expand callback set for position: {self.position.hp_id}"
            )

    def on_action(self, action: str) -> None:
        """Handle action button click."""
        if self.on_action_callback is not None:
            self.on_action_callback(self.position, action)


class HeaderWidget(BoxLayout):  # type: ignore[misc]
    """Header widget with column titles."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = 35
        self.spacing = 5

        # Build header
        self.build_header()

    def build_header(self) -> None:
        """Build header with column titles."""
        # Expand button space
        self.add_widget(Label(text="", size_hint_x=None, width=30))

        # Column headers
        headers = [
            ("Type", 0.08),
            ("ID", 0.1),
            ("Coin", 0.08),
            ("Quantity", 0.12),
            ("Price", 0.12),
            ("Progress", 0.1),
            ("Net", 0.12),
            ("State", 0.1),
            ("Actions", 0.18),
        ]

        for title, width_hint in headers:
            label = Label(
                text=title,
                size_hint_x=width_hint,
                bold=True,
                halign="center",
                valign="middle",
            )
            label.bind(size=label.setter("text_size"))
            self.add_widget(label)


class UnifiedHPManager(BoxLayout):  # type: ignore[misc]
    """Main unified HP manager widget."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.spacing = 10
        self.padding = 10

        # Data management
        self.hp_data = UnifiedHPData()

        # Callbacks (set by parent)
        self.create_hp_callback: Optional[Callable[[str, HPConfiguration], None]] = None
        self.cancel_hp_callback: Optional[Callable[[str, str], None]] = None
        self.remove_hp_callback: Optional[Callable[[str, str], None]] = None

        # Available data for modals
        self.available_symbols: List[str] = []
        self.inventory_coins: Dict[str, List[Any]] = {}
        self.symbols_info: Dict[str, Any] = {}
        self.client: Optional[Any] = None

        self.build_ui()

    def build_ui(self) -> None:
        """Build the main UI."""
        # Title and control buttons
        header_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=50, spacing=10
        )

        title_label = Label(
            text="HP Manager",
            size_hint_x=0.6,
            font_size="20sp",
            bold=True,
            halign="left",
        )
        title_label.bind(size=title_label.setter("text_size"))
        header_layout.add_widget(title_label)

        # Control buttons
        btn_layout = BoxLayout(orientation="horizontal", size_hint_x=0.4, spacing=5)

        buy_hp_btn = Button(text="New Buy HP", size_hint_x=0.5)
        buy_hp_btn.bind(on_release=self.show_buy_modal)

        sell_hp_btn = Button(text="New Sell HP", size_hint_x=0.5)
        sell_hp_btn.bind(on_release=self.show_sell_modal)

        btn_layout.add_widget(buy_hp_btn)
        btn_layout.add_widget(sell_hp_btn)
        header_layout.add_widget(btn_layout)

        self.add_widget(header_layout)

        # HP list
        self.build_hp_list()

    def build_hp_list(self) -> None:
        """Build the scrollable HP list."""
        # Header
        header = HeaderWidget()
        self.add_widget(header)

        # Scrollable content
        scroll = ScrollView()
        self.hp_list_layout = BoxLayout(
            orientation="vertical", size_hint_y=None, spacing=2
        )
        self.hp_list_layout.bind(minimum_height=self.hp_list_layout.setter("height"))

        scroll.add_widget(self.hp_list_layout)
        self.add_widget(scroll)

        # Initial refresh
        self.refresh_hp_list()

    def refresh_hp_list(self) -> None:
        """Refresh the HP list display."""
        self.hp_list_layout.clear_widgets()

        # Get all positions to display (respecting expand/collapse state)
        positions_to_show = self.hp_data.get_visible_positions()

        for position in positions_to_show:
            row = HPRowWidget(
                position=position,
                on_expand_callback=self.on_position_expand,
                on_action_callback=self.on_position_action,
            )
            self.hp_list_layout.add_widget(row)

        # Add empty state message if no positions
        if not positions_to_show:
            empty_label = Label(
                text='No HP positions yet. Click "New Buy HP" or "New Sell HP" to get started.',
                size_hint_y=None,
                height=100,
                halign="center",
                valign="middle",
            )
            empty_label.bind(size=empty_label.setter("text_size"))
            self.hp_list_layout.add_widget(empty_label)

    def on_position_expand(self, hp_id: str) -> None:
        """Handle position expand/collapse."""
        logger.info(f"Position expand requested for HP ID: {hp_id}")
        self.hp_data.toggle_expansion(hp_id)
        logger.info(f"Position {hp_id} expansion state toggled")
        self.refresh_hp_list()

    def on_position_action(self, position: UnifiedPosition, action: str) -> None:
        """Handle position action."""
        if action == "sell":
            # Show sell modal for this position
            # Extract coin from position symbol data
            coin = position.coin
            if hasattr(self, "show_sell_modal"):
                self.show_sell_modal(default_coin=coin)
            else:
                logger.warning(
                    f"Sell action requested for {position.hp_id} but no sell modal available"
                )
        elif action == "cancel":
            if self.cancel_hp_callback:
                self.cancel_hp_callback(position.hp_id, position.position_type.value)
        elif action == "remove":
            if self.remove_hp_callback:
                self.remove_hp_callback(position.hp_id, position.position_type.value)

    def show_buy_modal(
        self, instance: Any = None, default_coin: Optional[str] = None
    ) -> None:
        """Show Buy HP configuration modal."""
        if not self.available_symbols:
            logger.warning("No symbols available for Buy HP")
            return

        modal = BuyHPModal(
            symbols=self.available_symbols,
            symbols_info=self.symbols_info,
            client=self.client,
            callback=self.on_buy_hp_configured,
        )

        # Set default coin if provided
        if default_coin and f"{default_coin}USDT" in self.available_symbols:
            modal.symbol_spinner.text = f"{default_coin}USDT"
        elif default_coin and f"{default_coin}USDC" in self.available_symbols:
            modal.symbol_spinner.text = f"{default_coin}USDC"

        modal.open()

    def show_sell_modal(
        self, instance: Any = None, default_coin: Optional[str] = None
    ) -> None:
        """Show Sell HP configuration modal."""
        if not self.inventory_coins:
            logger.warning("No inventory available for Sell HP")
            return

        modal = SellHPModal(
            inventory_coins=self.inventory_coins, callback=self.on_sell_hp_configured
        )

        # Set default coin if provided and available
        if default_coin and default_coin in self.inventory_coins:
            modal.coin_spinner.text = default_coin
            modal.on_coin_selected(modal.coin_spinner, default_coin)

        modal.open()

    def on_buy_hp_configured(self, config: HPConfiguration) -> None:
        """Handle Buy HP configuration completion."""
        if self.create_hp_callback:
            self.create_hp_callback("BUY", config)

    def on_sell_hp_configured(self, config: HPConfiguration) -> None:
        """Handle Sell HP configuration completion."""
        if self.create_hp_callback:
            self.create_hp_callback("SELL", config)

    def update_symbols(self, symbols: List[str]) -> None:
        """Update available symbols for Buy HP."""
        self.available_symbols = symbols

    def update_inventory(self, inventory: Dict[str, List[Any]]) -> None:
        """Update available inventory for Sell HP."""
        self.inventory_coins = inventory

    def add_hp_position(self, hp_type: str, hp_id: str, data: Dict[str, Any]) -> None:
        """Add a new HP position to the display."""
        # Convert data to UnifiedPosition
        position = self._convert_data_to_position(hp_type, hp_id, data)
        if position:
            self.hp_data.add_position(position)
            Clock.schedule_once(lambda dt: self.refresh_hp_list(), 0)

    def update_hp_position(
        self, hp_type: str, hp_id: str, data: Dict[str, Any]
    ) -> None:
        """Update an existing HP position."""
        # For now, remove and re-add (could be optimized)
        self.remove_hp_position(hp_type, hp_id)
        self.add_hp_position(hp_type, hp_id, data)

    def remove_hp_position(self, hp_type: str, hp_id: str) -> None:
        """Remove an HP position from the display."""
        self.hp_data.remove_position(hp_id)
        Clock.schedule_once(lambda dt: self.refresh_hp_list(), 0)

    def clear_all_positions(self) -> None:
        """Clear all positions."""
        self.hp_data.clear_all()
        Clock.schedule_once(lambda dt: self.refresh_hp_list(), 0)

    def _convert_data_to_position(
        self, hp_type: str, hp_id: str, data: Dict[str, Any]
    ) -> Optional[UnifiedPosition]:
        """Convert HP data to UnifiedPosition."""
        try:
            from .models import format_currency, format_percentage, format_quantity

            # Add debugging for parent positions
            children_data = data.get("children", [])
            action_buttons = data.get("action_buttons", [])
            side = data.get("side", "UNKNOWN")
            logger.debug(
                f"Converting position {hp_id} type={hp_type}, side={side}, children={children_data}, actions={action_buttons}"
            )

            # Extract common fields
            coin = (
                data.get("coin", data.get("pair", "Unknown"))
                .replace("USDT", "")
                .replace("USDC", "")
                .replace("USD", "")
            )
            state = data.get("state", "UNKNOWN")
            is_child = data.get("is_child", False)
            parent_hp_id = data.get("parent_hp_id")

            # Determine position type based on hp_type and hierarchy
            if hp_type.upper() == "HP":
                # This is a parent HP position
                position_type = PositionType.HP
            elif hp_type.upper() == "BUY":
                position_type = PositionType.BUY
            elif hp_type.upper() == "SELL":
                position_type = PositionType.SELL
            else:
                # Default fallback
                position_type = PositionType.HP

            # Format display fields - always show exact quantities
            quantity = format_quantity(float(data.get("quantity", 0)))
            price = format_currency(
                float(data.get("buy_price", data.get("sell_price", 0)))
            )
            net = format_currency(float(data.get("net", 0)))
            progress = format_percentage(float(data.get("net_percent", 0)))

            position = UnifiedPosition(
                position_type=position_type,
                hp_id=hp_id,
                coin=coin,
                quantity=quantity,
                price=price,
                progress=progress,
                net=net,
                state=state,
                is_child=is_child,
                parent_hp_id=parent_hp_id,
                is_expanded=data.get("is_expanded", False),
                raw_quantity=float(data.get("quantity", 0)),
                raw_price=float(data.get("buy_price", data.get("sell_price", 0))),
                raw_net=float(data.get("net", 0)),
                progress_percent=float(data.get("net_percent", 0)),
                can_cancel=state not in ["COMPLETED", "SOLD", "CLOSED"],
                children=children_data.copy() if children_data else [],
                has_children=len(children_data) > 0 if children_data else False,
            )

            # Add action buttons and side information to position for use in UI
            position.action_buttons = action_buttons
            position.side = side

            logger.debug(
                f"Created position {hp_id}: has_children={position.has_children}, children={position.children}, side={side}"
            )
            return position
        except Exception as e:
            logger.error(f"Error converting data to position: {e}")
            return None
