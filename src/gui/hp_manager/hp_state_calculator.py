"""HP State Calculator Module.

This module handles state determination and action button logic for the HP Manager interface.
It provides focused methods for calculating the appropriate state for buy/sell children,
determining which action buttons should be displayed, and checking position status.

Key Responsibilities:
- Calculate buy child states based on operation state and quantities
- Calculate sell child states based on operation state and parent state
- Determine action buttons and their enabled/disabled states
- Check for active sell children and realized quantities

Author: Refactored from HpFront monolithic class
"""

import logging
from typing import Any, Dict

from src.gui.identifiers import HPUpdate

logger = logging.getLogger(__name__)


class HPStateCalculator:
    """Handles state calculation and action button logic for HP manager.

    This class extracts state determination logic from the HpFront UI class,
    providing focused methods for calculating child states, determining action buttons,
    and checking position status. This improves testability and separation of concerns.
    """

    def __init__(self, hp_list_data_getter=None):
        """Initialize the state calculator.

        Args:
            hp_list_data_getter: Optional callback to get the current hp_list_data.
                Should return a list of HP data dictionaries.
                Used for checking sell child status and realized quantities.
        """
        self.hp_list_data_getter = hp_list_data_getter

    def get_buy_child_state(self, update: HPUpdate) -> str:
        """Get appropriate state for buy child based on actual buy operation state.

        Architecture: Children should primarily show the actual operation state (from buy_operation_state)
        when available, falling back to parent-derived states.

        Args:
            update: The HPUpdate containing buy operation data

        Returns:
            State string for the buy child position
        """
        # First priority: Use actual buy operation state if available
        # This comes from the HPGuiDataBuy.data.state_info.state and represents the actual buy operation state
        if hasattr(update, "buy_operation_state") and update.buy_operation_state:
            actual_state = update.buy_operation_state
            return actual_state

        # Fallback: Use parent state to determine child state
        parent_state = update.state.value

        # When parent is actively operating (BUYING/SELLING), child shows operational state
        if parent_state in ["BUYING", "SELLING"]:
            return "BUYING"  # Buy child shows BUYING when parent is actively operating

        # When parent is stable/idle, child shows completion state based on quantities
        total_qty = getattr(update, "total_quantity", 0) or 0
        realized_qty = getattr(update, "realized_quantity", 0) or 0
        current_qty = getattr(update, "quantity", 0) or 0

        # Use the maximum quantity to determine if we have any bought quantity
        bought_qty = max(total_qty, realized_qty, current_qty)

        if parent_state == "NEW":
            return "NEW"
        elif bought_qty > 0:
            # Check if fully bought
            if current_qty >= bought_qty or abs(current_qty - bought_qty) < 0.00001:
                return "BOUGHT"  # Fully bought
            else:
                return "PARTIALLY_BOUGHT"  # Partially bought
        else:
            return "NEW"  # No quantities, still new

    def get_sell_child_state_from_update(self, update: HPUpdate) -> str:
        """Get sell child state, prioritizing sell operation state from update.

        Args:
            update: The HPUpdate containing sell operation data

        Returns:
            State string for the sell child position
        """
        # Check if this is a convert-only position
        is_convert_only = update.hp_id.endswith("_CONVERT")

        # Check if we have specific sell state information in the update
        if hasattr(update, "sell_state") and update.sell_state:
            sell_state = update.sell_state
            if sell_state in ["NEW"]:
                # For NEW state, check the overall strategy state to determine if this is
                # initial setup (idle) or active selling
                if update.state.value == "SELLING":
                    # Strategy is actively selling - show as SELLING
                    return "SELLING"
                elif update.state.value == "BOUGHT" and is_convert_only:
                    # For BOUGHT state on convert-only positions ready to convert, show as BOUGHT
                    return "BOUGHT"
                else:
                    # Initial setup or other states - show as idle
                    return "NEW"
            elif sell_state in ["PARTIALLY_SOLD"]:
                return "PARTIALLY_SOLD"
            elif sell_state in ["SOLD", "FILLED"]:
                return "SOLD"

        # Fall back to parent state logic
        return self.get_sell_child_state(update)

    def get_sell_child_state(self, update: HPUpdate, sell_data=None) -> str:
        """Get appropriate state for sell child based on parent state and sell operation status.

        Args:
            update: The HPUpdate containing position data
            sell_data: Optional sell data with state information

        Returns:
            State string for the sell child position
        """
        parent_state = update.state.value

        # If we have sell data with state info, prioritize that for sell child state
        if (
            sell_data
            and hasattr(sell_data, "data")
            and hasattr(sell_data.data, "state_info")
        ):
            sell_state = sell_data.data.state_info.state.value
            if sell_state in ["NEW"]:
                return "SELLING"  # Active sell order
            elif sell_state in ["PARTIALLY_SOLD"]:
                return "PARTIALLY_SOLD"
            elif sell_state in ["SOLD", "FILLED"]:
                return "SOLD"
            # If no specific sell state, fall back to parent state logic

        # Map parent states to appropriate sell child states
        if parent_state in ["SELLING"]:
            return "SELLING"
        elif parent_state in ["PARTIALLY_SOLD"]:
            return "PARTIALLY_SOLD"
        elif parent_state in ["SOLD"]:
            return "SOLD"
        elif parent_state in ["PART_SOLD_PART_BOUGHT"]:
            # Complex parent state: sell child should show its sell operation status
            # Since we're in this state, some selling happened, so likely PARTIALLY_SOLD
            return "PARTIALLY_SOLD"
        elif parent_state in ["SOLD_PART_BOUGHT"]:
            # Position was sold partially, but the sell operation is complete
            return "SOLD"
        else:
            # For other states where selling is active, default to SELLING
            if any(
                sell_indicator in parent_state for sell_indicator in ["SELL", "SOLD"]
            ):
                return "SELLING"
            else:
                return "NEW"

    def has_sell_child(self, hp_id: str) -> bool:
        """Check if HP has an active sell child (excludes cancelled/closed positions).

        Args:
            hp_id: The HP ID to check for sell children

        Returns:
            True if the HP has an active sell child, False otherwise
        """
        if not self.hp_list_data_getter:
            logger.warning(
                "hp_list_data_getter not set, cannot check for sell children"
            )
            return False

        hp_list_data = self.hp_list_data_getter()

        for item in hp_list_data:
            if item.get("hp_id") == f"{hp_id}_SELL":
                # Check if the sell child is in an active state
                state = item.get("state", "")
                # Count as "has sell child" for clearly active states
                if state in ["SELLING", "PARTIALLY_SOLD"]:
                    return True
                # For NEW state, assume it's active (legitimate new sell position)
                # The main issue was with the list filtering, not this check
                elif state == "NEW":
                    return True
                # Only exclude clearly inactive states
                elif state in ["CLOSED", "CANCELLED", "SOLD"]:
                    return False
        return False

    def get_parent_realized_quantity(self, hp_id: str) -> float:
        """Get the realized buy quantity from parent HP.

        Args:
            hp_id: The parent HP ID

        Returns:
            The realized quantity for the parent HP
        """
        if not self.hp_list_data_getter:
            logger.warning(
                "hp_list_data_getter not set, cannot get parent realized quantity"
            )
            return 0.0

        hp_list_data = self.hp_list_data_getter()

        for item in hp_list_data:
            if item.get("hp_id") == hp_id and item.get("side") == "PARENT":
                return float(item.get("quantity", "0.0"))
        return 0.0

    def get_sell_child_realized_quantity(self, hp_id: str) -> float:
        """Get the realized sell quantity from sell child.

        Args:
            hp_id: The parent HP ID (will look for {hp_id}_SELL)

        Returns:
            The realized sell quantity for the sell child
        """
        if not self.hp_list_data_getter:
            logger.warning(
                "hp_list_data_getter not set, cannot get sell child realized quantity"
            )
            return 0.0

        hp_list_data = self.hp_list_data_getter()

        for item in hp_list_data:
            if item.get("hp_id") == f"{hp_id}_SELL":
                return float(item.get("realized_quantity", "0.0"))
        return 0.0

    def determine_action_buttons(self, hp_data: dict) -> dict:
        """Determine which action buttons to show and their states.

        Args:
            hp_data: Dictionary containing HP data (hp_id, side, is_child, etc.)

        Returns:
            Dictionary with "buttons" list and "states" dict containing button configurations
        """
        hp_id = hp_data.get("hp_id", "")
        side = hp_data.get("side", "")
        is_child = hp_data.get("is_child", False)

        # Extract base HP ID for children
        base_hp_id = hp_id.split("_")[0] if is_child else hp_id

        buttons: Dict[str, Any] = {"buttons": [], "states": {}}

        if side == "PARENT":
            # Parent HP logic
            has_sell_child = self.has_sell_child(base_hp_id)
            realized_quantity = float(hp_data.get("quantity", "0.0"))

            # SELL button: Always show, but enabled only if no sell child and realized_quantity > 0
            buttons["buttons"].append("SELL")
            buttons["states"]["SELL"] = {
                "enabled": not has_sell_child and realized_quantity > 0,
                "text": "Sell",
            }

            # CANCEL button: Always show and enabled
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {"enabled": True, "text": "Cancel"}

        elif side == "BUY":
            # Buy child logic
            has_sell_child = self.has_sell_child(base_hp_id)

            # CANCEL button: Always show, but enabled only if no sell child
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {
                "enabled": not has_sell_child,
                "text": "Cancel",
            }

        elif side == "SELL":
            # Sell child logic
            realized_sell_quantity = float(hp_data.get("realized_quantity", "0.0"))

            # CANCEL button: Always show, but enabled only if realized_quantity == 0
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {
                "enabled": realized_sell_quantity == 0,
                "text": "Cancel",
            }

        return buttons
