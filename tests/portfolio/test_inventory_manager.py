"""Unit tests for src.portfolio.inventory_manager.InventoryManager."""

import pytest
from src.common.identifiers import InventoryItem
from src.portfolio.inventory_manager import InventoryManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_item(
    id: str,
    coin: str,
    buy_price: float = 100.0,
    quantity: float = 1.0,
    available_quantity: float = 1.0,
    locked_quantity: float = 0.0,
) -> InventoryItem:
    return InventoryItem(
        id=id,
        coin=coin,
        buy_price=buy_price,
        quantity=quantity,
        available_quantity=available_quantity,
        locked_quantity=locked_quantity,
    )


# ---------------------------------------------------------------------------
# CRUD: add / remove / get / update
# ---------------------------------------------------------------------------


class TestAddAndLen:
    def test_empty_on_init(self):
        mgr = InventoryManager()
        assert len(mgr) == 0

    def test_add_increases_length(self):
        mgr = InventoryManager()
        mgr.add_item(make_item("1", "ETH"))
        assert len(mgr) == 1

    def test_init_with_list(self):
        items = [make_item("1", "BTC"), make_item("2", "ETH")]
        mgr = InventoryManager(inventory=items)
        assert len(mgr) == 2


class TestRemoveItem:
    def test_remove_existing_returns_true(self):
        mgr = InventoryManager()
        mgr.add_item(make_item("1", "ETH"))
        assert mgr.remove_item("1") is True
        assert len(mgr) == 0

    def test_remove_non_existing_returns_false(self):
        mgr = InventoryManager()
        mgr.add_item(make_item("1", "ETH"))
        assert mgr.remove_item("99") is False
        assert len(mgr) == 1


class TestGetItem:
    def test_get_existing_item(self):
        item = make_item("1", "ETH")
        mgr = InventoryManager(inventory=[item])
        assert mgr.get_item("1") is item

    def test_get_missing_returns_none(self):
        mgr = InventoryManager()
        assert mgr.get_item("99") is None


class TestUpdateItem:
    def test_update_existing_returns_true(self):
        mgr = InventoryManager(inventory=[make_item("1", "ETH", buy_price=100.0)])
        updated = make_item("1", "ETH", buy_price=200.0)
        assert mgr.update_item(updated) is True
        assert mgr.get_item("1").buy_price == 200.0

    def test_update_non_existing_returns_false(self):
        mgr = InventoryManager()
        assert mgr.update_item(make_item("99", "ETH")) is False


# ---------------------------------------------------------------------------
# Filter / aggregation per coin
# ---------------------------------------------------------------------------


class TestGetItemsByCoin:
    def test_filters_by_coin(self):
        mgr = InventoryManager(
            inventory=[
                make_item("1", "ETH"),
                make_item("2", "BTC"),
                make_item("3", "ETH"),
            ]
        )
        assert len(mgr.get_items_by_coin("ETH")) == 2

    def test_unknown_coin_returns_empty(self):
        mgr = InventoryManager()
        assert mgr.get_items_by_coin("SOL") == []


class TestQuantityAggregates:
    def test_total_quantity_sums_two_lots(self):
        mgr = InventoryManager(
            inventory=[
                make_item("1", "ETH", quantity=1.0),
                make_item("2", "ETH", quantity=2.5),
            ]
        )
        assert mgr.get_total_quantity_by_coin("ETH") == pytest.approx(3.5)

    def test_available_quantity(self):
        mgr = InventoryManager(
            inventory=[
                make_item("1", "ETH", available_quantity=0.5),
                make_item("2", "ETH", available_quantity=1.5),
            ]
        )
        assert mgr.get_available_quantity_by_coin("ETH") == pytest.approx(2.0)

    def test_locked_quantity(self):
        mgr = InventoryManager(
            inventory=[
                make_item("1", "ETH", locked_quantity=0.3),
                make_item("2", "ETH", locked_quantity=0.7),
            ]
        )
        assert mgr.get_locked_quantity_by_coin("ETH") == pytest.approx(1.0)

    def test_total_value(self):
        mgr = InventoryManager(
            inventory=[
                make_item("1", "ETH", buy_price=200.0, quantity=2.0),
                make_item("2", "ETH", buy_price=100.0, quantity=1.0),
            ]
        )
        assert mgr.get_total_value_by_coin("ETH") == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Weighted average price
