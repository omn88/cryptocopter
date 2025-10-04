"""HP Position Updater Module.

This module handles all HP list position updates and orchestrates the creation
and modification of parent and child positions based on HPUpdate events.

Extracted from HpFront to improve separation of concerns and testability.
"""

import logging
from typing import Dict

from src.gui.identifiers import HPUpdate


logger = logging.getLogger("HPPositionUpdater")


class HPPositionUpdater:
    """Handles updates to HP position data structures.

    This class manages the complex logic of updating HP positions including:
    - Parent container creation and management
    - Position type detection (parent, multihop, regular, convert)
    - Routing updates to appropriate handlers
    - Quantity and price updates for buy/sell operations
    """

    def __init__(self):
        """Initialize the position updater."""
        # No instance state needed currently

    def update_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Main entry point for updating a position.

        Args:
            hp_map: Dictionary mapping HP IDs to position data
            update: HPUpdate event with new position data
            hp_id: The HP ID being updated
            operation_side: Operation side (LONG/SHORT/BUY/SELL)
            quantity_usd: Formatted quantity in USD
        """
        # Determine position type
        position_type = self._detect_position_type(hp_id, update)

        logger.debug("Processing position %s as type: %s", hp_id, position_type)

        # Route to appropriate handler based on position type
        if position_type == "parent":
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "regular_parent":
            # For regular operations: create parent + child (handled by HpFront)
            # This signals that child creation is needed
            pass
        elif position_type == "multihop":
            # Multihop handling (will be integrated with child creator)
            pass
        elif position_type == "regular":
            # Regular position handling (will be integrated with child creator)
            pass
        elif position_type == "convert":
            # Convert position handling (will be integrated with child creator)
            pass
        else:
            logger.warning("Unknown position type for %s, treating as parent", hp_id)
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )

    def _detect_position_type(self, hp_id: str, update: HPUpdate) -> str:
        """Detect the type of position based on HP ID pattern and operation context.

        Returns:
            One of: 'parent', 'regular_parent', 'multihop', 'regular', 'convert'
        """
        # Convert position: numeric + "_CONVERT" (e.g., "1000_CONVERT")
        if "_CONVERT" in hp_id:
            parts = hp_id.split("_CONVERT")
            if len(parts) == 2 and parts[0].isdigit() and parts[1] == "":
                return "convert"

        # Regular position: numeric + "_" + operation (e.g., "1000_BUY", "1000_SELL")
        if "_" in hp_id:
            parts = hp_id.split("_")
            if len(parts) == 2 and parts[0].isdigit() and parts[1] in ["BUY", "SELL"]:
                return "regular"

        # Multihop position: numeric + single letter (e.g., "1000a", "1000b")
        if len(hp_id) >= 2 and hp_id[-1].isalpha() and hp_id[:-1].isdigit():
            return "multihop"

        # Pure numeric (e.g., "1000"): needs context to determine if parent-only or parent+child
        if hp_id.isdigit():
            # For regular BUY/SELL operations, we need to create parent + child
            # For true parent positions (like in multihop), we create parent only
            if update.side in ["BUY", "SELL"] and not getattr(
                update, "is_child", False
            ):
                return "regular_parent"  # Create parent + child
            else:
                return "parent"  # Create parent only

        return "parent"

    def _handle_parent_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle parent position updates."""
        # Ensure parent container exists
        self.ensure_parent_container(hp_map, update, hp_id)

        # Update parent data based on operation
        parent = hp_map[hp_id]
        parent["state"] = update.state.value

        # Update core price data from the update
        if update.buy_price is not None:
            parent["buy_price"] = (
                str(update.symbol.format_price(update.buy_price))
                if update.symbol
                else str(update.buy_price)
            )
        if update.sell_price is not None:
            parent["sell_price"] = (
                str(update.symbol.format_price(update.sell_price))
                if update.symbol
                else str(update.sell_price)
            )
        if update.expected_return is not None:
            parent["expected_return"] = (
                str(update.symbol.format_price(update.expected_return))
                if update.symbol
                else str(update.expected_return)
            )

        # Update quantity from update data
        if update.quantity is not None:
            # For parent positions, use total_quantity if available, otherwise use quantity
            quantity_to_use = (
                update.total_quantity
                if update.total_quantity is not None
                else update.quantity
            )
            formatted_quantity = (
                str(update.symbol.format_quantity(float(quantity_to_use)))
                if update.symbol
                else str(quantity_to_use)
            )
            parent["quantity"] = formatted_quantity
            parent["realized_quantity"] = (
                formatted_quantity  # For parent, both are the same initially
            )

        # Update quantity_usd if provided (but not for NEW buy operations where nothing has been bought yet)
        is_sell_operation = self.is_sell_operation(update, operation_side)

        # Only set quantity_usd if it's a sell operation or if we have actual bought quantity
        if quantity_usd and quantity_usd != "0.0":
            if is_sell_operation:
                # For sell operations, always set quantity_usd
                parent["quantity_usd"] = quantity_usd
            else:
                # For buy operations, only set quantity_usd if we have non-zero quantity
                total_bought = (
                    float(update.total_quantity)
                    if update.total_quantity is not None
                    else float(update.quantity) if update.quantity is not None else 0.0
                )
                if total_bought > 0:
                    parent["quantity_usd"] = quantity_usd

        # Determine operation type

        if is_sell_operation:
            # Update parent quantities for sell operations
            self.update_parent_sell_quantities(parent, update)
        else:
            # Update parent quantities for buy operations
            self.update_parent_buy_quantities(parent, update)

    def ensure_parent_container(
        self, hp_map: Dict[str, Dict], update: HPUpdate, parent_hp_id: str
    ) -> None:
        """Ensure parent container exists with proper initialization."""
        if parent_hp_id not in hp_map or hp_map[parent_hp_id].get("is_child", True):
            # Check if we already have quantity_usd from the original HPUpdate
            original_quantity_usd = "0.0"
            if hasattr(update, "quantity_usd") and update.quantity_usd is not None:
                # Only use update.quantity_usd if this is being called for the actual parent
                if parent_hp_id == update.hp_id:
                    original_quantity_usd = str(update.quantity_usd)

            # For sell-only positions (like inventory sells), initialize with the sell quantity
            initial_quantity = "0.0"
            if hasattr(update, "quantity") and update.quantity is not None:
                initial_quantity = (
                    str(update.symbol.format_quantity(float(update.quantity)))
                    if update.symbol
                    else str(update.quantity)
                )

            hp_map[parent_hp_id] = {
                "hp_id": parent_hp_id,
                "coin": f"{update.coin}USD",
                "state": update.state.value,
                "buy_price": "0.0",
                "quantity": initial_quantity,
                "realized_quantity": "0.0",
                "quantity_usd": original_quantity_usd,
                "sell_price": "0.0",
                "expected_return": "0.0",
                "current_price": "0.0",
                "net": "0.0",
                "net_percent": "0.0",
                "is_child": False,
                "side": "PARENT",
                "children": [],
                "is_expanded": True,  # Start expanded so children are visible
                "action_buttons": ["SELL", "CANCEL"],
            }

        # Ensure children list exists
        hp_map[parent_hp_id].setdefault("children", [])

    def update_parent_buy_quantities(self, parent: Dict, update: HPUpdate) -> None:
        """Update parent quantities for buy operations."""
        # Parent should show realized quantity (what has actually been filled/bought)
        if update.total_quantity is not None:
            total_bought = float(update.total_quantity)
        else:
            total_bought = (
                float(update.quantity) if update.quantity is not None else 0.0
            )

        parent["quantity"] = str(update.symbol.format_quantity(total_bought))

        # Ensure realized_quantity exists
        if "realized_quantity" not in parent:
            parent["realized_quantity"] = "0.0"

    def update_parent_sell_quantities(self, parent: Dict, update: HPUpdate) -> None:
        """Update parent quantities for sell operations."""
        # For convert-only positions, use the quantity from the update since there's no actual buying
        if (
            update.symbol
            and hasattr(update.symbol, "is_convert_only")
            and update.symbol.is_convert_only
        ):
            total_bought_qty = float(update.quantity) if update.quantity else 0.0
        else:
            # Use total_quantity from update if available, otherwise fall back to existing parent data
            total_bought_qty = (
                float(update.total_quantity)
                if hasattr(update, "total_quantity")
                and update.total_quantity is not None
                else float(parent.get("quantity", "0.0"))
            )

        # Update parent quantities
        parent["quantity"] = str(update.symbol.format_quantity(total_bought_qty))

        # Parent realized_quantity should use the update's realized_quantity when available
        if update.realized_quantity is not None:
            # Use the realized_quantity from the update (this is what was actually sold)
            parent["realized_quantity"] = str(
                update.symbol.format_quantity(float(update.realized_quantity))
            )
        else:
            # Fallback: use 0.0 or existing value
            parent.setdefault("realized_quantity", "0.0")

    def is_sell_operation(self, update: HPUpdate, operation_side: str) -> bool:
        """Determine if this is a sell operation."""
        return (
            operation_side in ["SHORT", "SELL"]
            or update.state.value in ["SELLING", "SOLD", "SOLD_PART_BOUGHT"]
            or "SELL" in update.state.value
        )
