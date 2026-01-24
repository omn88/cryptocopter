"""Unit tests for inventory manager locking semantics and edge cases."""

import pytest
from src.portfolio.inventory_manager import InventoryManager
from src.common.identifiers import InventoryItem


@pytest.fixture
def empty_inventory_manager():
    """Create an empty inventory manager for testing."""
    return InventoryManager()


@pytest.fixture
def sample_inventory_items():
    """Create sample inventory items with different states for testing."""
    return [
        InventoryItem(
            id="btc_lot1",
            coin="BTC",
            buy_price=45000.0,
            quantity=1.0,
            available_quantity=1.0,
            locked_quantity=0.0,
            source="EXCHANGE",
        ),
        InventoryItem(
            id="btc_lot2",
            coin="BTC",
            buy_price=50000.0,
            quantity=0.5,
            available_quantity=0.3,
            locked_quantity=0.2,
            source="EXCHANGE",
        ),
        InventoryItem(
            id="btc_lot3",
            coin="BTC",
            buy_price=55000.0,
            quantity=0.3,
            available_quantity=0.0,
            locked_quantity=0.3,
            source="EXCHANGE",
        ),
        InventoryItem(
            id="eth_lot1",
            coin="ETH",
            buy_price=2800.0,
            quantity=5.0,
            available_quantity=3.0,
            locked_quantity=2.0,
            source="EXCHANGE",
        ),
        InventoryItem(
            id="usdc_lot1",
            coin="USDC",
            buy_price=1.0,
            quantity=10000.0,
            available_quantity=10000.0,
            locked_quantity=0.0,
            source="EXCHANGE",
        ),
    ]


@pytest.fixture
def inventory_manager_with_items(sample_inventory_items):
    """Create inventory manager pre-populated with sample items."""
    return InventoryManager(sample_inventory_items)


class TestBasicInventoryOperations:
    """Test basic inventory operations."""

    def test_init_empty(self, empty_inventory_manager):
        """Test initialization with no items."""
        assert len(empty_inventory_manager) == 0
        assert list(empty_inventory_manager) == []

    def test_init_with_items(self, inventory_manager_with_items):
        """Test initialization with items."""
        assert len(inventory_manager_with_items) == 5

    def test_add_item(self, empty_inventory_manager):
        """Test adding an item to inventory."""
        item = InventoryItem(
            id="test1",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=0.5,
            locked_quantity=0.5,
        )
        empty_inventory_manager.add_item(item)
        assert len(empty_inventory_manager) == 1
        assert empty_inventory_manager.get_item("test1") == item

    def test_remove_item_existing(self, inventory_manager_with_items):
        """Test removing an existing item."""
        result = inventory_manager_with_items.remove_item("btc_lot1")
        assert result is True
        assert len(inventory_manager_with_items) == 4
        assert inventory_manager_with_items.get_item("btc_lot1") is None

    def test_remove_item_nonexistent(self, inventory_manager_with_items):
        """Test removing a non-existent item."""
        result = inventory_manager_with_items.remove_item("nonexistent")
        assert result is False
        assert len(inventory_manager_with_items) == 5

    def test_get_item_existing(self, inventory_manager_with_items):
        """Test getting an existing item."""
        item = inventory_manager_with_items.get_item("btc_lot1")
        assert item is not None
        assert item.id == "btc_lot1"
        assert item.coin == "BTC"

    def test_get_item_nonexistent(self, inventory_manager_with_items):
        """Test getting a non-existent item."""
        item = inventory_manager_with_items.get_item("nonexistent")
        assert item is None

    def test_update_item_existing(self, inventory_manager_with_items):
        """Test updating an existing item."""
        item = inventory_manager_with_items.get_item("btc_lot1")
        item.available_quantity = 0.5
        item.locked_quantity = 0.5
        result = inventory_manager_with_items.update_item(item)
        assert result is True
        updated = inventory_manager_with_items.get_item("btc_lot1")
        assert updated.available_quantity == 0.5
        assert updated.locked_quantity == 0.5

    def test_update_item_nonexistent(self, inventory_manager_with_items):
        """Test updating a non-existent item."""
        item = InventoryItem(
            id="nonexistent",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=1.0,
            locked_quantity=0.0,
        )
        result = inventory_manager_with_items.update_item(item)
        assert result is False

    def test_clear(self, inventory_manager_with_items):
        """Test clearing all items."""
        inventory_manager_with_items.clear()
        assert len(inventory_manager_with_items) == 0


