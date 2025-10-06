import logging
from typing import Any, Dict
from src.gui.identifiers import HPUpdate

logger = logging.getLogger("HPPositionUpdater")


class HPPositionUpdater:
    def __init__(self):
        pass

    def update_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        position_type = self.detect_position_type(hp_id, update)
        logger.debug("Processing position %s as type: %s", hp_id, position_type)

        if position_type == "parent":
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "regular_parent":
            pass  # Create parent + child (handled by HpFront)
        elif position_type in ["multihop", "regular", "convert"]:
            pass  # Handled by child creator
        else:
            logger.warning("Unknown position type for %s, treating as parent", hp_id)
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )

    def detect_position_type(self, hp_id: str, update: HPUpdate) -> str:
        if "_CONVERT" in hp_id:
            parts = hp_id.split("_CONVERT")
            if len(parts) == 2 and parts[0].isdigit() and parts[1] == "":
                return "convert"
        if "_" in hp_id:
            parts = hp_id.split("_")
            if len(parts) == 2 and parts[0].isdigit() and parts[1] in ["BUY", "SELL"]:
                return "regular"
        if len(hp_id) >= 2 and hp_id[-1].isalpha() and hp_id[:-1].isdigit():
            return "multihop"
        if hp_id.isdigit():
            if update.side in ["BUY", "SELL"] and not getattr(
                update, "is_child", False
            ):
                return "regular_parent"
            else:
                return "parent"
        return "parent"

    def _handle_parent_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        self.ensure_parent_container(hp_map, update, hp_id)
        parent = hp_map[hp_id]
        parent["state"] = update.state.value

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

        if update.quantity is not None:
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
            parent["realized_quantity"] = formatted_quantity

        is_sell_operation = self.is_sell_operation(update, operation_side)
        if quantity_usd and quantity_usd != "0.0":
            if is_sell_operation:
                parent["quantity_usd"] = quantity_usd
            else:
                total_bought = (
                    float(update.total_quantity)
                    if update.total_quantity is not None
                    else float(update.quantity) if update.quantity is not None else 0.0
                )
                if total_bought > 0:
                    parent["quantity_usd"] = quantity_usd

        if is_sell_operation:
            self.update_parent_sell_quantities(parent, update)
        else:
            self.update_parent_buy_quantities(parent, update)

    def ensure_parent_container(
        self, hp_map: Dict[str, Dict], update: HPUpdate, parent_hp_id: str
    ) -> None:
        if parent_hp_id not in hp_map or hp_map[parent_hp_id].get("is_child", True):
            original_quantity_usd = "0.0"
            if hasattr(update, "quantity_usd") and update.quantity_usd is not None:
                if parent_hp_id == update.hp_id:
                    original_quantity_usd = str(update.quantity_usd)

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
                "is_expanded": True,
                "action_buttons": ["SELL", "CANCEL"],
            }
        hp_map[parent_hp_id].setdefault("children", [])

    def update_parent_buy_quantities(self, parent: Dict, update: HPUpdate) -> None:
        total_bought = (
            float(update.total_quantity)
            if update.total_quantity is not None
            else float(update.quantity) if update.quantity is not None else 0.0
        )
        parent["quantity"] = str(update.symbol.format_quantity(total_bought))
        if "realized_quantity" not in parent:
            parent["realized_quantity"] = "0.0"

    def update_parent_sell_quantities(self, parent: Dict, update: HPUpdate) -> None:
        if (
            update.symbol
            and hasattr(update.symbol, "is_convert_only")
            and update.symbol.is_convert_only
        ):
            total_bought_qty = float(update.quantity) if update.quantity else 0.0
        else:
            total_bought_qty = (
                float(update.total_quantity)
                if hasattr(update, "total_quantity")
                and update.total_quantity is not None
                else float(parent.get("quantity", "0.0"))
            )

        parent["quantity"] = str(update.symbol.format_quantity(total_bought_qty))

        if update.realized_quantity is not None:
            parent["realized_quantity"] = str(
                update.symbol.format_quantity(float(update.realized_quantity))
            )
        else:
            parent.setdefault("realized_quantity", "0.0")

    def is_sell_operation(self, update: HPUpdate, operation_side: str) -> bool:
        return (
            operation_side in ["SHORT", "SELL"]
            or update.state.value in ["SELLING", "SOLD", "SOLD_PART_BOUGHT"]
            or "SELL" in update.state.value
        )

    # ========== Cancellation Logic ==========

    def determine_cancellation_target(
        self,
        hp_id: str,
        has_sell_child_callback,
        get_realized_quantity_callback,
        get_position_side_callback,
    ) -> Dict[str, Any]:
        """
        Determine what to cancel based on HP structure.

        Returns dict with:
        - target_hp_id: The HP ID to cancel
        - target_side: The side to use for cancellation
        - should_cancel: Whether cancellation is allowed
        """
        # Determine if this is a parent, buy child, or sell child
        if "_" not in hp_id:
            # This is a parent HP
            return self._determine_parent_cancellation(
                hp_id, has_sell_child_callback, get_position_side_callback
            )
        elif hp_id.endswith("_BUY"):
            # This is a buy child
            base_hp_id = hp_id.replace("_BUY", "")
            return self._determine_buy_child_cancellation(
                base_hp_id, has_sell_child_callback
            )
        elif hp_id.endswith("_SELL"):
            # This is a sell child
            base_hp_id = hp_id.replace("_SELL", "")
            return self._determine_sell_child_cancellation(
                hp_id, base_hp_id, get_realized_quantity_callback
            )
        else:
            # Fallback - allow direct cancellation
            return {
                "target_hp_id": hp_id,
                "target_side": None,  # Let caller determine
                "should_cancel": True,
            }

    def _determine_parent_cancellation(
        self, hp_id: str, has_sell_child_callback, get_position_side_callback
    ) -> Dict[str, Any]:
        """Determine cancellation for parent HP"""
        has_sell_child = has_sell_child_callback(hp_id)

        if has_sell_child:
            # Cancel the sell child instead
            return {
                "target_hp_id": f"{hp_id}_SELL",
                "target_side": "SHORT",
                "should_cancel": True,
            }
        else:
            # Cancel parent - determine actual position side
            actual_side = get_position_side_callback(hp_id)
            side_str = (
                "SHORT" if actual_side and actual_side.name == "SHORT" else "LONG"
            )
            return {
                "target_hp_id": hp_id,
                "target_side": side_str,
                "should_cancel": True,
            }

    def _determine_buy_child_cancellation(
        self, base_hp_id: str, has_sell_child_callback
    ) -> Dict[str, Any]:
        """Determine cancellation for buy child"""
        has_sell_child = has_sell_child_callback(base_hp_id)

        if not has_sell_child:
            # Only allow buy cancellation if no sell child exists
            return {
                "target_hp_id": base_hp_id,
                "target_side": "LONG",
                "should_cancel": True,
            }
        else:
            # Don't allow cancellation if sell child exists
            return {
                "target_hp_id": base_hp_id,
                "target_side": "LONG",
                "should_cancel": False,
            }

    def _determine_sell_child_cancellation(
        self, hp_id: str, base_hp_id: str, get_realized_quantity_callback
    ) -> Dict[str, Any]:
        """Determine cancellation for sell child"""
        sell_realized_qty = get_realized_quantity_callback(base_hp_id)

        if sell_realized_qty == 0:
            # Only allow sell cancellation if no realized quantity
            return {
                "target_hp_id": hp_id,
                "target_side": "SHORT",
                "should_cancel": True,
            }
        else:
            # Don't allow cancellation if there's realized quantity
            return {
                "target_hp_id": hp_id,
                "target_side": "SHORT",
                "should_cancel": False,
            }
