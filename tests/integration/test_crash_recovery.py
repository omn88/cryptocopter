"""
Comprehensive test suite for crash recovery scenarios.

This module tests the ability to recover from system crashes in all possible
position states and trading scenarios.
"""

from typing import Dict

from unittest.mock import AsyncMock
from binance.enums import ORDER_STATUS_PARTIALLY_FILLED, ORDER_STATUS_FILLED

from src.database.models import (
    Position,
    Order,
    Strategy,
    PositionType,
    PositionStatus,
    TradeType,
    OrderStatus,
)
from src.database.trading_database import TradingDatabase
from src.database.recovery_service import RecoveryService


async def create_test_strategy(test_db: TradingDatabase) -> str:
    """Create a test strategy."""
    strategy = Strategy(
        name="Test Recovery Strategy",
        description="Strategy for testing recovery scenarios",
        status="ACTIVE",
    )
    return await test_db.save_strategy(strategy)


def simulate_exchange_order_data(
    order_id: int, status: str = "NEW", executed_qty: str = "0.0"
) -> Dict:
    """Simulate exchange order data in your testing pattern."""
    return {
        "orderId": order_id,
        "symbol": "BTCUSDT",
        "status": status,
        "side": "BUY",
        "type": "LIMIT",
        "origQty": "0.001",
        "price": "99000.0",
        "executedQty": executed_qty,
        "updateTime": 1566818724722,
    }


# ========================================================================
# TEST CASES FOR NEW POSITIONS
# ========================================================================


