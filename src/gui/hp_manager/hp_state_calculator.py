import logging
from typing import Any, Dict
from src.gui.identifiers import HPUpdate

logger = logging.getLogger(__name__)


class HPStateCalculator:
    def __init__(self, hp_list_data_getter=None):
        self.hp_list_data_getter = hp_list_data_getter

    def get_buy_child_state(self, update: HPUpdate) -> str:
        if hasattr(update, "buy_operation_state") and update.buy_operation_state:
            return update.buy_operation_state

        parent_state = update.state.value
        if parent_state in ["BUYING", "SELLING"]:
            return "BUYING"

        total_qty = getattr(update, "total_quantity", 0) or 0
        realized_qty = getattr(update, "realized_quantity", 0) or 0
        current_qty = getattr(update, "quantity", 0) or 0
        bought_qty = max(total_qty, realized_qty, current_qty)

        if parent_state == "NEW":
            return "NEW"
        elif bought_qty > 0:
            if current_qty >= bought_qty or abs(current_qty - bought_qty) < 0.00001:
                return "BOUGHT"
            else:
                return "PARTIALLY_BOUGHT"
        else:
            return "NEW"

    def get_sell_child_state_from_update(self, update: HPUpdate) -> str:
        is_convert_only = update.hp_id.endswith("_CONVERT")

        if hasattr(update, "sell_state") and update.sell_state:
            sell_state = update.sell_state
            if sell_state in ["NEW"]:
                if update.state.value == "SELLING":
                    return "SELLING"
                elif update.state.value == "BOUGHT" and is_convert_only:
                    return "BOUGHT"
                else:
                    return "NEW"
            elif sell_state in ["PARTIALLY_SOLD"]:
                return "PARTIALLY_SOLD"
            elif sell_state in ["SOLD", "FILLED"]:
                return "SOLD"

        return self.get_sell_child_state(update)

    def get_sell_child_state(self, update: HPUpdate, sell_data=None) -> str:
        parent_state = update.state.value

        if (
            sell_data
            and hasattr(sell_data, "data")
            and hasattr(sell_data.data, "state_info")
        ):
            sell_state = sell_data.data.state_info.state.value
            if sell_state in ["NEW"]:
                return "SELLING"
            elif sell_state in ["PARTIALLY_SOLD"]:
                return "PARTIALLY_SOLD"
            elif sell_state in ["SOLD", "FILLED"]:
                return "SOLD"

        if parent_state in ["SELLING"]:
            return "SELLING"
        elif parent_state in ["PARTIALLY_SOLD"]:
            return "PARTIALLY_SOLD"
        elif parent_state in ["SOLD"]:
            return "SOLD"
        elif parent_state in ["PART_SOLD_PART_BOUGHT"]:
            return "PARTIALLY_SOLD"
        elif parent_state in ["SOLD_PART_BOUGHT"]:
            return "SOLD"
        else:
            if any(
                sell_indicator in parent_state for sell_indicator in ["SELL", "SOLD"]
            ):
                return "SELLING"
            else:
                return "NEW"

    def has_sell_child(self, hp_id: str) -> bool:
        """
        Check if the parent HP has any active sell-type children.
        This includes:
        - Regular sell children (hp_id_SELL)
        - Convert-only children (hp_id_CONVERT)
        - Multihop children (hp_id with letter suffix like 1000a, 1000b)
        """
        if not self.hp_list_data_getter:
            logger.warning(
                "hp_list_data_getter not set, cannot check for sell children"
            )
            return False

        hp_list_data = self.hp_list_data_getter()

        # Check for regular sell child
        for item in hp_list_data:
            child_hp_id = item.get("hp_id", "")

            # Check if this is a sell-type child of the specified parent
            is_regular_sell = child_hp_id == f"{hp_id}_SELL"
            is_convert = child_hp_id == f"{hp_id}_CONVERT"
            is_multihop = (
                child_hp_id.startswith(f"{hp_id}")
                and len(child_hp_id) > len(hp_id)
                and child_hp_id[len(hp_id) : len(hp_id) + 1].isalpha()
                and not child_hp_id.endswith("_BUY")
            )

            if is_regular_sell or is_convert or is_multihop:
                state = item.get("state", "")
                # Consider child as active if not in terminal states
                if state in ["SELLING", "PARTIALLY_SOLD", "NEW", "BOUGHT", "BUYING"]:
                    return True
                elif state in ["CLOSED", "CANCELLED", "SOLD"]:
                    # Continue checking other children
                    continue

        return False

    def get_sell_child_realized_quantity(self, hp_id: str) -> float:
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
        hp_id = hp_data.get("hp_id", "")
        side = hp_data.get("side", "")
        is_child = hp_data.get("is_child", False)
        state = hp_data.get("state", "")
        base_hp_id = hp_id.split("_")[0] if is_child else hp_id

        buttons: Dict[str, Any] = {"buttons": [], "states": {}}

        if side == "PARENT":
            has_sell_child = self.has_sell_child(base_hp_id)
            realized_quantity = float(hp_data.get("quantity", "0.0"))

            # For SOLD state, disable both buttons (position is complete)
            if state == "SOLD":
                buttons["buttons"].append("SELL")
                buttons["states"]["SELL"] = {
                    "enabled": False,
                    "text": "Update Sell" if has_sell_child else "Sell",
                }
                buttons["buttons"].append("CANCEL")
                buttons["states"]["CANCEL"] = {"enabled": False, "text": "Cancel"}
            else:
                # For active positions (BUYING, BOUGHT, SELLING, etc.):
                # - Allow setting sell price even if quantity is 0 (important for BUYING state)
                # - Enable sell button if quantity > 0 OR if state is BUYING/SELLING
                is_active_position = state in [
                    "BUYING",
                    "SELLING",
                    "BOUGHT",
                    "PARTIALLY_BOUGHT",
                    "PARTIALLY_SOLD",
                ]
                sell_enabled = realized_quantity > 0 or is_active_position

                buttons["buttons"].append("SELL")
                buttons["states"]["SELL"] = {
                    "enabled": sell_enabled,
                    "text": "Update Sell" if has_sell_child else "Sell",
                }
                buttons["buttons"].append("CANCEL")
                buttons["states"]["CANCEL"] = {"enabled": True, "text": "Cancel"}

        elif side == "BUY":
            has_sell_child = self.has_sell_child(base_hp_id)
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {
                "enabled": not has_sell_child,
                "text": "Cancel",
            }
        elif side == "SELL":
            realized_sell_quantity = float(hp_data.get("realized_quantity", "0.0"))
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {
                "enabled": realized_sell_quantity == 0,
                "text": "Cancel",
            }

        return buttons