class TestCoinQueries:
    """Test coin-specific query methods."""

    def test_get_items_by_coin(self, inventory_manager_with_items):
        """Test getting all items for a specific coin."""
        btc_items = inventory_manager_with_items.get_items_by_coin("BTC")
        assert len(btc_items) == 3
        assert all(item.coin == "BTC" for item in btc_items)

        eth_items = inventory_manager_with_items.get_items_by_coin("ETH")
        assert len(eth_items) == 1

        nonexistent = inventory_manager_with_items.get_items_by_coin("DOGE")
        assert len(nonexistent) == 0

    def test_get_total_quantity_by_coin(self, inventory_manager_with_items):
        """Test getting total quantity for a coin."""
        # BTC: 1.0 + 0.5 + 0.3 = 1.8
        btc_total = inventory_manager_with_items.get_total_quantity_by_coin("BTC")
        assert btc_total == pytest.approx(1.8)

        # ETH: 5.0
        eth_total = inventory_manager_with_items.get_total_quantity_by_coin("ETH")
        assert eth_total == pytest.approx(5.0)

        # Non-existent coin
        doge_total = inventory_manager_with_items.get_total_quantity_by_coin("DOGE")
        assert doge_total == 0.0

    def test_get_available_quantity_by_coin(self, inventory_manager_with_items):
        """Test getting available quantity for a coin."""
        # BTC: 1.0 + 0.3 + 0.0 = 1.3
        btc_available = inventory_manager_with_items.get_available_quantity_by_coin("BTC")
        assert btc_available == pytest.approx(1.3)

        # ETH: 3.0
        eth_available = inventory_manager_with_items.get_available_quantity_by_coin("ETH")
        assert eth_available == pytest.approx(3.0)

        # Non-existent coin
        doge_available = inventory_manager_with_items.get_available_quantity_by_coin("DOGE")
        assert doge_available == 0.0

    def test_get_locked_quantity_by_coin(self, inventory_manager_with_items):
        """Test getting locked quantity for a coin."""
        # BTC: 0.0 + 0.2 + 0.3 = 0.5
        btc_locked = inventory_manager_with_items.get_locked_quantity_by_coin("BTC")
        assert btc_locked == pytest.approx(0.5)

        # ETH: 2.0
        eth_locked = inventory_manager_with_items.get_locked_quantity_by_coin("ETH")
        assert eth_locked == pytest.approx(2.0)

        # USDC: 0.0
        usdc_locked = inventory_manager_with_items.get_locked_quantity_by_coin("USDC")
        assert usdc_locked == 0.0

        # Non-existent coin
        doge_locked = inventory_manager_with_items.get_locked_quantity_by_coin("DOGE")
        assert doge_locked == 0.0


class TestLockingInvariants:
    """Test that locking invariants are maintained."""

    def test_total_equals_available_plus_locked(self, inventory_manager_with_items):
        """Test that total quantity equals available + locked for each coin."""
        for coin in ["BTC", "ETH", "USDC"]:
            total = inventory_manager_with_items.get_total_quantity_by_coin(coin)
            available = inventory_manager_with_items.get_available_quantity_by_coin(coin)
            locked = inventory_manager_with_items.get_locked_quantity_by_coin(coin)
            assert total == pytest.approx(available + locked), \
                f"{coin}: total ({total}) != available ({available}) + locked ({locked})"

    def test_no_negative_quantities(self, inventory_manager_with_items):
        """Test that no negative quantities exist."""
        for item in inventory_manager_with_items:
            assert item.quantity >= 0, f"Item {item.id} has negative quantity"
            assert item.available_quantity >= 0, f"Item {item.id} has negative available_quantity"
            assert item.locked_quantity >= 0, f"Item {item.id} has negative locked_quantity"

    def test_available_plus_locked_equals_quantity_per_item(self, inventory_manager_with_items):
        """Test that each item's quantity equals its available + locked."""
        for item in inventory_manager_with_items:
            assert item.quantity == pytest.approx(item.available_quantity + item.locked_quantity), \
                f"Item {item.id}: quantity ({item.quantity}) != available ({item.available_quantity}) + locked ({item.locked_quantity})"


