"""Integration tests for Database (trading_database.py).

Covers direct DB operations in isolation — no strategy executor, no broker.
Uses the shared `test_db` fixture from the root conftest which provides a
fresh temp-file SQLite database per test and closes it afterwards.
"""

import time
from typing import Any

import pytest

from src.database.trading_database import Database
from src.database.models import (
    Order,
    OrderStatus,
    Position,
    PositionStatus,
    PositionType,
    TradeType,
)
from src.database.exceptions import DatabaseError
from src.domain.inventory import InventoryItem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_position(hp_id: str = "1000", **kwargs: Any) -> Position:
    defaults: dict[str, Any] = dict(
        hp_id=hp_id,
        symbol="BTCUSDC",
        coin="BTC",
        position_type=PositionType.BUY,
        status=PositionStatus.OPEN,
        strategy_state="BUYING",
        buy_price=50000.0,
        quantity=0.02,
        budget=1000.0,
        end_currency="USDC",
    )
    defaults.update(kwargs)
    return Position(**defaults)


def _make_order(position_id: str = "1000", **kwargs: Any) -> Order:
    defaults: dict[str, Any] = dict(
        position_id=position_id,
        symbol="BTCUSDC",
        side="BUY",
        status=OrderStatus.NEW,
        price=50000.0,
        quantity=0.02,
    )
    defaults.update(kwargs)
    return Order(**defaults)


def _make_inventory_item(
    item_id: str = "inv1", coin: str = "BTC", **kwargs: Any
) -> InventoryItem:
    defaults: dict[str, Any] = dict(
        id=item_id,
        coin=coin,
        buy_price=50000.0,
        quantity=0.5,
        available_quantity=0.5,
        locked_quantity=0.0,
        source="EXCHANGE",
        timestamp=time.time(),
        notes="test item",
    )
    defaults.update(kwargs)
    return InventoryItem(**defaults)


# ---------------------------------------------------------------------------
# Position CRUD
# ---------------------------------------------------------------------------


class TestSaveAndRetrievePosition:
    async def test_save_returns_hp_id(self, test_db: Database):
        pos = _make_position("1000")
        result = await test_db.save_position(pos)
        assert result == "1000"

    async def test_saved_position_appears_in_active_positions(self, test_db: Database):
        pos = _make_position("1001", status=PositionStatus.OPEN)
        await test_db.save_position(pos)
        active = await test_db.get_active_positions()
        hp_ids = [p.hp_id for p in active]
        assert "1001" in hp_ids

    async def test_closed_position_excluded_from_active(self, test_db: Database):
        pos = _make_position("1002", status=PositionStatus.CLOSED)
        await test_db.save_position(pos)
        active = await test_db.get_active_positions()
        hp_ids = [p.hp_id for p in active]
        assert "1002" not in hp_ids

    async def test_canceled_position_excluded_from_active(self, test_db: Database):
        pos = _make_position("1003", status=PositionStatus.CANCELED)
        await test_db.save_position(pos)
        active = await test_db.get_active_positions()
        hp_ids = [p.hp_id for p in active]
        assert "1003" not in hp_ids

    async def test_upsert_overwrites_existing_position(self, test_db: Database):
        pos = _make_position("1004", status=PositionStatus.OPEN)
        await test_db.save_position(pos)
        pos.status = PositionStatus.FILLED
        pos.strategy_state = "SELLING"
        await test_db.save_position(pos)
        active = await test_db.get_active_positions()
        match = next((p for p in active if p.hp_id == "1004"), None)
        assert match is not None
        assert match.status == PositionStatus.FILLED
        assert match.strategy_state == "SELLING"

    async def test_position_fields_round_trip(self, test_db: Database):
        pos = _make_position(
            "1005",
            buy_price=48000.0,
            sell_price=52000.0,
            quantity=0.05,
            budget=2400.0,
            realized_quantity=0.025,
            end_currency="USDC",
            trade_type=TradeType.DIRECT,
            completeness=0.5,
        )
        await test_db.save_position(pos)
        active = await test_db.get_active_positions()
        match = next((p for p in active if p.hp_id == "1005"), None)
        assert match is not None
        assert match.buy_price == 48000.0
        assert match.sell_price == 52000.0
        assert match.quantity == 0.05
        assert match.realized_quantity == 0.025
        assert match.completeness == 0.5
        assert match.trade_type == TradeType.DIRECT


class TestDeletePosition:
    async def test_delete_removes_position(self, test_db: Database):
        pos = _make_position("2000")
        await test_db.save_position(pos)
        await test_db.delete_position("2000")
        active = await test_db.get_active_positions()
        assert not any(p.hp_id == "2000" for p in active)

    async def test_delete_nonexistent_does_not_raise(self, test_db: Database):
        # Should silently succeed
        await test_db.delete_position("nonexistent_id")


# ---------------------------------------------------------------------------
# Child position hierarchy
# ---------------------------------------------------------------------------


