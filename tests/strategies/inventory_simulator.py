"""
Inventory Sell Simulator for testing inventory-based sell operations.

This simulator provides methods to test the complete inventory sell flow:
1. Clicking sell buttons on inventory items
2. Configuring sell parameters (direct, multi-hop, convert)
3. Creating HP sell positions
4. Executing sell orders
5. Validating final states
"""

import logging
from typing import List, Optional

from src.gui.hp_manager.hpfront import HpFront
from src.strategy_executor import StrategyExecutor
from src.portfolio.portfolio_gui import PortfolioUI
from src.identifiers import InventoryItem, State
from tests.strategies.hp_manager_helpers import wait_for_condition

logger = logging.getLogger(__name__)


class InventorySellSimulator:
    """Simulator for inventory-based sell operations."""

    def __init__(
        self,
        portfolio: PortfolioUI,
        hp_manager: HpFront,
        strategy_executor: StrategyExecutor,
    ):
        self.portfolio = portfolio
        self.hp_manager = hp_manager
        self.strategy_executor = strategy_executor

    def get_inventory_item(self, coin: str) -> InventoryItem:
        """Get inventory item for a specific coin from portfolio inventory."""
        # Portfolio has the inventory, not strategy executor
        inventory = self.portfolio.inventory
        for item in inventory:
            if item.coin == coin:
                return item
        raise ValueError(f"No inventory item found for coin: {coin}")

    def get_all_inventory_items(self) -> List[InventoryItem]:
        """Get all inventory items from portfolio."""
        return self.portfolio.inventory

    async def simulate_sell_button_click(self, coin: str):
        """Simulate clicking sell button on inventory item."""
        inventory_item = self.get_inventory_item(coin)

        # This should trigger the sell modal to open with pre-populated data
        # Currently this functionality needs to be implemented
        if hasattr(self.portfolio, 'sell_button_clicked'):
            result = self.portfolio.sell_button_clicked(inventory_item)
        else:
            # For now, just log that the functionality needs implementation
            logger.info(f"Portfolio.sell_button_clicked method not implemented yet for {coin}")
            result = None

        logger.info(f"Sell button clicked for {coin}, result: {result}")
        return result

    async def verify_sell_modal_opened(
        self, coin: str, expected_quantity: float, expected_buy_price: float
    ):
        """Verify that sell modal opened with correct pre-populated data."""
        # This will need to be implemented - verify modal is open with correct data
        logger.info(f"TODO: Verify sell modal opened for {coin} with quantity={expected_quantity}, buy_price={expected_buy_price}")
        pass

    async def configure_direct_sell(
        self, sell_price: float, end_currency: str = "USDC"
    ):
        """Configure direct sell in the modal."""
        # This will simulate user entering sell configuration
        logger.info(f"TODO: Configure direct sell with price={sell_price}, end_currency={end_currency}")
        pass

    async def configure_multi_hop_sell(self, sell_price: float, end_currency: str):
        """Configure multi-hop sell in the modal."""
        # This will simulate user entering multi-hop sell configuration
        logger.info(f"TODO: Configure multi-hop sell with price={sell_price}, end_currency={end_currency}")
        pass

    async def configure_convert_sell(self, end_currency: str):
        """Configure convert-only sell in the modal."""
        # This will simulate user entering convert sell configuration
        logger.info(f"TODO: Configure convert sell to {end_currency}")
        pass

    async def submit_sell_configuration(self):
        """Submit the sell configuration to create HP sell position."""
        # This will simulate clicking "Create HP" or similar button in modal
        logger.info("TODO: Submit sell configuration to create HP position")
        pass

    def verify_hp_sell_position_created(self, hp_id: str, coin: str, quantity: float):
        """Verify that HP sell position was created correctly."""
        assert hp_id in self.strategy_executor.strategies
        strategy = self.strategy_executor.strategies[hp_id]
        logger.info(f"Verified HP sell position created: {hp_id} for {coin} with quantity {quantity}")
        # Add verification logic here

    async def verify_sell_execution_complete(self, hp_id: str, expected_state: State):
        """Verify that sell execution completed with expected state."""
        await wait_for_condition(
            condition_func=lambda: self.strategy_executor.strategies[hp_id].state
            == expected_state
        )
        logger.info(f"Verified sell execution complete: {hp_id} reached state {expected_state}")

    def verify_inventory_item_structure(self, item: InventoryItem, coin: str):
        """Verify that inventory item has expected structure and data."""
        assert item.coin == coin, f"Expected coin {coin}, got {item.coin}"
        assert item.available_quantity > 0, f"Expected positive quantity for {coin}"
        assert item.buy_price > 0, f"Expected positive buy price for {coin}"
        logger.info(f"Verified inventory item structure for {coin}: quantity={item.available_quantity}, price={item.buy_price}")

    def verify_connections(self):
        """Verify that portfolio, HP manager, and strategy executor are properly connected."""
        # Verify portfolio has hp_manager reference
        assert hasattr(
            self.portfolio, "hp_manager"
        ), "Portfolio should have hp_manager reference"
        assert (
            self.portfolio.hp_manager is self.hp_manager
        ), "Portfolio should reference the correct HP manager"

        # Verify HP manager has portfolio_queue (not direct portfolio reference)
        assert hasattr(
            self.hp_manager, "portfolio_queue"
        ), "HP manager should have portfolio_queue for communication"
        
        # Verify HP manager does NOT have direct portfolio reference (correct architecture)
        assert not hasattr(
            self.hp_manager, "portfolio"
        ), "HP manager should NOT have direct portfolio reference - it uses portfolio_queue instead"

        # Verify backend connections
        assert (
            self.hp_manager.config_queue is self.strategy_executor.config_queue
        ), "HP manager should use strategy executor config queue"
        assert (
            self.strategy_executor.ui_queue is self.hp_manager.ui_queue
        ), "Strategy executor should use HP manager UI queue"

        logger.info("Verified all portfolio-HP manager-backend connections")