class TestValueCalculations:
    """Test value calculation methods with locked quantities."""

    def test_get_total_value_by_coin(self, inventory_manager_with_items):
        """Test total value calculation includes both available and locked."""
        # BTC: (1.0 * 45000) + (0.5 * 50000) + (0.3 * 55000) = 45000 + 25000 + 16500 = 86500
        btc_value = inventory_manager_with_items.get_total_value_by_coin("BTC")
        assert btc_value == pytest.approx(86500.0)

        # ETH: 5.0 * 2800 = 14000
        eth_value = inventory_manager_with_items.get_total_value_by_coin("ETH")
        assert eth_value == pytest.approx(14000.0)

    def test_get_weighted_average_price(self, inventory_manager_with_items):
        """Test weighted average price calculation."""
        # BTC weighted avg: 86500 / 1.8 = 48055.56
        btc_avg = inventory_manager_with_items.get_weighted_average_price("BTC")
        assert btc_avg == pytest.approx(48055.56, rel=1e-2)

        # ETH: single lot, so just the buy price
        eth_avg = inventory_manager_with_items.get_weighted_average_price("ETH")
        assert eth_avg == pytest.approx(2800.0)

        # Non-existent coin returns 0
        doge_avg = inventory_manager_with_items.get_weighted_average_price("DOGE")
        assert doge_avg == 0.0

    def test_weighted_average_price_zero_quantity(self):
        """Test weighted average price when total quantity is zero."""
        manager = InventoryManager([
            InventoryItem(
                id="test1",
                coin="BTC",
                buy_price=50000.0,
                quantity=0.0,
                available_quantity=0.0,
                locked_quantity=0.0,
            )
        ])
        avg = manager.get_weighted_average_price("BTC")
        assert avg == 0.0

    def test_get_total_portfolio_value(self, inventory_manager_with_items):
        """Test total portfolio value calculation."""
        # Sum of all values: 86500 (BTC) + 14000 (ETH) + 10000 (USDC) = 110500
        total = inventory_manager_with_items.get_total_portfolio_value()
        assert total == pytest.approx(110500.0)


class TestCoinSummary:
    """Test coin summary generation."""

    def test_get_coin_summary(self, inventory_manager_with_items):
        """Test getting summary of all coins."""
        summary = inventory_manager_with_items.get_coin_summary()
        
        assert len(summary) == 3  # BTC, ETH, USDC
        assert "BTC" in summary
        assert "ETH" in summary
        assert "USDC" in summary

        # Verify BTC summary
        btc = summary["BTC"]
        assert btc["total_quantity"] == pytest.approx(1.8)
        assert btc["available_quantity"] == pytest.approx(1.3)
        assert btc["locked_quantity"] == pytest.approx(0.5)
        assert btc["total_value"] == pytest.approx(86500.0)
        assert btc["weighted_avg_price"] == pytest.approx(48055.56, rel=1e-2)

        # Verify ETH summary
        eth = summary["ETH"]
        assert eth["total_quantity"] == pytest.approx(5.0)
        assert eth["available_quantity"] == pytest.approx(3.0)
        assert eth["locked_quantity"] == pytest.approx(2.0)

    def test_coin_summary_empty_inventory(self, empty_inventory_manager):
        """Test coin summary with empty inventory."""
        summary = empty_inventory_manager.get_coin_summary()
        assert summary == {}


class TestBackwardCompatibility:
    """Test backward compatibility features."""

    def test_getitem_existing_coin(self, inventory_manager_with_items):
        """Test __getitem__ for existing coin."""
        btc = inventory_manager_with_items["BTC"]
        assert btc["total_quantity"] == pytest.approx(1.8)
        assert btc["available_quantity"] == pytest.approx(1.3)
        assert btc["locked_quantity"] == pytest.approx(0.5)

    def test_getitem_nonexistent_coin(self, inventory_manager_with_items):
        """Test __getitem__ for non-existent coin returns zeros."""
        doge = inventory_manager_with_items["DOGE"]
        assert doge["total_quantity"] == 0.0
        assert doge["available_quantity"] == 0.0
        assert doge["locked_quantity"] == 0.0
        assert doge["total_value"] == 0.0
        assert doge["weighted_avg_price"] == 0.0

    def test_len(self, inventory_manager_with_items):
        """Test __len__ returns number of items."""
        assert len(inventory_manager_with_items) == 5

    def test_iter(self, inventory_manager_with_items):
        """Test __iter__ makes manager iterable."""
        items = list(inventory_manager_with_items)
        assert len(items) == 5
        assert all(isinstance(item, InventoryItem) for item in items)


