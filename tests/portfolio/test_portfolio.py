"""
Unit tests for PortfolioManager (src/portfolio/portfolio.py).

Coverage targets:
- init_portfolio_source: DB path, CSV fallback, empty fallback, error fallback
- handle_account_position: proportional balance distribution across lots
- update_inventory / add_inventory_item / remove_inventory_item: in-memory mutations
- run_loop: event routing for ACCOUNT_POSITION / ALL_TICKERS / PORTFOLIO_INVENTORY
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

from src.domain.enums import EventName
from src.domain.inventory import InventoryItem
from src.domain.orders import AccountPosition, Balance, Event


# ---------------------------------------------------------------------------
# init_portfolio_source
# ---------------------------------------------------------------------------


class TestInitPortfolioSource:
    async def test_loads_from_db_when_items_present(self, make_portfolio):
        """When DB returns items, inventory is populated from them."""
        raw = [
            {
                "id": "abc",
                "coin": "BTC",
                "buy_price": 50000.0,
                "quantity": 0.5,
                "available_quantity": 0.5,
                "locked_quantity": 0.0,
                "source": "DB",
                "timestamp": time.time(),
                "notes": "",
            }
        ]
        pm = make_portfolio(db_items=raw, client_account={"balances": []})

        await pm.init_portfolio_source()

        assert len(pm.inventory) == 1
        assert pm.inventory[0].coin == "BTC"

    async def test_empty_db_starts_empty_when_no_csv(self, make_portfolio):
        """Empty DB with no CSV → empty inventory (no error)."""
        pm = make_portfolio(db_items=[])

        with patch.object(
            pm, "_try_load_inventory_csv", new=AsyncMock(return_value=False)
        ):
            await pm.init_portfolio_source()

        assert pm.inventory == []

    async def test_initialization_complete_event_is_set(self, make_portfolio):
        """initialization_complete event is always set after init, even on error."""
        pm = make_portfolio(db_items=[])
        pm.db.fetch_all_inventory_items = AsyncMock(
            side_effect=RuntimeError("DB offline")
        )

        with patch.object(
            pm, "_try_load_inventory_csv", new=AsyncMock(return_value=False)
        ):
            await pm.init_portfolio_source()

        assert pm.initialization_complete.is_set()
        assert pm.inventory == []

    async def test_inventory_manager_updated_when_loading_from_db(self, make_portfolio):
        """InventoryManager reflects DB-loaded items."""
        raw = [
            {
                "id": "x1",
                "coin": "ETH",
                "buy_price": 3000.0,
                "quantity": 2.0,
                "available_quantity": 2.0,
                "locked_quantity": 0.0,
                "source": "DB",
                "timestamp": time.time(),
                "notes": "",
            }
        ]
        pm = make_portfolio(db_items=raw, client_account={"balances": []})

        await pm.init_portfolio_source()

        summary = pm.inventory_manager.get_coin_summary()
        assert "ETH" in summary


# ---------------------------------------------------------------------------
# handle_account_position
# ---------------------------------------------------------------------------


class TestHandleAccountPosition:
    async def test_distributes_balance_proportionally_across_lots(
        self, make_portfolio, make_item
    ):
        """Two lots of the same coin get available/locked in proportion to their quantity."""
        pm = make_portfolio()
        lot1 = make_item("BTC", quantity=0.25)
        lot2 = make_item("BTC", quantity=0.75)
        pm.inventory = [lot1, lot2]

        balances = [Balance(coin="BTC", free=0.8, locked=0.2)]
        account_pos = AccountPosition(
            event_time=0, last_update_time=0, balances=balances
        )

        await pm.handle_account_position(account_pos)

        # lot1 is 25% → 0.25 * 0.8 = 0.2 available
        assert abs(lot1.available_quantity - 0.2) < 1e-9
        assert abs(lot1.locked_quantity - 0.05) < 1e-9
        # lot2 is 75%
        assert abs(lot2.available_quantity - 0.6) < 1e-9
        assert abs(lot2.locked_quantity - 0.15) < 1e-9

    async def test_coin_not_in_exchange_is_left_unchanged(
        self, make_portfolio, make_item
    ):
        """Inventory coin absent from exchange balances is LEFT UNCHANGED.

        AccountPosition may only contain coins that changed, so missing coins
        should not be zeroed out.
        """
        pm = make_portfolio()
        item = make_item("DOGE", quantity=1000.0)
        item.available_quantity = 500.0
        pm.inventory = [item]

        account_pos = AccountPosition(event_time=0, last_update_time=0, balances=[])

        await pm.handle_account_position(account_pos)

        assert item.available_quantity == 500.0

    async def test_empty_inventory_is_handled(self, make_portfolio):
        """No error when inventory is empty."""
        pm = make_portfolio()
        pm.inventory = []

        balances = [Balance(coin="BTC", free=1.0, locked=0.0)]
        account_pos = AccountPosition(
            event_time=0, last_update_time=0, balances=balances
        )

        await pm.handle_account_position(account_pos)  # should not raise


# ---------------------------------------------------------------------------
# update_inventory / add / remove
# ---------------------------------------------------------------------------


class TestInventoryMutations:
    async def test_update_inventory_replaces_list(self, make_portfolio, make_item):
        pm = make_portfolio()
        pm.inventory = [make_item("BTC")]
        new_items = [make_item("ETH"), make_item("SOL")]

        await pm.update_inventory(new_items)

        assert len(pm.inventory) == 2
        assert pm.inventory[0].coin == "ETH"

    def test_add_inventory_item_appends(self, make_portfolio, make_item):
        pm = make_portfolio()
        pm.inventory = []

        item = make_item("ADA")
        pm.add_inventory_item(item)

        assert len(pm.inventory) == 1
        assert pm.inventory[0].coin == "ADA"

    def test_remove_inventory_item_by_id(self, make_portfolio, make_item):
        pm = make_portfolio()
        item = InventoryItem(
            id="remove-me",
            coin="BTC",
            buy_price=50000.0,
            quantity=1.0,
            available_quantity=1.0,
            locked_quantity=0.0,
            source="TEST",
            timestamp=time.time(),
        )
        pm.inventory = [item, make_item("ETH")]

        pm.remove_inventory_item("remove-me")

        assert len(pm.inventory) == 1
        assert pm.inventory[0].coin == "ETH"

    def test_remove_nonexistent_id_is_safe(self, make_portfolio, make_item):
        pm = make_portfolio()
        pm.inventory = [make_item("BTC")]

        pm.remove_inventory_item("does-not-exist")

        assert len(pm.inventory) == 1  # unchanged


# ---------------------------------------------------------------------------
# run_loop — event routing
# ---------------------------------------------------------------------------


class TestRunLoop:
    async def test_routes_account_position_event(self, make_portfolio):
        """ACCOUNT_POSITION event triggers handle_account_position."""
        pm = make_portfolio()
        pm.handle_account_position = AsyncMock()

        account_pos = AccountPosition(event_time=0, last_update_time=0, balances=[])
        pm.worker_queue.put_nowait(
            Event(name=EventName.ACCOUNT_POSITION, content=account_pos)
        )

        task = asyncio.create_task(pm.run_loop())
        await asyncio.sleep(0.05)
        pm.stop_event.set()
        await asyncio.wait_for(task, timeout=1.0)

        pm.handle_account_position.assert_awaited_once_with(account_pos)

    async def test_routes_portfolio_inventory_event(self, make_portfolio, make_item):
        """PORTFOLIO_INVENTORY event triggers update_inventory."""
        pm = make_portfolio()
        pm.update_inventory = AsyncMock()

        items = [make_item("BTC")]
        pm.worker_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=items)
        )

        task = asyncio.create_task(pm.run_loop())
        await asyncio.sleep(0.05)
        pm.stop_event.set()
        await asyncio.wait_for(task, timeout=1.0)

        pm.update_inventory.assert_awaited_once_with(items)

    async def test_stops_on_stop_event(self, make_portfolio):
        """run_loop exits when stop_event is set and queue is empty."""
        pm = make_portfolio()

        task = asyncio.create_task(pm.run_loop())
        await asyncio.sleep(0.05)
        pm.stop_event.set()

        await asyncio.wait_for(task, timeout=1.0)
