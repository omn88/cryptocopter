"""Unit tests for src.strategies.buy_dip.config.BuyDipConfig."""

import pytest
from src.strategies.buy_dip.config import BuyDipConfig


# ---------------------------------------------------------------------------
# Default construction
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_dca_distances(self):
        cfg = BuyDipConfig()
        assert cfg.dca_distances_pct == [1.618, 2.718, 3.142]

    def test_default_order_size_percentage(self):
        assert BuyDipConfig().order_size_percentage == 2.0

    def test_custom_valid_config(self):
        cfg = BuyDipConfig(
            order_size_percentage=5.0,
            dca_distances_pct=[1.0, 2.0, 3.0],
            min_consecutive_rising=2,
            min_total_gain_pct=0.5,
            sell_placement_distance_pct=1.0,
            sell_cancellation_distance_pct=3.0,
        )
        assert cfg.order_size_percentage == 5.0
        assert cfg.dca_distances_pct == [1.0, 2.0, 3.0]
        assert cfg.min_consecutive_rising == 2


# ---------------------------------------------------------------------------
# order_size_percentage validation
# ---------------------------------------------------------------------------


class TestOrderSizePercentage:
    def test_zero_raises(self):
        with pytest.raises(ValueError, match="order_size_percentage"):
            BuyDipConfig(order_size_percentage=0)

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="order_size_percentage"):
            BuyDipConfig(order_size_percentage=-1.0)

    def test_exactly_100_is_valid(self):
        cfg = BuyDipConfig(order_size_percentage=100.0)
        assert cfg.order_size_percentage == 100.0

    def test_above_100_raises(self):
        with pytest.raises(ValueError, match="order_size_percentage"):
            BuyDipConfig(order_size_percentage=100.1)


# ---------------------------------------------------------------------------
# dca_distances_pct validation
# ---------------------------------------------------------------------------


class TestDcaDistancesPct:
    def test_empty_list_raises(self):
        with pytest.raises(ValueError, match="dca_distances_pct"):
            BuyDipConfig(dca_distances_pct=[])

    def test_zero_distance_raises(self):
        with pytest.raises(ValueError, match=r"dca_distances_pct\[0\]"):
            BuyDipConfig(dca_distances_pct=[0.0, 1.0])

    def test_negative_distance_raises(self):
        with pytest.raises(ValueError, match=r"dca_distances_pct\[0\]"):
            BuyDipConfig(dca_distances_pct=[-1.0])

    def test_distance_100_or_above_raises(self):
        with pytest.raises(ValueError, match=r"dca_distances_pct\[0\]"):
            BuyDipConfig(dca_distances_pct=[100.0])

    def test_single_valid_distance(self):
        cfg = BuyDipConfig(dca_distances_pct=[5.0])
        assert cfg.dca_distances_pct == [5.0]

    def test_unsorted_input_is_sorted(self):
        cfg = BuyDipConfig(dca_distances_pct=[3.0, 1.0, 2.0])
        assert cfg.dca_distances_pct == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# sell threshold validation
# ---------------------------------------------------------------------------


class TestSellThresholds:
    def test_placement_zero_raises(self):
        with pytest.raises(ValueError, match="sell_placement_distance_pct"):
            BuyDipConfig(
                sell_placement_distance_pct=0.0,
                sell_cancellation_distance_pct=4.0,
            )

    def test_cancellation_zero_raises(self):
        with pytest.raises(ValueError, match="sell_cancellation_distance_pct"):
            BuyDipConfig(
                sell_placement_distance_pct=2.0,
                sell_cancellation_distance_pct=0.0,
            )

    def test_placement_equal_cancellation_raises(self):
        with pytest.raises(ValueError, match="sell_placement_distance_pct"):
            BuyDipConfig(
                sell_placement_distance_pct=4.0,
                sell_cancellation_distance_pct=4.0,
            )

    def test_placement_greater_than_cancellation_raises(self):
        with pytest.raises(ValueError, match="sell_placement_distance_pct"):
            BuyDipConfig(
                sell_placement_distance_pct=5.0,
                sell_cancellation_distance_pct=4.0,
            )

    def test_valid_thresholds(self):
        cfg = BuyDipConfig(
            sell_placement_distance_pct=1.0,
            sell_cancellation_distance_pct=3.0,
        )
        assert cfg.sell_placement_distance_pct == 1.0
        assert cfg.sell_cancellation_distance_pct == 3.0