class TestFIFOLotSelection:
    """Test FIFO lot selection scenarios (simulated through item ordering)."""

    def test_fifo_ordering_by_price(self):
        """Test that items can be sorted by price for FIFO locking."""
        items = [
            InventoryItem(
                id="lot3",
                coin="BTC",
                buy_price=55000.0,
                quantity=0.3,
                available_quantity=0.3,
                locked_quantity=0.0,
            ),
            InventoryItem(
                id="lot1",
                coin="BTC",
                buy_price=45000.0,
                quantity=1.0,
                available_quantity=1.0,
                locked_quantity=0.0,
            ),
            InventoryItem(
                id="lot2",
                coin="BTC",
                buy_price=50000.0,
                quantity=0.5,
                available_quantity=0.5,
                locked_quantity=0.0,
            ),
        ]
        manager = InventoryManager(items)
        btc_items = manager.get_items_by_coin("BTC")
        
        # Sort by buy_price (FIFO: lowest price first)
        sorted_items = sorted(btc_items, key=lambda x: x.buy_price)
        
        assert sorted_items[0].buy_price == 45000.0
        assert sorted_items[1].buy_price == 50000.0
        assert sorted_items[2].buy_price == 55000.0

    def test_partial_lot_locking_simulation(self):
        """Test simulating partial lot locking."""
        item = InventoryItem(
            id="lot1",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=1.0,
            locked_quantity=0.0,
        )
        manager = InventoryManager([item])
        
        # Simulate locking 0.6 BTC
        item.available_quantity = 0.4
        item.locked_quantity = 0.6
        manager.update_item(item)
        
        # Verify state
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(0.4)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.6)
        assert manager.get_total_quantity_by_coin("BTC") == pytest.approx(1.0)


class TestConcurrentLocks:
    """Test concurrent locking scenarios."""

    def test_multiple_locks_on_same_coin(self):
        """Test locking same coin for multiple HP positions."""
        items = [
            InventoryItem(
                id="btc_lot1",
                coin="BTC",
                buy_price=50000.0,
                quantity=2.0,
                available_quantity=2.0,
                locked_quantity=0.0,
            )
        ]
        manager = InventoryManager(items)
        
        # Simulate first lock for HP position 1 (0.5 BTC)
        item = manager.get_item("btc_lot1")
        item.available_quantity -= 0.5
        item.locked_quantity += 0.5
        manager.update_item(item)
        
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(1.5)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.5)
        
        # Simulate second lock for HP position 2 (0.8 BTC)
        item.available_quantity -= 0.8
        item.locked_quantity += 0.8
        manager.update_item(item)
        
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(0.7)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(1.3)

    def test_lock_with_insufficient_quantity(self):
        """Test that locking more than available is prevented by caller."""
        item = InventoryItem(
            id="btc_lot1",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=1.0,
            locked_quantity=0.0,
        )
        manager = InventoryManager([item])
        
        # Attempt to lock 1.5 BTC when only 1.0 available
        # The manager doesn't enforce this, but we verify the state
        available = manager.get_available_quantity_by_coin("BTC")
        quantity_to_lock = 1.5
        
        # Caller should check this condition
        assert quantity_to_lock > available
        
        # Only lock what's available
        actual_lock = min(quantity_to_lock, available)
        item.available_quantity -= actual_lock
        item.locked_quantity += actual_lock
        manager.update_item(item)
        
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(0.0)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(1.0)