async def test_recover_new_buy_position(
    test_db: TradingDatabase, recovery_service: RecoveryService
):
    """Test recovery of a NEW buy position (just created, no orders yet)."""
    strategy_id = await create_test_strategy(test_db)

    # Create a NEW buy position
    position = Position(
        hp_id="hp_new_buy_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.NEW,
        symbol="BTCUSDT",
        coin="BTC",
        budget=100.0,
        price_low=95000.0,
        price_high=105000.0,
        order_trigger=1.0,
        mode="DCA",
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    # Test recovery
    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_new_buy_001"
    assert recovered.status == PositionStatus.NEW
    assert recovered.budget == 100.0


async def test_recover_new_sell_position(
    test_db: TradingDatabase, recovery_service: RecoveryService
):
    """Test recovery of a NEW sell position."""
    strategy_id = await create_test_strategy(test_db)

    position = Position(
        hp_id="hp_new_sell_001",
        strategy_id=strategy_id,
        position_type=PositionType.SELL,
        status=PositionStatus.NEW,
        symbol="BTCUSDT",
        coin="BTC",
        quantity=0.001,
        buy_price=98000.0,
        sell_price=102000.0,
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_new_sell_001"
    assert recovered.status == PositionStatus.NEW
    assert recovered.quantity == 0.001


# ========================================================================
# TEST CASES FOR OPEN POSITIONS (WITH ACTIVE ORDERS)
# ========================================================================


async def test_recover_open_buy_position_with_orders(
    test_db: TradingDatabase,
    recovery_service: RecoveryService,
    mock_async_client: AsyncMock,
):
    """Test recovery of OPEN buy position with active orders."""
    strategy_id = await create_test_strategy(test_db)

    # Create OPEN buy position
    position = Position(
        hp_id="hp_open_buy_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.OPEN,
        symbol="BTCUSDT",
        coin="BTC",
        budget=100.0,
        price_low=95000.0,
        price_high=105000.0,
        order_trigger=1.0,
        mode="DCA",
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    # Create associated order
    order = Order(
        position_id=position.id,
        exchange_order_id=12345,
        symbol="BTCUSDT",
        side="BUY",
        status=OrderStatus.NEW,
        price=99000.0,
        quantity=0.001,
        order_type="LIMIT",
    )
    await test_db.save_order(order)  # Simulate exchange response using your pattern
    mock_async_client.get_order.return_value = simulate_exchange_order_data(
        12345, "NEW", "0.0"
    )

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_open_buy_001"
    assert recovered.status == PositionStatus.OPEN

    # Verify orders are recovered
    orders = await test_db.get_position_orders(position.id)
    assert len(orders) == 1
    assert orders[0].exchange_order_id == 12345


async def test_recover_open_sell_position_with_orders(
    test_db: TradingDatabase,
    recovery_service: RecoveryService,
    mock_async_client: AsyncMock,
):
    """Test recovery of OPEN sell position with active orders."""
    strategy_id = await create_test_strategy(test_db)

    position = Position(
        hp_id="hp_open_sell_001",
        strategy_id=strategy_id,
        position_type=PositionType.SELL,
        status=PositionStatus.OPEN,
        symbol="BTCUSDT",
        coin="BTC",
        quantity=0.001,
        buy_price=98000.0,
        sell_price=102000.0,
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    order = Order(
        position_id=position.id,
        exchange_order_id=54321,
        symbol="BTCUSDT",
        side="SELL",
        status=OrderStatus.NEW,
        price=102000.0,
        quantity=0.001,
        order_type="LIMIT",
    )
    await test_db.save_order(order)  # Simulate exchange response for sell order
    sell_order_data = simulate_exchange_order_data(54321, "NEW", "0.0")
    sell_order_data["side"] = "SELL"
    sell_order_data["price"] = "102000.0"
    mock_async_client.get_order.return_value = sell_order_data

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_open_sell_001"
    assert recovered.status == PositionStatus.OPEN


# ========================================================================
# TEST CASES FOR PARTIALLY FILLED POSITIONS
# ========================================================================


async def test_recover_partially_filled_buy_position(
    test_db: TradingDatabase,
    recovery_service: RecoveryService,
    mock_async_client: AsyncMock,
):
    """Test recovery of partially filled buy position."""
    strategy_id = await create_test_strategy(test_db)

    position = Position(
        hp_id="hp_partial_buy_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.PARTIALLY_FILLED,
        symbol="BTCUSDT",
        coin="BTC",
        budget=100.0,
        price_low=95000.0,
        price_high=105000.0,
        order_trigger=1.0,
        realized_quantity=0.0005,  # Partially filled
        mode="DCA",
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    order = Order(
        position_id=position.id,
        exchange_order_id=11111,
        symbol="BTCUSDT",
        side="BUY",
        status=OrderStatus.PARTIALLY_FILLED,
        price=99000.0,
        quantity=0.001,
        realized_quantity=0.0005,
        order_type="LIMIT",
    )
    await test_db.save_order(order)  # Simulate partially filled exchange response
    mock_async_client.get_order.return_value = simulate_exchange_order_data(
        11111, ORDER_STATUS_PARTIALLY_FILLED, "0.0005"
    )

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_partial_buy_001"
    assert recovered.status == PositionStatus.PARTIALLY_FILLED
    assert recovered.realized_quantity == 0.0005


# ========================================================================
# TEST CASES FOR FILLED POSITIONS
# ========================================================================


async def test_recover_filled_buy_position(
    test_db: TradingDatabase,
    recovery_service: RecoveryService,
):
    """Test recovery of fully filled buy position."""
    strategy_id = await create_test_strategy(test_db)

    position = Position(
        hp_id="hp_filled_buy_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.FILLED,
        symbol="BTCUSDT",
        coin="BTC",
        budget=100.0,
        price_low=95000.0,
        price_high=105000.0,
        order_trigger=1.0,
        realized_quantity=0.001,  # Fully bought
        mode="DCA",
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    # No orders needed for filled position
    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_filled_buy_001"
    assert recovered.status == PositionStatus.FILLED
    assert recovered.realized_quantity == 0.001


# ========================================================================
# TEST CASES FOR EXCHANGE STATUS MISMATCH SCENARIOS
# ========================================================================


async def test_recover_position_with_exchange_status_mismatch(
    test_db: TradingDatabase,
    recovery_service: RecoveryService,
    mock_async_client: AsyncMock,
):
    """Test recovery when DB and exchange have different order statuses."""
    strategy_id = await create_test_strategy(test_db)

    position = Position(
        hp_id="hp_status_mismatch_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.OPEN,
        symbol="BTCUSDT",
        coin="BTC",
        budget=100.0,
        price_low=95000.0,
        price_high=105000.0,
        order_trigger=1.0,
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    # DB shows order as NEW
    order = Order(
        position_id=position.id,
        exchange_order_id=88888,
        symbol="BTCUSDT",
        side="BUY",
        status=OrderStatus.NEW,
        price=99000.0,
        quantity=0.001,
        order_type="LIMIT",
    )
    await test_db.save_order(order)  # Exchange shows order as FILLED
    mock_async_client.get_order.return_value = simulate_exchange_order_data(
        88888, ORDER_STATUS_FILLED, "0.001"
    )

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_status_mismatch_001"
    # Status should be updated to FILLED based on exchange data
    assert recovered.status == PositionStatus.FILLED
    assert recovered.realized_quantity == 0.001


async def test_recover_position_with_missing_exchange_order(
    test_db: TradingDatabase,
    recovery_service: RecoveryService,
    mock_async_client: AsyncMock,
):
    """Test recovery when order exists in DB but not on exchange."""
    strategy_id = await create_test_strategy(test_db)

    position = Position(
        hp_id="hp_missing_order_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.OPEN,
        symbol="BTCUSDT",
        coin="BTC",
        budget=100.0,
        price_low=95000.0,
        price_high=105000.0,
        order_trigger=1.0,
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    # Order exists in DB
    order = Order(
        position_id=position.id,
        exchange_order_id=99999,
        symbol="BTCUSDT",
        side="BUY",
        status=OrderStatus.NEW,
        price=99000.0,
        quantity=0.001,
        order_type="LIMIT",
    )
    await test_db.save_order(order)  # Exchange throws error (order not found)
    mock_async_client.get_order.side_effect = Exception("Order not found")

    recovered_positions = await recovery_service.recover_positions_for_testing()

    # Should still recover position and handle missing order gracefully
    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_missing_order_001"


# ========================================================================
# TEST CASES FOR MULTIHOP POSITIONS
# ========================================================================


async def test_recover_multihop_parent_position(
    test_db: TradingDatabase, recovery_service: RecoveryService
):
    """Test recovery of parent position in multihop trade."""
    strategy_id = await create_test_strategy(test_db)

    # Parent position
    parent_position = Position(
        hp_id="hp_multihop_parent_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.WAITING_CHILD,
        symbol="BTCETH",
        coin="BTC",
        budget=100.0,
        price_low=0.02,
        price_high=0.03,
        order_trigger=2.5,
        trade_type=TradeType.TWOHOP,
        hop_sequence=0,
        child_position_ids=["child_001"],
    )
    await test_db.save_position(parent_position)

    # Child position
    child_position = Position(
        hp_id="hp_multihop_child_001",
        strategy_id=strategy_id,
        position_type=PositionType.SELL,
        status=PositionStatus.OPEN,
        symbol="ETHUSDT",
        coin="ETH",
        quantity=0.05,
        buy_price=2400.0,
        sell_price=2500.0,
        trade_type=TradeType.TWOHOP,
        hop_sequence=1,
        parent_position_id=parent_position.id,
    )
    await test_db.save_position(child_position)

    # Update parent with child ID
    parent_position.child_position_ids = [child_position.id]
    await test_db.save_position(parent_position)

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 2

    # Find parent and child
    parent = next(p for p in recovered_positions if p.hp_id == "hp_multihop_parent_001")
    child = next(p for p in recovered_positions if p.hp_id == "hp_multihop_child_001")

    assert parent.status == PositionStatus.WAITING_CHILD
    assert parent.trade_type == TradeType.TWOHOP
    assert parent.hop_sequence == 0
    assert child.id in parent.child_position_ids

    assert child.status == PositionStatus.OPEN
    assert child.parent_position_id == parent.id
    assert child.hop_sequence == 1


# ========================================================================
# TEST CASES FOR PERFORMANCE AND EDGE CASES
# ========================================================================


async def test_recover_empty_database(recovery_service: RecoveryService):
    """Test recovery when database is empty (fresh start)."""
    recovered_positions = await recovery_service.recover_positions_for_testing()
    assert len(recovered_positions) == 0


async def test_recover_multiple_positions_different_states(
    test_db: TradingDatabase, recovery_service: RecoveryService
):
    """Test recovery of multiple positions in different states simultaneously."""
    strategy_id = await create_test_strategy(test_db)

    # Create positions in various states
    positions_data = [
        ("hp_multi_new", PositionStatus.NEW, PositionType.BUY, 0.0),
        ("hp_multi_open", PositionStatus.OPEN, PositionType.BUY, 0.0),
        ("hp_multi_partial", PositionStatus.PARTIALLY_FILLED, PositionType.BUY, 0.0005),
        ("hp_multi_filled", PositionStatus.FILLED, PositionType.BUY, 0.001),
        ("hp_multi_sell", PositionStatus.OPEN, PositionType.SELL, 0.0),
    ]

    for hp_id, status, pos_type, realized_qty in positions_data:
        position = Position(
            hp_id=hp_id,
            strategy_id=strategy_id,
            position_type=pos_type,
            status=status,
            symbol="BTCUSDT",
            coin="BTC",
            budget=100.0 if pos_type == PositionType.BUY else 0.0,
            quantity=0.001 if pos_type == PositionType.SELL else 0.0,
            price_low=95000.0 if pos_type == PositionType.BUY else 0.0,
            price_high=105000.0 if pos_type == PositionType.BUY else 0.0,
            order_trigger=1.0 if pos_type == PositionType.BUY else 0.0,
            buy_price=98000.0 if pos_type == PositionType.SELL else 0.0,
            sell_price=102000.0 if pos_type == PositionType.SELL else 0.0,
            realized_quantity=realized_qty,
            trade_type=TradeType.DIRECT,
        )
        await test_db.save_position(position)

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 5

    # Verify each position was recovered correctly
    hp_ids = {p.hp_id for p in recovered_positions}
    expected_hp_ids = {data[0] for data in positions_data}
    assert hp_ids == expected_hp_ids


async def test_recover_position_with_metadata(
    test_db: TradingDatabase, recovery_service: RecoveryService
):
    """Test recovery of position with custom metadata."""
    strategy_id = await create_test_strategy(test_db)

    metadata = {
        "original_target": 110000.0,
        "dca_attempts": 3,
        "last_price_check": "2025-06-21T10:00:00",
        "custom_flags": ["aggressive", "high_priority"],
    }

    position = Position(
        hp_id="hp_metadata_001",
        strategy_id=strategy_id,
        position_type=PositionType.BUY,
        status=PositionStatus.OPEN,
        symbol="BTCUSDT",
        coin="BTC",
        budget=100.0,
        price_low=95000.0,
        price_high=105000.0,
        order_trigger=1.0,
        metadata=metadata,
        trade_type=TradeType.DIRECT,
    )
    await test_db.save_position(position)

    recovered_positions = await recovery_service.recover_positions_for_testing()

    assert len(recovered_positions) == 1
    recovered = recovered_positions[0]
    assert recovered.hp_id == "hp_metadata_001"
    assert recovered.metadata == metadata
    assert recovered.metadata["dca_attempts"] == 3
    assert "aggressive" in recovered.metadata["custom_flags"]


# ========================================================================
# BASIC FUNCTIONALITY TESTS - FOCUS ON CORE RECOVERY SCENARIOS
# ========================================================================
