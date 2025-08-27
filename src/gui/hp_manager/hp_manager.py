"""Unified HP Manager widget.

This widget replaces the tabbed Buy/Sell interface with a hierarchical view
of all HP positions and modal configurators for creating new ones.
"""

from kivy.uix.boxlayout import BoxLayout
from kivy.properties import StringProperty, ObjectProperty
from kivy.clock import Clock
from typing import Dict, List, Optional, Callable, Any
import logging

from .models import UnifiedPosition, UnifiedHPData, PositionType, PositionState
from .modal_configurators import BuyHPModal
from .models import HPConfiguration

logger = logging.getLogger(__name__)


class HPManager(BoxLayout):  # type: ignore[misc]
    """HP manager controller - handles modals and data management only.

    UI layout is handled by KV file. This class only manages:
    - Modal dialogs for creating HP positions
    - Data management and callbacks
    - Integration with HpFront
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

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

        # Modal instances
        self.buy_modal: Optional[BuyHPModal] = None

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

    def on_buy_hp_configured(self, config: HPConfiguration) -> None:
        """Handle Buy HP configuration completion."""
        if self.create_hp_callback:
            self.create_hp_callback("BUY", config)

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
            # Note: UI refresh is now handled by HpFront through binding

    def remove_hp_position(self, hp_type: str, hp_id: str) -> None:
        """Remove an HP position from the display."""
        self.hp_data.remove_position(hp_id)
        # Note: UI refresh is now handled by HpFront through binding

    def clear_all_positions(self) -> None:
        """Clear all positions."""
        self.hp_data.clear_all()
        # Note: UI refresh is now handled by HpFront through binding

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
                is_expanded=hp_id
                in self.hp_data.expanded_hp_ids,  # Check actual expansion state
                raw_quantity=float(data.get("quantity", 0)),
                raw_price=float(data.get("buy_price", data.get("sell_price", 0))),
                raw_net=float(data.get("net", 0)),
                progress_percent=float(data.get("net_percent", 0)),
                can_cancel=state not in ["COMPLETED", "SOLD", "CLOSED"],
                children=children_data.copy() if children_data else [],
                has_children=len(children_data) > 0 if children_data else False,
                action_buttons=action_buttons,
                side=side,
            )

            logger.debug(
                f"Created position {hp_id}: has_children={position.has_children}, children={position.children}, side={side}"
            )
            return position
        except Exception as e:
            logger.error(f"Error converting data to position: {e}")
            return None