class TestUnlockSemantics:
    """Test unlock semantics and edge cases."""

    def test_full_unlock(self):
        """Test full unlock releases all locked quantity."""
        item = InventoryItem(
            id="btc_lot1",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=0.3,
            locked_quantity=0.7,
        )
        manager = InventoryManager([item])
        
        # Unlock all 0.7 BTC
        item.locked_quantity = 0.0
        item.available_quantity = 1.0
        manager.update_item(item)
        
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(1.0)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.0)

    def test_partial_unlock(self):
        """Test partial unlock reduces locked and increases available."""
        item = InventoryItem(
            id="btc_lot1",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=0.3,
            locked_quantity=0.7,
        )
        manager = InventoryManager([item])
        
        # Unlock 0.4 BTC (leaving 0.3 still locked)
        item.locked_quantity -= 0.4
        item.available_quantity += 0.4
        manager.update_item(item)
        
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(0.7)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.3)

    def test_unlock_more_than_locked(self):
        """Test unlocking more than currently locked (should clamp to zero)."""
        item = InventoryItem(
            id="btc_lot1",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=0.5,
            locked_quantity=0.5,
        )
        manager = InventoryManager([item])
        
        # Try to unlock 0.8 when only 0.5 is locked
        unlock_amount = 0.8
        actual_unlock = min(unlock_amount, item.locked_quantity)
        
        item.locked_quantity -= actual_unlock
        item.available_quantity += actual_unlock
        
        # Ensure no negative values
        item.locked_quantity = max(0.0, item.locked_quantity)
        manager.update_item(item)
        
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(1.0)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.0)

    def test_unlock_after_cancel_no_fills(self):
        """Test unlock when HP position cancelled with no fills."""
        items = [
            InventoryItem(
                id="btc_lot1",
                coin="BTC",
                buy_price=45000.0,
                quantity=1.0,
                available_quantity=0.4,
                locked_quantity=0.6,
            ),
            InventoryItem(
                id="btc_lot2",
                coin="BTC",
                buy_price=50000.0,
                quantity=0.5,
                available_quantity=0.4,
                locked_quantity=0.1,
            ),
        ]
        manager = InventoryManager(items)
        
        # Initially: 0.7 locked total
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.7)
        
        # Cancel HP position: unlock all 0.7 BTC
        for item in manager.get_items_by_coin("BTC"):
            item.available_quantity += item.locked_quantity
            item.locked_quantity = 0.0
            manager.update_item(item)
        
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.0)
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(1.5)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_coin_queries(self, empty_inventory_manager):
        """Test queries on empty inventory."""
        assert empty_inventory_manager.get_total_quantity_by_coin("BTC") == 0.0
        assert empty_inventory_manager.get_available_quantity_by_coin("BTC") == 0.0
        assert empty_inventory_manager.get_locked_quantity_by_coin("BTC") == 0.0
        assert empty_inventory_manager.get_total_value_by_coin("BTC") == 0.0
        assert empty_inventory_manager.get_weighted_average_price("BTC") == 0.0

    def test_multiple_operations_maintain_consistency(self):
        """Test that multiple operations maintain consistency."""
        manager = InventoryManager()
        
        # Add item
        item1 = InventoryItem(
            id="btc1",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=1.0,
            locked_quantity=0.0,
        )
        manager.add_item(item1)
        
        # Lock some
        item1.available_quantity = 0.6
        item1.locked_quantity = 0.4
        manager.update_item(item1)
        
        # Add another item
        item2 = InventoryItem(
            id="btc2",
            coin="BTC",
            buy_price=51000.0,
            quantity=0.5,
            available_quantity=0.5,
            locked_quantity=0.0,
        )
        manager.add_item(item2)
        
        # Verify totals
        assert manager.get_total_quantity_by_coin("BTC") == pytest.approx(1.5)
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(1.1)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.4)
        
        # Remove first item
        manager.remove_item("btc1")
        
        assert manager.get_total_quantity_by_coin("BTC") == pytest.approx(0.5)
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(0.5)
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.0)

    def test_zero_quantity_items(self):
        """Test handling of items with zero quantity."""
        item = InventoryItem(
            id="btc1",
            coin="BTC",
            buy_price=50000.0,
            quantity=0.0,
            available_quantity=0.0,
            locked_quantity=0.0,
        )
        manager = InventoryManager([item])
        
        assert manager.get_total_quantity_by_coin("BTC") == 0.0
        assert manager.get_available_quantity_by_coin("BTC") == 0.0
        assert manager.get_locked_quantity_by_coin("BTC") == 0.0

    def test_very_small_quantities(self):
        """Test handling of very small quantities (precision)."""
        item = InventoryItem(
            id="btc1",
            coin="BTC",
            buy_price=50000.0,
            quantity=0.00000001,
            available_quantity=0.00000001,
            locked_quantity=0.0,
        )
        manager = InventoryManager([item])
        
        assert manager.get_total_quantity_by_coin("BTC") == pytest.approx(0.00000001)

    def test_large_quantities(self):
        """Test handling of large quantities."""
        item = InventoryItem(
            id="usdc1",
            coin="USDC",
            buy_price=1.0,
            quantity=1_000_000_000.0,
            available_quantity=500_000_000.0,
            locked_quantity=500_000_000.0,
        )
        manager = InventoryManager([item])
        
        assert manager.get_total_quantity_by_coin("USDC") == pytest.approx(1_000_000_000.0)
        assert manager.get_available_quantity_by_coin("USDC") == pytest.approx(500_000_000.0)
        assert manager.get_locked_quantity_by_coin("USDC") == pytest.approx(500_000_000.0)


