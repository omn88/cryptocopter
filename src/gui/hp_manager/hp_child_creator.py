import logging
from typing import Dict, Optional
from src.gui.identifiers import HPUpdate
from src.identifiers import State

logger = logging.getLogger(__name__)


class HPChildCreator:
    def __init__(
        self,
        buy_state_getter_callback=None,
        sell_state_getter_callback=None,
        position_updater=None,
    ):
        self.buy_state_getter_callback = buy_state_getter_callback
        self.sell_state_getter_callback = sell_state_getter_callback
        self.position_updater = position_updater

    def create_buy_child_with_parent_update(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        _operation_side: Optional[str] = None,
        _quantity_usd: Optional[str] = None,
    ) -> None:
        """Create buy child and update parent with buy data."""
        # Create the child
        self.create_buy_child(
            hp_map, update, hp_id, parent_hp_id, _operation_side, _quantity_usd
        )

        # Update parent with buy data
        parent = hp_map[parent_hp_id]
        buy_child = hp_map[hp_id]
        parent["buy_price"] = buy_child["buy_price"]
        parent["quantity_usd"] = buy_child["quantity_usd"]
        parent["net"] = buy_child["net"]
        parent["net_percent"] = buy_child["net_percent"]
        parent["state"] = update.state.value

        # Update parent expected_return if available in the update
        if update.expected_return is not None:
            parent["expected_return"] = (
                str(update.symbol.format_price(update.expected_return))
                if update.symbol
                else str(update.expected_return)
            )

        # Update parent quantities
        if self.position_updater:
            self.position_updater.update_parent_buy_quantities(parent, update)

    def create_sell_child_with_parent_update(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        _operation_side: Optional[str] = None,
        _quantity_usd: Optional[str] = None,
    ) -> None:
        """Create sell child and update parent with sell data."""
        # Create the child
        self.create_sell_child(
            hp_map, update, hp_id, parent_hp_id, _operation_side, _quantity_usd
        )

        # Update parent with sell data
        parent = hp_map[parent_hp_id]
        sell_child = hp_map[hp_id]
        parent["buy_price"] = sell_child["buy_price"]
        parent["sell_price"] = sell_child["sell_price"]
        parent["expected_return"] = sell_child["expected_return"]

        # Update parent quantities for sell operations
        if self.position_updater:
            self.position_updater.update_parent_sell_quantities(parent, update)

    def create_multihop_child_with_parent_update(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
    ) -> None:
        """Create multihop sell child and update parent."""
        # Store the parent's quantity_usd before child creation
        parent = hp_map[parent_hp_id]
        parent_quantity_usd_saved = parent.get("quantity_usd", "0.0")

        # Create the child
        self.create_multihop_child(hp_map, update, hp_id, parent_hp_id)

        # Update parent quantities
        if self.position_updater:
            self.position_updater.update_parent_sell_quantities(parent, update)

        # Restore the parent's quantity_usd after update
        parent["quantity_usd"] = parent_quantity_usd_saved

    def create_convert_child_with_parent_update(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        _operation_side: Optional[str] = None,
        _quantity_usd: Optional[str] = None,
    ) -> None:
        """Create convert sell child and update parent."""
        # Create the child
        self.create_convert_child(
            hp_map, update, hp_id, parent_hp_id, _operation_side, _quantity_usd
        )

        # Update parent with convert sell data
        parent = hp_map[parent_hp_id]
        convert_sell_child = hp_map[hp_id]
        parent["buy_price"] = convert_sell_child["buy_price"]
        parent["quantity_usd"] = convert_sell_child["quantity_usd"]
        parent["sell_price"] = convert_sell_child["sell_price"]
        parent["expected_return"] = convert_sell_child["expected_return"]

        if update.state.value == State.SOLD.value:
            parent["realized_quantity"] = convert_sell_child["realized_quantity"]

        parent["state"] = update.state.value

    def create_buy_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        _operation_side: Optional[str] = None,
        _quantity_usd: Optional[str] = None,
    ) -> None:
        parent = hp_map[parent_hp_id]

        expected_quantity = (
            update.expected_quantity
            if hasattr(update, "expected_quantity") and update.expected_quantity
            else float(update.quantity or 0.0)
        )
        orders_total_quantity = (
            update.orders_total_quantity
            if hasattr(update, "orders_total_quantity") and update.orders_total_quantity
            else 0.0
        )

        # Use total_quantity (cumulative) for realized_quantity if available and > 0
        if (
            hasattr(update, "total_quantity")
            and update.total_quantity is not None
            and update.total_quantity > 0
        ):
            realized_quantity = qty_for_usd_calc = float(update.total_quantity)
        elif hasattr(update, "realized_quantity") and update.realized_quantity:
            realized_quantity = qty_for_usd_calc = update.realized_quantity
        else:
            realized_quantity = qty_for_usd_calc = float(update.quantity or 0.0)

        child_qty = (
            orders_total_quantity if orders_total_quantity > 0 else expected_quantity
        )

        # Calculate quantity_usd using total_quantity (cumulative invested amount) * weighted average buy_price
        quantity_usd = qty_for_usd_calc * (
            update.buy_price if update.buy_price else 0.0
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
            "quantity_usd": (
                str(update.symbol.format_price(quantity_usd))
                if update.symbol
                else f"{quantity_usd:.2f}"
            ),
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
        parent = hp_map[parent_hp_id]
        child_qty = (
            float(update.quantity)
            if update.quantity is not None
            else float(parent.get("quantity", "0.0"))
        )

        # Calculate realized quantity for convert positions
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
            actually_sold_qty = child_qty  # For NEW convert positions

        quantity_usd = child_qty * (update.buy_price if update.buy_price else 0.0)
        expected_return = (
            update.expected_return
            if update.expected_return
            else child_qty * (update.sell_price if update.sell_price else 0.0)
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
            "quantity_usd": (
                str(update.symbol.format_price(quantity_usd))
                if update.symbol
                else f"{quantity_usd:.2f}"
            ),
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
        self, hp_map: Dict[str, Dict], update: HPUpdate, hp_id: str, parent_hp_id: str
    ) -> None:
        parent = hp_map[parent_hp_id]

        # Remove regular sell child if adding multihop
        regular_sell_child_id = f"{parent_hp_id}_SELL"
        if regular_sell_child_id in parent.get("children", []):
            parent["children"].remove(regular_sell_child_id)
            if regular_sell_child_id in hp_map:
                del hp_map[regular_sell_child_id]

        parent_qty = float(parent.get("quantity", "0.0"))
        is_regular_sell_child = hp_id.endswith("_SELL")

        # Update parent quantity if needed (first multihop child)
        if parent_qty == 0.0 and update.quantity and not is_regular_sell_child:
            total_bought_qty = float(update.quantity)
            parent["quantity"] = str(update.symbol.format_quantity(total_bought_qty))
            parent_buy_price = float(parent.get("buy_price", "0.0"))
            parent_quantity_usd = total_bought_qty * parent_buy_price
            parent["quantity_usd"] = (
                str(update.symbol.format_price(parent_quantity_usd))
                if update.symbol
                else f"{parent_quantity_usd:.2f}"
            )
        else:
            total_bought_qty = parent_qty

        # Determine child quantity
        if not is_regular_sell_child:
            if update.quantity is not None:
                child_qty = float(update.quantity)
            elif hasattr(update, "total_quantity") and update.total_quantity:
                child_qty = float(update.total_quantity)
            else:
                child_qty = total_bought_qty
        else:
            child_qty = total_bought_qty

        # Calculate realized quantity
        if (
            hasattr(update, "realized_quantity")
            and update.realized_quantity is not None
        ):
            actually_sold_qty = update.realized_quantity
        elif (
            hasattr(update, "sell_completeness")
            and update.sell_completeness is not None
        ):
            actually_sold_qty = child_qty * update.sell_completeness
        else:
            actually_sold_qty = float(parent.get("realized_quantity", "0.0"))

        quantity_usd = child_qty * (update.buy_price if update.buy_price else 0.0)

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
            "quantity_usd": (
                str(update.symbol.format_price(quantity_usd))
                if update.symbol
                else f"{quantity_usd:.2f}"
            ),
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
        logger.debug("Created multihop child %s for parent %s", hp_id, parent_hp_id)

    def _get_buy_child_state(self, update: HPUpdate) -> str:
        if self.buy_state_getter_callback:
            return self.buy_state_getter_callback(update)
        if hasattr(update, "state") and update.state:
            return (
                update.state.value
                if hasattr(update.state, "value")
                else str(update.state)
            )
        return "UNKNOWN"

    def _get_sell_child_state(self, update: HPUpdate) -> str:
        if self.sell_state_getter_callback:
            return self.sell_state_getter_callback(update)
        if hasattr(update, "state") and update.state:
            return (
                update.state.value
                if hasattr(update.state, "value")
                else str(update.state)
            )
        return "UNKNOWN"