# ---------------------------------------------------------------------------


class TestWeightedAveragePrice:
    def test_single_item(self):
        mgr = InventoryManager(inventory=[make_item("1", "ETH", buy_price=150.0, quantity=2.0)])
        assert mgr.get_weighted_average_price("ETH") == pytest.approx(150.0)

    def test_two_lots_different_prices(self):
        # (200*2 + 100*1) / 3 = 500/3 ≈ 166.67
        mgr = InventoryManager(
            inventory=[
                make_item("1", "ETH", buy_price=200.0, quantity=2.0),
                make_item("2", "ETH", buy_price=100.0, quantity=1.0),
            ]
        )
        assert mgr.get_weighted_average_price("ETH") == pytest.approx(500.0 / 3.0)

    def test_empty_coin_returns_zero(self):
        mgr = InventoryManager()
        assert mgr.get_weighted_average_price("ETH") == 0.0

    def test_zero_total_quantity_returns_zero(self):
        mgr = InventoryManager(
            inventory=[make_item("1", "ETH", buy_price=100.0, quantity=0.0)]
        )
        assert mgr.get_weighted_average_price("ETH") == 0.0


# ---------------------------------------------------------------------------
# get_coin_summary
# ---------------------------------------------------------------------------


class TestGetCoinSummary:
    def test_summary_contains_all_coins(self):
        mgr = InventoryManager(
            inventory=[make_item("1", "ETH"), make_item("2", "BTC")]
        )
        summary = mgr.get_coin_summary()
        assert set(summary.keys()) == {"ETH", "BTC"}

    def test_summary_keys(self):
        mgr = InventoryManager(inventory=[make_item("1", "ETH")])
        eth = mgr.get_coin_summary()["ETH"]
        assert set(eth.keys()) == {
            "total_quantity",
            "available_quantity",
            "locked_quantity",
            "total_value",
            "weighted_avg_price",
        }


# ---------------------------------------------------------------------------
# get_total_portfolio_value
# ---------------------------------------------------------------------------


class TestGetTotalPortfolioValue:
    def test_empty_returns_zero(self):
        assert InventoryManager().get_total_portfolio_value() == 0.0

    def test_multi_item_sum(self):
        mgr = InventoryManager(
            inventory=[
                make_item("1", "ETH", buy_price=200.0, quantity=1.0),
                make_item("2", "BTC", buy_price=30000.0, quantity=0.1),
            ]
        )
        assert mgr.get_total_portfolio_value() == pytest.approx(3200.0)


# ---------------------------------------------------------------------------
# __getitem__
# ---------------------------------------------------------------------------


class TestGetItem_DunderGetitem:
    def test_known_coin_returns_filled_dict(self):
        mgr = InventoryManager(inventory=[make_item("1", "ETH", buy_price=100.0, quantity=2.0)])
        result = mgr["ETH"]
        assert result["total_quantity"] == pytest.approx(2.0)

    def test_unknown_coin_returns_zero_dict(self):
        mgr = InventoryManager()
        result = mgr["UNKNOWN"]
        assert result == {
            "total_quantity": 0.0,
            "available_quantity": 0.0,
            "locked_quantity": 0.0,
            "total_value": 0.0,
            "weighted_avg_price": 0.0,
        }


# ---------------------------------------------------------------------------
# clear / __iter__
# ---------------------------------------------------------------------------


class TestClearAndIter:
    def test_clear_empties_inventory(self):
        mgr = InventoryManager(inventory=[make_item("1", "ETH")])
        mgr.clear()
        assert len(mgr) == 0

    def test_iter_yields_all_items(self):
        items = [make_item("1", "ETH"), make_item("2", "BTC")]
        mgr = InventoryManager(inventory=items)
        assert list(mgr) == items
