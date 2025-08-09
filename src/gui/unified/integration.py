"""Integration adapter for the Unified HP Manager.

This module provides the integration layer between the existing HpFront
system and the new unified HP manager, handling callbacks and data
synchronization.
"""

from typing import Dict, List, Any, Callable, Optional
import logging

from .unified_hp_manager import UnifiedHPManager
from .models import HPConfiguration
from src.identifiers import HPBuyConfig, HPSellConfig, Mode

logger = logging.getLogger(__name__)


class UnifiedHPIntegration:
    """Integration adapter for the Unified HP Manager."""

    def __init__(self, hp_front_instance: Any) -> None:
        """Initialize with reference to HpFront instance."""
        self.hp_front = hp_front_instance
        self.unified_manager = UnifiedHPManager()

        # Set up callbacks
        self.unified_manager.create_hp_callback = self.handle_create_hp
        self.unified_manager.cancel_hp_callback = self.handle_cancel_hp
        self.unified_manager.remove_hp_callback = self.handle_remove_hp

    def get_widget(self) -> UnifiedHPManager:
        """Get the unified manager widget."""
        return self.unified_manager

    def handle_create_hp(self, hp_type: str, config: HPConfiguration) -> None:
        """Handle HP creation from the unified manager."""
        try:
            if hp_type == "BUY":
                self._create_buy_hp(config)
            elif hp_type == "SELL":
                self._create_sell_hp(config)
            else:
                logger.error(f"Unknown HP type: {hp_type}")
        except Exception as e:
            logger.error(f"Error creating {hp_type} HP: {e}")

    def _create_buy_hp(self, config: HPConfiguration) -> None:
        """Create a Buy HP from configuration."""
        if not self.hp_front.symbols_info.get(config.symbol):
            logger.error(f"Symbol info not found for {config.symbol}")
            return

        # Convert HPConfiguration to HPBuyConfig
        buy_config = HPBuyConfig(
            hp_id=config.hp_id or "1000",
            symbol_info=self.hp_front.symbols_info[config.symbol],
            coin=config.coin,
            budget=config.budget or 1000.0,
            mode=Mode.DCA if config.mode == "DCA" else Mode.SINGLE,
            order_trigger=(config.order_trigger or 1.0)
            / 100.0,  # Convert percentage to decimal
            price_low=config.price_low or 0.0,
            price_high=config.price_high or 0.0,
        )

        # Use existing HP frontend method
        if hasattr(self.hp_front, "on_create_buy_hp"):
            self.hp_front.on_create_buy_hp(buy_config)
        else:
            logger.error("HpFront doesn't have on_create_buy_hp method")

    def _create_sell_hp(self, config: HPConfiguration) -> None:
        """Create a Sell HP from configuration."""
        if not self.hp_front.symbols_info.get(config.symbol):
            logger.error(f"Symbol info not found for {config.symbol}")
            return

        # Convert HPConfiguration to HPSellConfig
        sell_config = HPSellConfig(
            hp_id=config.hp_id or "1000",
            symbol_info=self.hp_front.symbols_info[config.symbol],
            coin=config.coin,
            quantity=config.quantity or 0.0,
            buy_price=0.0,  # Will be updated from actual data
            sell_price=config.sell_price or 0.0,
            end_currency=config.end_currency or "USDC",
        )

        # Use existing HP frontend method
        if hasattr(self.hp_front, "on_create_sell_hp"):
            self.hp_front.on_create_sell_hp(sell_config)
        else:
            logger.error("HpFront doesn't have on_create_sell_hp method")

    def handle_cancel_hp(self, hp_id: str, hp_type: str) -> None:
        """Handle HP cancellation from the unified manager."""
        try:
            # Use existing HP frontend cancellation method
            if hasattr(self.hp_front, "cancel_hp_position"):
                self.hp_front.cancel_hp_position(hp_id, hp_type)
            else:
                logger.error("HpFront doesn't have cancel_hp_position method")
        except Exception as e:
            logger.error(f"Error cancelling HP {hp_id}: {e}")

    def handle_remove_hp(self, hp_id: str, hp_type: str) -> None:
        """Handle HP removal from the unified manager."""
        try:
            # Use existing HP frontend removal method
            if hasattr(self.hp_front, "remove_hp_position"):
                self.hp_front.remove_hp_position(hp_id, hp_type)
            else:
                logger.error("HpFront doesn't have remove_hp_position method")
        except Exception as e:
            logger.error(f"Error removing HP {hp_id}: {e}")

    def update_symbols(self, symbols: List[str]) -> None:
        """Update available symbols for Buy HP."""
        self.unified_manager.update_symbols(symbols)

    def update_inventory(self, inventory: Dict[str, List[Any]]) -> None:
        """Update available inventory for Sell HP."""
        self.unified_manager.update_inventory(inventory)

    def sync_hp_data(self, hp_list_data: List[Dict[str, Any]]) -> None:
        """Sync HP data from the existing system."""
        # Clear existing positions
        self.unified_manager.clear_all_positions()

        # Add all positions from hp_list_data
        for hp_data in hp_list_data:
            try:
                hp_type = self._determine_hp_type(hp_data)
                hp_id = hp_data.get("id", "")

                if hp_type and hp_id:
                    self.unified_manager.add_hp_position(hp_type, hp_id, hp_data)
            except Exception as e:
                logger.error(f"Error syncing HP data: {e}")

    def _determine_hp_type(self, hp_data: Dict[str, Any]) -> Optional[str]:
        """Determine HP type from existing HP data structure."""
        # This needs to be adapted based on the actual structure
        # of hp_list_data from the existing system

        # Look for indicators of Buy vs Sell HP
        if "buy_price" in hp_data or "budget" in hp_data:
            return "BUY"
        elif "sell_price" in hp_data or "quantity" in hp_data:
            return "SELL"

        # Fallback: try to infer from state or other fields
        state = hp_data.get("state", "").upper()
        if "BUY" in state:
            return "BUY"
        elif "SELL" in state:
            return "SELL"

        logger.warning(f"Could not determine HP type for data: {hp_data}")
        return None
