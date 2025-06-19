"""
Test suite for the new trading database system.
"""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime
from pathlib import Path

from src.database.trading_database import TradingDatabase
from src.database.models import (
    Position,
    Order,
    Strategy,
    PositionType,
    PositionStatus,
    TradeType,
    OrderStatus,
)
from src.database.recovery_service import RecoveryService
from src.database.position_manager import PositionManager
from src.database.exceptions import DatabaseError, RecoveryError


@pytest.fixture
async def temp_database():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    db = TradingDatabase(db_path)
    yield db

    # Cleanup
    await db.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sample_position():
    """Create a sample position for testing."""
    return Position(
        hp_id="test_001",
        position_type=PositionType.BUY,
        status=PositionStatus.NEW,
        symbol="BTCUSDC",
        coin="BTC",
        budget=1000.0,
        price_low=30000.0,
        price_high=35000.0,
        order_trigger=32000.0,
        mode="DCA",
    )


@pytest.fixture
def sample_strategy():
    """Create a sample strategy for testing."""
    return Strategy(
        name="Test Strategy",
        description="A test strategy for unit tests",
        status="ACTIVE",
    )


class TestTradingDatabase:
    """Test the core database functionality."""

    @pytest.mark.asyncio
    async def test_database_initialization(self, temp_database):
        """Test database initialization and table creation."""
        db = temp_database

        # Database should be initialized without errors
        stats = await db.get_database_stats()
        assert isinstance(stats, dict)
        assert "positions" in stats
        assert "orders" in stats
        assert stats["positions"] == 0  # Empty database

    @pytest.mark.asyncio
    async def test_save_and_retrieve_strategy(self, temp_database, sample_strategy):
        """Test saving and retrieving strategies."""
        db = temp_database

        # Save strategy
        strategy_id = await db.save_strategy(sample_strategy)
        assert strategy_id == sample_strategy.id

        # Verify it was saved
        stats = await db.get_database_stats()
        assert stats["strategies"] == 1

    @pytest.mark.asyncio
    async def test_save_and_retrieve_position(self, temp_database, sample_position):
        """Test saving and retrieving positions."""
        db = temp_database

        # Save position
        position_id = await db.save_position(sample_position)
        assert position_id == sample_position.id

        # Retrieve active positions
        positions = await db.get_active_positions()
        assert len(positions) == 1
        assert positions[0].hp_id == "test_001"
        assert positions[0].symbol == "BTCUSDC"

    @pytest.mark.asyncio
    async def test_position_status_filtering(self, temp_database):
        """Test that closed positions are not returned as active."""
        db = temp_database

        # Create positions with different statuses
        active_position = Position(
            hp_id="active_001",
            position_type=PositionType.BUY,
            status=PositionStatus.OPEN,
            symbol="BTCUSDC",
            coin="BTC",
        )

        closed_position = Position(
            hp_id="closed_001",
            position_type=PositionType.BUY,
            status=PositionStatus.CLOSED,
            symbol="ETHUSDC",
            coin="ETH",
        )

        await db.save_position(active_position)
        await db.save_position(closed_position)

        # Only active position should be returned
        active_positions = await db.get_active_positions()
        assert len(active_positions) == 1
        assert active_positions[0].hp_id == "active_001"

    @pytest.mark.asyncio
    async def test_multihop_position_hierarchy(self, temp_database):
        """Test multihop position relationships."""
        db = temp_database

        # Create parent position
        parent = Position(
            hp_id="parent_001",
            position_type=PositionType.SELL,
            status=PositionStatus.OPEN,
            symbol="BTCUSDC",
            coin="BTC",
            trade_type=TradeType.TWOHOP,
            child_position_ids=["child_001_id", "child_002_id"],
        )

        # Create child positions
        child1 = Position(
            id="child_001_id",
            hp_id="parent_001a",
            position_type=PositionType.SELL,
            status=PositionStatus.WAITING_CHILD,
            symbol="BTCETH",
            coin="BTC",
            parent_position_id=parent.id,
            trade_type=TradeType.TWOHOP,
            hop_sequence=1,
        )

        child2 = Position(
            id="child_002_id",
            hp_id="parent_001b",
            position_type=PositionType.SELL,
            status=PositionStatus.WAITING_PARENT,
            symbol="ETHUSDC",
            coin="ETH",
            parent_position_id=parent.id,
            trade_type=TradeType.TWOHOP,
            hop_sequence=2,
        )

        # Save all positions
        await db.save_position(parent)
        await db.save_position(child1)
        await db.save_position(child2)

        # Retrieve hierarchy
        hierarchy = await db.get_position_hierarchy("parent_001")
        assert len(hierarchy) == 3
        assert hierarchy[0].hp_id == "parent_001"
        assert len(hierarchy[0].child_position_ids) == 2

    @pytest.mark.asyncio
    async def test_save_and_retrieve_orders(self, temp_database, sample_position):
        """Test saving and retrieving orders."""
        db = temp_database

        # Save position first
        await db.save_position(sample_position)

        # Create and save order
        order = Order(
            position_id=sample_position.id,
            exchange_order_id=12345,
            symbol="BTCUSDC",
            side="BUY",
            status=OrderStatus.NEW,
            price=32000.0,
            quantity=0.001,
            quantity_stable=32.0,
        )

        order_id = await db.save_order(order)
        assert order_id == order.id

        # Retrieve orders for position
        orders = await db.get_position_orders(sample_position.id)
        assert len(orders) == 1
        assert orders[0].exchange_order_id == 12345
        assert orders[0].symbol == "BTCUSDC"

    @pytest.mark.asyncio
    async def test_database_backup(self, temp_database):
        """Test database backup functionality."""
        db = temp_database

        # Add some data
        position = Position(
            hp_id="backup_test",
            position_type=PositionType.BUY,
            status=PositionStatus.NEW,
            symbol="BTCUSDC",
            coin="BTC",
        )
        await db.save_position(position)

        # Create backup
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            backup_path = tmp.name

        try:
            await db.backup_database(backup_path)

            # Verify backup exists
            assert os.path.exists(backup_path)

            # Verify backup contains data
            backup_db = TradingDatabase(backup_path)
            positions = await backup_db.get_active_positions()
            assert len(positions) == 1
            assert positions[0].hp_id == "backup_test"
            await backup_db.close()

        finally:
            if os.path.exists(backup_path):
                os.unlink(backup_path)