class TestMultipleLots:
    """Test scenarios with multiple lots per coin."""

    def test_multiple_lots_fifo_selection(self):
        """Test that multiple lots can be selected in FIFO order."""
        items = [
            InventoryItem(
                id="btc_lot1",
                coin="BTC",
                buy_price=45000.0,
                quantity=0.3,
                available_quantity=0.3,
                locked_quantity=0.0,
            ),
            InventoryItem(
                id="btc_lot2",
                coin="BTC",
                buy_price=50000.0,
                quantity=0.4,
                available_quantity=0.4,
                locked_quantity=0.0,
            ),
            InventoryItem(
                id="btc_lot3",
                coin="BTC",
                buy_price=55000.0,
                quantity=0.3,
                available_quantity=0.3,
                locked_quantity=0.0,
            ),
        ]
        manager = InventoryManager(items)
        
        # Simulate locking 0.6 BTC using FIFO
        # Should lock: full lot1 (0.3) + partial lot2 (0.3)
        lot1 = manager.get_item("btc_lot1")
        lot1.available_quantity = 0.0
        lot1.locked_quantity = 0.3
        manager.update_item(lot1)
        
        lot2 = manager.get_item("btc_lot2")
        lot2.available_quantity = 0.1
        lot2.locked_quantity = 0.3
        manager.update_item(lot2)
        
        assert manager.get_locked_quantity_by_coin("BTC") == pytest.approx(0.6)
        assert manager.get_available_quantity_by_coin("BTC") == pytest.approx(0.4)

    def test_multiple_lots_weighted_average(self):
        """Test weighted average across multiple lots with different lock states."""
        items = [
            InventoryItem(
                id="btc_lot1",
                coin="BTC",
                buy_price=45000.0,
                quantity=1.0,
                available_quantity=0.5,
                locked_quantity=0.5,
            ),
            InventoryItem(
                id="btc_lot2",
                coin="BTC",
                buy_price=55000.0,
                quantity=1.0,
                available_quantity=0.8,
                locked_quantity=0.2,
            ),
        ]
        manager = InventoryManager(items)
        
        # Weighted avg: (1.0 * 45000 + 1.0 * 55000) / 2.0 = 50000
        avg = manager.get_weighted_average_price("BTC")
        assert avg == pytest.approx(50000.0)
        
        # Total value includes both available and locked
        value = manager.get_total_value_by_coin("BTC")
        assert value == pytest.approx(100000.0)


class TestStatePersistence:
    """Test that inventory state can be persisted and restored."""

    def test_serialize_and_restore_state(self):
        """Test that inventory state can be serialized and restored."""
        original_items = [
            InventoryItem(
                id="btc1",
                coin="BTC",
                buy_price=50000.0,
                quantity=1.0,
                available_quantity=0.6,
                locked_quantity=0.4,
            ),
            InventoryItem(
                id="eth1",
                coin="ETH",
                buy_price=3000.0,
                quantity=2.0,
                available_quantity=1.5,
                locked_quantity=0.5,
            ),
        ]
        original_manager = InventoryManager(original_items)
        
        # Simulate serialization by copying inventory list
        serialized = list(original_manager)
        
        # Create new manager from serialized state
        restored_manager = InventoryManager(serialized)
        
        # Verify state is identical
        assert restored_manager.get_total_quantity_by_coin("BTC") == \
               original_manager.get_total_quantity_by_coin("BTC")
        assert restored_manager.get_available_quantity_by_coin("BTC") == \
               original_manager.get_available_quantity_by_coin("BTC")
        assert restored_manager.get_locked_quantity_by_coin("BTC") == \
               original_manager.get_locked_quantity_by_coin("BTC")
        assert restored_manager.get_locked_quantity_by_coin("ETH") == \
               original_manager.get_locked_quantity_by_coin("ETH")
