"""
HP Data Manager - Main coordinator for all HP position data operations.

This class serves as the central coordinator that manages all HP position data operations,
encapsulating the specialized helper classes and providing a clean API for the GUI layer.
"""

import logging
from typing import Dict, List, Optional, Callable
from src.gui.identifiers import HPUpdate
from src.gui.hp_manager.hp_position_updater import HPPositionUpdater
from src.gui.hp_manager.hp_child_creator import HPChildCreator
from src.gui.hp_manager.hp_state_calculator import HPStateCalculator

logger = logging.getLogger("HPDataManager")


class HPDataManager:
    """
    Main coordinator for HP position data operations.

    This class encapsulates all the specialized helper classes and provides
    a unified interface for position routing, child creation, state calculation,
    and parent updates.

    Architecture:
    - HPPositionUpdater: Handles parent container creation and quantity updates
    - HPChildCreator: Creates child positions (buy/sell/convert/multihop)
    - HPStateCalculator: Calculates states for child positions

    The hpfront class only needs to interact with this manager, not individual helpers.
    """

    def __init__(self, hp_list_data_getter: Callable[[], List[Dict]]):
        """
        Initialize the HP data manager with all helper components.

        Args:
            hp_list_data_getter: Callback to get current hp_list_data (needed for state calculations)
        """
        # Initialize specialized helper components
        self.position_updater = HPPositionUpdater()
        self.state_calculator = HPStateCalculator(
            hp_list_data_getter=hp_list_data_getter
        )
        self.child_creator = HPChildCreator(
            buy_state_getter_callback=self.state_calculator.get_buy_child_state,
            sell_state_getter_callback=self.state_calculator.get_sell_child_state_from_update,
            position_updater=self.position_updater,
        )

    def handle_position_update(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """
        Main entry point for handling position updates.

        Routes the update to the appropriate handler based on position type detection.
        This is the only method hpfront needs to call for position processing.

        Args:
            hp_map: Dictionary mapping HP IDs to position data
            update: The HPUpdate containing new position data
            hp_id: The HP identifier (e.g., "1000", "1000_BUY", "1000a", "1000_CONVERT")
            operation_side: The operation side (LONG/SHORT)
            quantity_usd: The USD quantity as formatted string
        """
        # Detect position type
        position_type = self._detect_position_type(hp_id, update)

        logger.debug(f"Routing position {hp_id} as type: {position_type}")

        # Route to appropriate handler
        if position_type == "parent":
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "regular_parent":
            self._handle_regular_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "multihop":
            self._handle_multihop_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "regular":
            self._handle_regular_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "convert":
            self._handle_convert_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        else:
            logger.warning(f"Unknown position type for {hp_id}, treating as parent")
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )

    def _detect_position_type(self, hp_id: str, update: HPUpdate) -> str:
        """Detect the type of position based on HP ID pattern."""
        return self.position_updater._detect_position_type(hp_id, update)

    def _handle_parent_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle parent-only position updates (updates to existing parent container)."""
        # Ensure parent container exists
        self.position_updater.ensure_parent_container(hp_map, update, hp_id)

        # Update parent data
        parent = hp_map[hp_id]
        parent["state"] = update.state.value

        # Update core price data
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

        # Update quantity_usd if provided
        if quantity_usd and quantity_usd != "0.0":
            parent["quantity_usd"] = quantity_usd

        # Determine operation type and update parent quantities
        is_sell = self.position_updater.is_sell_operation(update, operation_side)
        if is_sell:
            self.position_updater.update_parent_sell_quantities(parent, update)
        else:
            self.position_updater.update_parent_buy_quantities(parent, update)

    def _handle_multihop_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle multihop position updates (e.g., '1000a', '1000b')."""
        parent_hp_id = hp_id[:-1]  # Remove letter suffix

        # Ensure parent exists
        self.position_updater.ensure_parent_container(hp_map, update, parent_hp_id)

        # Create multihop child with parent update
        self.child_creator.create_multihop_child_with_parent_update(
            hp_map, update, hp_id, parent_hp_id
        )

    def _handle_regular_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle regular position updates (e.g., '1000_BUY', '1000_SELL')."""
        parent_hp_id, child_operation = hp_id.split("_")

        # Ensure parent exists
        self.position_updater.ensure_parent_container(hp_map, update, parent_hp_id)

        # Update parent state for sell operations
        if child_operation == "SELL":
            hp_map[parent_hp_id]["state"] = update.state.value

        # Create appropriate child with parent update
        if child_operation == "BUY":
            self.child_creator.create_buy_child_with_parent_update(
                hp_map, update, hp_id, parent_hp_id, operation_side, quantity_usd
            )
        elif child_operation == "SELL":
            self.child_creator.create_sell_child_with_parent_update(
                hp_map, update, hp_id, parent_hp_id, operation_side, quantity_usd
            )

    def _handle_convert_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle convert position updates (e.g., '1000_CONVERT')."""
        parent_hp_id = hp_id.split("_CONVERT")[0]

        logger.info(f"Handling convert position for HP ID: {hp_id}")

        # Ensure parent exists
        self.position_updater.ensure_parent_container(hp_map, update, parent_hp_id)

        # Create convert child with parent update
        self.child_creator.create_convert_child_with_parent_update(
            hp_map, update, hp_id, parent_hp_id, None, quantity_usd
        )

        logger.info(f"Convert sell child created for HP ID: {hp_id}")

    def _handle_regular_parent_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle regular parent position that needs both parent container and child position."""
        # Create parent container
        self.position_updater.ensure_parent_container(hp_map, update, hp_id)

        # Update parent data
        parent = hp_map[hp_id]
        parent["state"] = update.state.value

        # Update core price data
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

        # Update quantity_usd if provided
        if quantity_usd and quantity_usd != "0.0":
            parent["quantity_usd"] = quantity_usd

        # Determine operation type and update parent quantities
        is_sell = self.position_updater.is_sell_operation(update, operation_side)

        if is_sell:
            self.position_updater.update_parent_sell_quantities(parent, update)
            if hasattr(update, "quantity_usd") and update.quantity_usd:
                parent["quantity_usd"] = str(update.quantity_usd)
        else:
            self.position_updater.update_parent_buy_quantities(parent, update)

        # Create child position (non-updating version since parent is already updated)
        if is_sell:
            child_hp_id = f"{hp_id}_SELL"
            self.child_creator.create_sell_child(
                hp_map, update, child_hp_id, hp_id, operation_side, quantity_usd
            )
        else:
            child_hp_id = f"{hp_id}_BUY"
            self.child_creator.create_buy_child(
                hp_map, update, child_hp_id, hp_id, operation_side, quantity_usd
            )