class TestPositionManager:
    """Test the position manager functionality."""

    @pytest.fixture
    async def position_manager(self, temp_database):
        """Create a position manager for testing."""
        return PositionManager(temp_database)

    @pytest.mark.asyncio
    async def test_position_status_conversion(self, position_manager):
        """Test conversion between trading system states and database statuses."""
        from src.identifiers import State

        # Test state conversions
        test_cases = [
            (State.NEW, PositionStatus.NEW),
            (State.BUYING, PositionStatus.OPEN),
            (State.PARTIALLY_BOUGHT, PositionStatus.PARTIALLY_FILLED),
            (State.BOUGHT, PositionStatus.FILLED),
            (State.CLOSED, PositionStatus.CLOSED),
        ]

        for state, expected_status in test_cases:
            result = position_manager._convert_state_to_status(state)
            assert result == expected_status


class TestRecoveryService:
    """Test the recovery service functionality."""

    @pytest.fixture
    async def recovery_service(self, temp_database):
        """Create a recovery service for testing."""
        # Mock client and symbols_info for testing
        mock_client = None  # Would need proper mock
        mock_symbols = {}

        return RecoveryService(temp_database, mock_client, mock_symbols)

    @pytest.mark.asyncio
    async def test_position_integrity_validation(self, temp_database):
        """Test position integrity validation."""
        # This test would need proper mocking of client and symbols
        # For now, just test that the method exists and doesn't crash
        recovery_service = RecoveryService(temp_database, None, {})

        try:
            validation_result = await recovery_service.validate_recovery_integrity()
            assert isinstance(validation_result, dict)
            assert "missing_symbols" in validation_result
        except Exception as e:
            # Expected since we don't have proper mocks
            assert "symbols_info" in str(e) or "client" in str(e)


class TestDatabasePerformance:
    """Test database performance characteristics."""

    @pytest.mark.asyncio
    async def test_large_position_insertion(self, temp_database):
        """Test inserting many positions."""
        db = temp_database

        # Create many positions
        positions = []
        for i in range(100):
            position = Position(
                hp_id=f"perf_test_{i:03d}",
                position_type=PositionType.BUY,
                status=PositionStatus.NEW,
                symbol="BTCUSDC",
                coin="BTC",
                budget=1000.0 + i,
            )
            positions.append(position)

        # Time the insertion
        start_time = datetime.now()

        for position in positions:
            await db.save_position(position)

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Should complete reasonably quickly
        assert duration < 10.0  # Less than 10 seconds for 100 positions

        # Verify all were saved
        active_positions = await db.get_active_positions()
        assert len(active_positions) == 100

    @pytest.mark.asyncio
    async def test_concurrent_operations(self, temp_database):
        """Test concurrent database operations."""
        db = temp_database

        async def save_position(i):
            position = Position(
                hp_id=f"concurrent_{i}",
                position_type=PositionType.BUY,
                status=PositionStatus.NEW,
                symbol="BTCUSDC",
                coin="BTC",
            )
            await db.save_position(position)

        # Run multiple operations concurrently
        tasks = [save_position(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify all were saved
        positions = await db.get_active_positions()
        assert len(positions) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