class TestPositionHierarchy:
    async def test_hierarchy_returns_parent_only_when_no_children(
        self, test_db: Database
    ):
        parent = _make_position("3000")
        await test_db.save_position(parent)
        hierarchy = await test_db.get_position_hierarchy("3000")
        assert len(hierarchy) == 1
        assert hierarchy[0].hp_id == "3000"

    async def test_hierarchy_returns_empty_for_unknown_id(self, test_db: Database):
        hierarchy = await test_db.get_position_hierarchy("unknown_id")
        assert hierarchy == []

    async def test_child_positions_excluded_from_active_positions(
        self, test_db: Database
    ):
        # Child hp_ids end with 'a' or 'b' and are filtered out by get_active_positions
        child_a = _make_position("4000a", status=PositionStatus.OPEN)
        child_b = _make_position("4000b", status=PositionStatus.OPEN)
        await test_db.save_position(child_a)
        await test_db.save_position(child_b)
        active = await test_db.get_active_positions()
        hp_ids = [p.hp_id for p in active]
        assert "4000a" not in hp_ids
        assert "4000b" not in hp_ids


# ---------------------------------------------------------------------------
# Order CRUD
# ---------------------------------------------------------------------------


class TestSaveAndRetrieveOrder:
    async def test_save_order_returns_order_id(self, test_db: Database):
        pos = _make_position("5000")
        await test_db.save_position(pos)
        order = _make_order(position_id="5000")
        result = await test_db.save_order(order)
        assert result == order.id

    async def test_saved_order_retrievable_by_position(self, test_db: Database):
        pos = _make_position("5001")
        await test_db.save_position(pos)
        order = _make_order(position_id="5001", price=49000.0, quantity=0.01)
        await test_db.save_order(order)
        orders = await test_db.get_position_orders("5001")
        assert len(orders) == 1
        assert orders[0].price == 49000.0
        assert orders[0].quantity == 0.01

    async def test_multiple_orders_per_position(self, test_db: Database):
        pos = _make_position("5002")
        await test_db.save_position(pos)
        for i in range(3):
            order = _make_order(position_id="5002", price=50000.0 + i * 100)
            await test_db.save_order(order)
        orders = await test_db.get_position_orders("5002")
        assert len(orders) == 3

    async def test_get_orders_for_unknown_position_returns_empty(
        self, test_db: Database
    ):
        orders = await test_db.get_position_orders("nonexistent")
        assert orders == []

    async def test_order_status_round_trip(self, test_db: Database):
        pos = _make_position("5003")
        await test_db.save_position(pos)
        order = _make_order(position_id="5003", status=OrderStatus.PARTIALLY_FILLED)
        await test_db.save_order(order)
        orders = await test_db.get_position_orders("5003")
        assert orders[0].status == OrderStatus.PARTIALLY_FILLED


# ---------------------------------------------------------------------------
# Inventory CRUD
# ---------------------------------------------------------------------------


class TestInventoryCrud:
    async def test_insert_and_fetch_item(self, test_db: Database):
        item = _make_inventory_item("btc1", "BTC", quantity=1.0)
        await test_db.insert_inventory_item(item)
        rows = await test_db.fetch_all_inventory_items()
        ids = [r["id"] for r in rows]
        assert "btc1" in ids

    async def test_fetched_item_fields(self, test_db: Database):
        item = _make_inventory_item("eth1", "ETH", buy_price=3000.0, quantity=2.0)
        await test_db.insert_inventory_item(item)
        rows = await test_db.fetch_all_inventory_items()
        match = next(r for r in rows if r["id"] == "eth1")
        assert match["coin"] == "ETH"
        assert match["buy_price"] == 3000.0
        assert match["quantity"] == 2.0

    async def test_available_and_locked_are_zero_on_fetch(self, test_db: Database):
        # DB only persists 'quantity'; runtime fields are always returned as 0
        item = _make_inventory_item(
            "sol1", "SOL", available_quantity=5.0, locked_quantity=1.0
        )
        await test_db.insert_inventory_item(item)
        rows = await test_db.fetch_all_inventory_items()
        match = next(r for r in rows if r["id"] == "sol1")
        assert match["available_quantity"] == 0.0
        assert match["locked_quantity"] == 0.0

    async def test_update_item(self, test_db: Database):
        item = _make_inventory_item("bnb1", "BNB", quantity=10.0)
        await test_db.insert_inventory_item(item)
        item.quantity = 8.0
        item.buy_price = 600.0
        await test_db.update_inventory_item(item)
        rows = await test_db.fetch_all_inventory_items()
        match = next(r for r in rows if r["id"] == "bnb1")
        assert match["quantity"] == 8.0
        assert match["buy_price"] == 600.0

    async def test_delete_item(self, test_db: Database):
        item = _make_inventory_item("del1", "ADA")
        await test_db.insert_inventory_item(item)
        await test_db.delete_inventory_item("del1")
        rows = await test_db.fetch_all_inventory_items()
        assert not any(r["id"] == "del1" for r in rows)

    async def test_fetch_empty_returns_empty_list(self, test_db: Database):
        rows = await test_db.fetch_all_inventory_items()
        assert rows == []

    async def test_multiple_items_all_returned(self, test_db: Database):
        for i in range(5):
            item = _make_inventory_item(f"multi_{i}", "BTC")
            await test_db.insert_inventory_item(item)
        rows = await test_db.fetch_all_inventory_items()
        assert len(rows) == 5


# ---------------------------------------------------------------------------
# close() is idempotent
# ---------------------------------------------------------------------------


class TestClose:
    async def test_close_twice_does_not_raise(self, test_db: Database):
        await test_db.close()
        await test_db.close()  # Second close should be a no-op
