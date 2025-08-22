from typing import Dict, List, Optional
from src.identifiers import InventoryItem


class InventoryManager:
    """Manages inventory items with aggregation and manipulation methods."""

    def __init__(self, inventory: Optional[List[InventoryItem]] = None):
        self.inventory: List[InventoryItem] = inventory or []

    def add_item(self, item: InventoryItem) -> None:
        """Add an inventory item."""
        self.inventory.append(item)

    def remove_item(self, item_id: str) -> bool:
        """Remove an inventory item by id. Returns True if item was found and removed."""
        original_length = len(self.inventory)
        self.inventory = [item for item in self.inventory if item.id != item_id]
        return len(self.inventory) < original_length

    def get_item(self, item_id: str) -> Optional[InventoryItem]:
        """Get an inventory item by id."""
        for item in self.inventory:
            if item.id == item_id:
                return item
        return None

    def get_items_by_coin(self, coin: str) -> List[InventoryItem]:
        """Get all inventory items for a specific coin."""
        return [item for item in self.inventory if item.coin == coin]

    def get_total_quantity_by_coin(self, coin: str) -> float:
        """Get total quantity for a specific coin across all inventory items."""
        return sum(item.quantity for item in self.inventory if item.coin == coin)

    def get_available_quantity_by_coin(self, coin: str) -> float:
        """Get total available quantity for a specific coin across all inventory items."""
        return sum(
            item.available_quantity for item in self.inventory if item.coin == coin
        )

    def get_locked_quantity_by_coin(self, coin: str) -> float:
        """Get total locked quantity for a specific coin across all inventory items."""
        return sum(item.locked_quantity for item in self.inventory if item.coin == coin)

    def get_total_value_by_coin(self, coin: str) -> float:
        """Get total value (quantity * buy_price) for a specific coin."""
        return sum(
            item.quantity * item.buy_price
            for item in self.inventory
            if item.coin == coin
        )

    def get_weighted_average_price(self, coin: str) -> float:
        """Get weighted average buy price for a specific coin."""
        items = self.get_items_by_coin(coin)
        if not items:
            return 0.0

        total_quantity = sum(item.quantity for item in items)
        if total_quantity == 0:
            return 0.0

        total_value = sum(item.quantity * item.buy_price for item in items)
        return total_value / total_quantity

    def get_coin_summary(self) -> Dict[str, Dict[str, float]]:
        """Get summary of all coins with their totals."""
        summary = {}

        # Get unique coins
        coins = set(item.coin for item in self.inventory)

        for coin in coins:
            summary[coin] = {
                "total_quantity": self.get_total_quantity_by_coin(coin),
                "available_quantity": self.get_available_quantity_by_coin(coin),
                "locked_quantity": self.get_locked_quantity_by_coin(coin),
                "total_value": self.get_total_value_by_coin(coin),
                "weighted_avg_price": self.get_weighted_average_price(coin),
            }

        return summary

    def get_total_portfolio_value(self) -> float:
        """Get total portfolio value (sum of all items' quantity * buy_price)."""
        return sum(item.quantity * item.buy_price for item in self.inventory)

    def update_item(self, updated_item: InventoryItem) -> bool:
        """Update an existing inventory item. Returns True if item was found and updated."""
        for i, item in enumerate(self.inventory):
            if item.id == updated_item.id:
                self.inventory[i] = updated_item
                return True
        return False

    def clear(self) -> None:
        """Clear all inventory items."""
        self.inventory.clear()

    def __len__(self) -> int:
        """Return the number of inventory items."""
        return len(self.inventory)

    def __iter__(self):
        """Make InventoryManager iterable."""
        return iter(self.inventory)

    def __getitem__(self, coin: str) -> Dict[str, float]:
        """Get coin summary for a specific coin (for backward compatibility)."""
        if not any(item.coin == coin for item in self.inventory):
            return {
                "total_quantity": 0.0,
                "available_quantity": 0.0,
                "locked_quantity": 0.0,
                "total_value": 0.0,
                "weighted_avg_price": 0.0,
            }

        return {
            "total_quantity": self.get_total_quantity_by_coin(coin),
            "available_quantity": self.get_available_quantity_by_coin(coin),
            "locked_quantity": self.get_locked_quantity_by_coin(coin),
            "total_value": self.get_total_value_by_coin(coin),
            "weighted_avg_price": self.get_weighted_average_price(coin),
        }
