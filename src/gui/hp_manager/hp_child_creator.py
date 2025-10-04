"""HP Child Position Creator Module.

This module handles the creation and management of child positions (buy, sell, convert, multihop)
for the HP Manager interface. Child positions are derivative positions that track specific
sell orders, conversions, or multihop trades linked to parent buy positions.

Key Responsibilities:
- Create buy child positions with quantity tracking
- Create sell child positions (regular and multihop)
- Create convert-only child positions for non-trading conversions
- Manage parent-child relationships and quantity calculations
- Handle state determination for child positions

Author: Refactored from HpFront monolithic class
"""

import logging
from typing import Dict, Optional

from src.gui.identifiers import HPUpdate

logger = logging.getLogger(__name__)


class HPChildCreator:
    """Handles creation of child positions for HP manager.

    This class extracts child position creation logic from the HpFront UI class,
    providing focused methods for creating buy, sell, convert, and multihop child positions.
    Each type of child has specific quantity calculations, state management, and
    parent-child relationship handling.
    """

    def __init__(self, buy_state_getter_callback=None, sell_state_getter_callback=None):
        """Initialize the child creator.

        Args:
            buy_state_getter_callback: Optional callback to get state for buy child positions.
                Should accept an HPUpdate and return a state string.
                If None, will use a default state determination.
            sell_state_getter_callback: Optional callback to get state for sell child positions.
                Should accept an HPUpdate and return a state string.
                If None, will use a default state determination.
        """
        self.buy_state_getter_callback = buy_state_getter_callback
        self.sell_state_getter_callback = sell_state_getter_callback

    def create_buy_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        _operation_side: Optional[str] = None,
        _quantity_usd: Optional[str] = None,
    ) -> None:
        """Create a buy child position.

        Buy children are created when a parent position has partial buys tracked separately.
        This typically happens when multiple buy orders are executed for the same position.

        Args:
            hp_map: The HP map to update
            update: The HPUpdate with child data
            hp_id: The child HP ID
            parent_hp_id: The parent HP ID
        """
        parent = hp_map[parent_hp_id]

        # Calculate expected quantity (what we're trying to buy)
        if hasattr(update, "expected_quantity") and update.expected_quantity:
            expected_quantity = update.expected_quantity
        else:
            expected_quantity = float(update.quantity or 0.0)

        # Calculate orders total (what's currently in orders)
        if hasattr(update, "orders_total_quantity") and update.orders_total_quantity:
            orders_total_quantity = update.orders_total_quantity
        else:
            orders_total_quantity = 0.0

        # Calculate realized quantity (what we've actually bought)
        # For buy children, realized_quantity should represent total bought amount, not remaining amount
        # Use total_quantity if available AND non-zero, otherwise fall back to realized_quantity or quantity
        if (
            hasattr(update, "total_quantity")
            and update.total_quantity is not None
            and update.total_quantity > 0
        ):
            realized_quantity = float(update.total_quantity)
            qty_for_usd_calc = realized_quantity
        elif hasattr(update, "realized_quantity") and update.realized_quantity:
            realized_quantity = update.realized_quantity
            qty_for_usd_calc = realized_quantity
        else:
            realized_quantity = float(update.quantity or 0.0)
            qty_for_usd_calc = realized_quantity

        # For buy children, quantity should show orders_total_quantity (what's in orders),
        # or expected_quantity if no orders exist yet
        child_qty = (
            orders_total_quantity if orders_total_quantity > 0 else expected_quantity
        )

        # Calculate quantity_usd using total_quantity (cumulative invested amount) * weighted average buy_price
        buy_child_quantity_usd = qty_for_usd_calc * (
            update.buy_price if update.buy_price else 0.0
        )

        buy_child_quantity_usd_str = (
            str(update.symbol.format_price(buy_child_quantity_usd))
            if update.symbol
            else f"{buy_child_quantity_usd:.2f}"
        )

        buy_child = {
            "hp_id": hp_id,
            "coin": update.symbol.name,
            "buy_price": (
                str(update.symbol.format_price(update.buy_price))
                if update.buy_price
                else "0.0"
            ),
            "quantity": str(update.symbol.format_quantity(child_qty)),
            "expected_quantity": str(update.symbol.format_quantity(expected_quantity)),
            "orders_total_quantity": str(
                update.symbol.format_quantity(orders_total_quantity)
            ),
            "realized_quantity": str(update.symbol.format_quantity(realized_quantity)),
            "quantity_usd": buy_child_quantity_usd_str,
            # Note: Buy children don't have sell-related fields (sell_price, expected_return)
            # but they do have net/net_percent for current profit/loss calculation
            "current_price": (
                str(update.symbol.format_price(update.current_price))
                if update.current_price
                else "0.0"
            ),
            "net": str(update.symbol.format_price(update.net)) if update.net else "0.0",
            "net_percent": str(update.net_percent) if update.net_percent else "0.0",
            "state": self._get_buy_child_state(update),
            "is_child": True,
            "side": "BUY",
            "parent_hp_id": parent_hp_id,
            "action_buttons": ["CANCEL"],
        }

        hp_map[hp_id] = buy_child
        if hp_id not in parent["children"]:
            parent["children"].append(hp_id)

        logger.debug("Created buy child %s for parent %s", hp_id, parent_hp_id)

    def create_sell_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        _operation_side: Optional[str] = None,
        _quantity_usd: Optional[str] = None,
    ) -> None:
        """Create a regular sell child position.

        Regular sell children represent simple sell orders for a parent buy position.
        This delegates to create_multihop_child as both share similar logic.

        Args:
            hp_map: The HP map to update
            update: The HPUpdate with child data
            hp_id: The child HP ID
            parent_hp_id: The parent HP ID
        """
        # Regular sell children use the same logic as multihop
        self.create_multihop_child(hp_map, update, hp_id, parent_hp_id)

    def create_convert_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        _operation_side: Optional[str] = None,
        _quantity_usd: Optional[str] = None,
    ) -> None:
        """Create a convert-only sell child position.

        Convert children are for positions that involve currency conversion only,
        without actual trading. This typically happens when converting crypto to fiat
        or between stablecoins.

        Args:
            hp_map: The HP map to update
            update: The HPUpdate with child data
            hp_id: The child HP ID
            parent_hp_id: The parent HP ID
        """
        parent = hp_map[parent_hp_id]

        # Get quantities from parent
        parent_qty = float(parent.get("quantity", "0.0"))

        # For convert-only positions, we're converting all of the parent quantity
        # Use quantity from update if available, otherwise use parent quantity
        if update.quantity is not None:
            child_qty = float(update.quantity)
        else:
            child_qty = parent_qty

        # Calculate actually sold/converted quantity
        # For convert-only positions, realized_quantity should equal the quantity to be converted
        if (
            hasattr(update, "realized_quantity")
            and update.realized_quantity is not None
            and update.realized_quantity > 0
        ):
            actually_sold_qty = update.realized_quantity
        elif (
            hasattr(update, "sell_completeness")
            and update.sell_completeness is not None
            and update.sell_completeness > 0
        ):
            actually_sold_qty = child_qty * update.sell_completeness
        else:
            # For NEW convert positions, realized_quantity should be the full quantity
            actually_sold_qty = child_qty

        # For convert-only, quantity_usd should be the USD value at buy price
        # (how much USD the crypto was worth when we bought it)
        sell_child_quantity_usd = child_qty * (
            update.buy_price if update.buy_price else 0.0
        )
        sell_child_quantity_usd_str = (
            str(update.symbol.format_price(sell_child_quantity_usd))
            if update.symbol
            else f"{sell_child_quantity_usd:.2f}"
        )

        # For convert positions, expected_return is based on the conversion
        # which might be to USD (sell_price would be 1.0 for USD)
        if update.expected_return:
            expected_return = update.expected_return
        else:
            # Calculate expected return: quantity * sell_price
            expected_return = child_qty * (
                update.sell_price if update.sell_price else 0.0
            )

        sell_child = {
            "hp_id": hp_id,
            "coin": update.symbol.name,
            "buy_price": (
                str(update.symbol.format_price(update.buy_price))
                if update.buy_price
                else "0.0"
            ),
            "quantity": str(update.symbol.format_quantity(child_qty)),
            "realized_quantity": str(update.symbol.format_quantity(actually_sold_qty)),
            "quantity_usd": sell_child_quantity_usd_str,
            "sell_price": (
                str(update.symbol.format_price(update.sell_price))
                if update.sell_price
                else "0.0"
            ),
            "expected_return": (
                str(update.symbol.format_price(expected_return))
                if update.symbol
                else f"{expected_return:.2f}"
            ),
            "current_price": (
                str(update.symbol.format_price(update.current_price))
                if update.current_price
                else "0.0"
            ),
            "net": str(update.symbol.format_price(update.net)) if update.net else "0.0",
            "net_percent": str(update.net_percent) if update.net_percent else "0.0",
            "state": self._get_sell_child_state(update),
            "sell_completeness": str(getattr(update, "sell_completeness", 0.0)),
            "is_child": True,
            "side": "SELL",
            "parent_hp_id": parent_hp_id,
            "action_buttons": ["CANCEL"],
        }

        hp_map[hp_id] = sell_child
        if hp_id not in parent["children"]:
            parent["children"].append(hp_id)

        logger.debug("Created convert-only child %s for parent %s", hp_id, parent_hp_id)

    def create_multihop_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
    ) -> None:
        """Create a multihop sell child position.

        Multihop children are created when a sell position involves multiple hops
        (e.g., selling crypto to BTC then to USD). Each hop is tracked as a separate child.

        Args:
            hp_map: The HP map to update
            update: The HPUpdate with child data
            hp_id: The child HP ID
            parent_hp_id: The parent HP ID
        """
        parent = hp_map[parent_hp_id]

        # When adding the first multihop child, remove any regular sell child (_SELL)
        # that may have been created when the parent was initially processed
        regular_sell_child_id = f"{parent_hp_id}_SELL"
        if regular_sell_child_id in parent.get("children", []):
            parent["children"].remove(regular_sell_child_id)
            if regular_sell_child_id in hp_map:
                del hp_map[regular_sell_child_id]

        # Get quantities from parent, but for multihop, use update quantity if parent is still 0
        parent_qty = float(parent.get("quantity", "0.0"))

        # Check if this is a regular sell child (e.g., "1000_SELL") vs actual multihop child (e.g., "1000a")
        is_regular_sell_child = hp_id.endswith("_SELL")

        if parent_qty == 0.0 and update.quantity and not is_regular_sell_child:
            # This is likely the first multihop child, use the original quantity
            total_bought_qty = float(update.quantity)
            # Update parent with the correct quantity and quantity_usd
            parent["quantity"] = str(update.symbol.format_quantity(total_bought_qty))
            # Calculate quantity_usd for parent using parent's buy price (not multihop child's)
            parent_buy_price = float(parent.get("buy_price", "0.0"))
            parent_quantity_usd = total_bought_qty * parent_buy_price
            parent["quantity_usd"] = (
                str(update.symbol.format_price(parent_quantity_usd))
                if update.symbol
                else f"{parent_quantity_usd:.2f}"
            )
        else:
            total_bought_qty = parent_qty

        # For multihop children, determine the correct quantity to display
        if not is_regular_sell_child:
            # For multihop children, use current remaining quantity (update.quantity)
            # for ongoing positions, and total_quantity only for initial setup
            if update.quantity is not None:
                child_qty = float(update.quantity)
            elif hasattr(update, "total_quantity") and update.total_quantity:
                child_qty = float(update.total_quantity)
            else:
                child_qty = total_bought_qty
        else:
            child_qty = total_bought_qty

        # Calculate actually sold quantity from sell completion if available
        if (
            hasattr(update, "realized_quantity")
            and update.realized_quantity is not None
        ):
            # Use actual realized quantity from sell order if available
            actually_sold_qty = update.realized_quantity
        elif (
            hasattr(update, "sell_completeness")
            and update.sell_completeness is not None
        ):
            # Fallback: Use sell completeness to calculate realized quantity for sell operations
            actually_sold_qty = child_qty * update.sell_completeness
        else:
            actually_sold_qty = float(parent.get("realized_quantity", "0.0"))

        # Calculate quantity_usd based on remaining quantity for multihop children
        sell_child_quantity_usd = child_qty * (
            update.buy_price if update.buy_price else 0.0
        )
        sell_child_quantity_usd_str = (
            str(update.symbol.format_price(sell_child_quantity_usd))
            if update.symbol
            else f"{sell_child_quantity_usd:.2f}"
        )

        sell_child = {
            "hp_id": hp_id,
            "coin": update.symbol.name,
            "buy_price": (
                str(update.symbol.format_price(update.buy_price))
                if update.buy_price
                else "0.0"
            ),
            "quantity": str(update.symbol.format_quantity(child_qty)),
            "realized_quantity": str(update.symbol.format_quantity(actually_sold_qty)),
            "quantity_usd": sell_child_quantity_usd_str,
            "sell_price": (
                str(update.symbol.format_price(update.sell_price))
                if update.sell_price
                else "0.0"
            ),
            "expected_return": (
                str(update.symbol.format_price(update.expected_return))
                if update.expected_return
                else "0.0"
            ),
            "current_price": (
                str(update.symbol.format_price(update.current_price))
                if update.current_price
                else "0.0"
            ),
            "net": (
                str(update.symbol.format_price(update.net)) if update.net else "0.0"
            ),
            "net_percent": str(update.net_percent) if update.net_percent else "0.0",
            "state": self._get_sell_child_state(update),
            "sell_completeness": str(getattr(update, "sell_completeness", 0.0)),
            "is_child": True,
            "side": "SELL",
            "parent_hp_id": parent_hp_id,
            "action_buttons": ["CANCEL"],
        }

        hp_map[hp_id] = sell_child
        if hp_id not in parent["children"]:
            parent["children"].append(hp_id)

        logger.debug("Created multihop child %s for parent %s", hp_id, parent_hp_id)

    def _get_buy_child_state(self, update: HPUpdate) -> str:
        """Get the state for a buy child position.

        Uses the callback if provided, otherwise returns a default state.

        Args:
            update: The HPUpdate containing state information

        Returns:
            State string for the buy child position
        """
        if self.buy_state_getter_callback:
            return self.buy_state_getter_callback(update)

        # Default state determination
        if hasattr(update, "state") and update.state:
            return (
                update.state.value
                if hasattr(update.state, "value")
                else str(update.state)
            )
        return "UNKNOWN"

    def _get_sell_child_state(self, update: HPUpdate) -> str:
        """Get the state for a sell child position.

        Uses the callback if provided, otherwise returns a default state.

        Args:
            update: The HPUpdate containing state information

        Returns:
            State string for the sell child position
        """
        if self.sell_state_getter_callback:
            return self.sell_state_getter_callback(update)

        # Default state determination
        if hasattr(update, "state") and update.state:
            return (
                update.state.value
                if hasattr(update.state, "value")
                else str(update.state)
            )
        return "UNKNOWN"
