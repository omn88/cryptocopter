"""Unit tests for Buy Dip candle detection components.

Tests cover:
- CandleBuffer: Ring buffer storage and retrieval (3 tests)
- RisingCandleDetector: Pattern detection (4 tests)
- BudgetManager: Percentage-based sizing (6 tests)
- Configuration: Validation (1 test)

Note: ATR and HighWatermarkDetector tests removed - those components
are no longer used in the active strategy (moved to backtester/).

Total: 14 unit tests
"""

import pytest

from src.strategies.buy_dip.candle_buffer import CandleBuffer
from src.strategies.buy_dip.rising_detector import RisingCandleDetector
from src.strategies.buy_dip.budget_manager import BudgetManager
from src.strategies.buy_dip.config import BuyDipConfig


class TestCandleBuffer:
    """Test the ring buffer for candle storage."""

    def test_stores_candles_in_order(self, sample_candle):
        """Test that candles are stored in chronological order."""
        buffer = CandleBuffer(maxlen=100)

        candle1 = sample_candle(high=100, timestamp=1000)
        candle2 = sample_candle(high=101, timestamp=2000)
        candle3 = sample_candle(high=102, timestamp=3000)

        buffer.add(candle1)
        buffer.add(candle2)
        buffer.add(candle3)

        candles = buffer.get_last_n(3)
        assert len(candles) == 3
        assert candles[0]["high"] == 100
        assert candles[1]["high"] == 101
        assert candles[2]["high"] == 102

    def test_ring_buffer_evicts_oldest(self, sample_candle):
        """Test that oldest candles are evicted when maxlen is reached."""
        buffer = CandleBuffer(maxlen=3)

        for i in range(5):
            buffer.add(sample_candle(close=100 + i, timestamp=1000 * i))

        candles = buffer.get_all()
        assert len(candles) == 3
        assert candles[0]["close"] == 102
        assert candles[1]["close"] == 103
        assert candles[2]["close"] == 104

    def test_get_last_n_returns_correct_count(self, sample_candle):
        """Test getting the last N candles."""
        buffer = CandleBuffer(maxlen=100)

        for i in range(10):
            buffer.add(sample_candle(close=100 + i, timestamp=1000 * i))

        last_3 = buffer.get_last_n(3)
        assert len(last_3) == 3
        assert last_3[0]["close"] == 107
        assert last_3[1]["close"] == 108
        assert last_3[2]["close"] == 109

        last_20 = buffer.get_last_n(20)
        assert len(last_20) == 10


class TestRisingCandleDetector:
    """Test detection of rising candle patterns."""

    def test_detects_consecutive_higher_highs(self, sample_candle):
        """Test detection with 3 consecutive candles with higher highs."""
        detector = RisingCandleDetector(
            min_consecutive=3,
            min_total_gain_pct=0.25,
        )

        candles = [
            sample_candle(high=100, close=99, timestamp=1000),
            sample_candle(high=102, close=101, timestamp=2000),
            sample_candle(high=105, close=104, timestamp=3000),
        ]

        for candle in candles:
            detector.add_candle(candle)

        assert detector.is_rising() is True

    def test_detects_total_gain_threshold(self, sample_candle):
        """Test detection based on total gain percentage (0.25% threshold)."""
        detector = RisingCandleDetector(
            min_consecutive=3,
            min_total_gain_pct=0.25,
        )

        # 3 candles: 67000 → 67100 → 67200 (0.3% total gain)
        candles = [
            sample_candle(high=67000, close=66950, timestamp=1000),
            sample_candle(high=67100, close=67050, timestamp=2000),
            sample_candle(high=67200, close=67150, timestamp=3000),
        ]

        for candle in candles:
            detector.add_candle(candle)

        # Total gain = (67200 - 67000) / 67000 = 0.298% > 0.25%
        assert detector.is_rising() is True

    def test_uses_highs_not_closes(self, sample_candle):
        """Test that detector uses highs, not closes."""
        detector = RisingCandleDetector(
            min_consecutive=3,
            min_total_gain_pct=0.25,
        )

        # Highs are rising, but closes are falling
        candles = [
            sample_candle(high=100, close=98, timestamp=1000),
            sample_candle(high=102, close=97, timestamp=2000),
            sample_candle(high=105, close=96, timestamp=3000),
        ]

        for candle in candles:
            detector.add_candle(candle)

        # Should still detect as rising (highs are increasing)
        assert detector.is_rising() is True

    def test_or_logic_either_condition_sufficient(self, sample_candle):
        """Test that EITHER consecutive highs OR total gain is sufficient."""
        # Scenario 1: Consecutive highs but small total gain
        detector_1 = RisingCandleDetector(min_consecutive=3, min_total_gain_pct=0.25)
        candles_1 = [
            sample_candle(high=100, close=99, timestamp=1000),
            sample_candle(high=100.05, close=99.5, timestamp=2000),
            sample_candle(high=100.10, close=100, timestamp=3000),
        ]
        for candle in candles_1:
            detector_1.add_candle(candle)
        # Only 0.1% gain but 3 consecutive highs
        assert detector_1.is_rising() is True

        # Scenario 2: Large gain but not consecutive
        detector_2 = RisingCandleDetector(min_consecutive=3, min_total_gain_pct=0.25)
        candles_2 = [
            sample_candle(high=100, close=99, timestamp=1000),
            sample_candle(high=99.5, close=99, timestamp=2000),  # Dip
            sample_candle(high=102, close=101, timestamp=3000),  # Large jump
        ]
        for candle in candles_2:
            detector_2.add_candle(candle)
        # 2% gain but not 3 consecutive
        assert detector_2.is_rising() is True


class TestBudgetManager:
    """Test percentage-based budget management."""

    def test_calculates_order_size_percentage(self):
        """Test order size calculation based on percentage of available budget."""
        manager = BudgetManager(
            initial_budget=10000.0,
            order_size_percentage=2.0,  # 2% per order
            min_order_size=10.0,
        )

        order_size = manager.calculate_order_size()
        assert order_size == pytest.approx(200.0)  # 2% of 10000

    def test_locks_and_releases_funds(self):
        """Test locking and releasing funds for orders."""
        manager = BudgetManager(
            initial_budget=10000.0,
            order_size_percentage=2.0,
            min_order_size=10.0,
        )

        # Lock funds for order
        manager.lock_funds(200.0)
        assert manager.get_available_budget() == pytest.approx(9800.0)
        assert manager.get_locked_budget() == pytest.approx(200.0)

        # Release funds (no profit)
        manager.release_funds(200.0, profit=0.0)
        assert manager.get_available_budget() == pytest.approx(10000.0)
        assert manager.get_locked_budget() == pytest.approx(0.0)

    def test_adds_budget_dynamically(self):
        """Test adding budget during strategy execution."""
        manager = BudgetManager(
            initial_budget=10000.0,
            order_size_percentage=2.0,
            min_order_size=10.0,
        )

        manager.add_budget(5000.0)
        assert manager.get_available_budget() == pytest.approx(15000.0)

        # New order size should be 2% of 15000 = 300
        assert manager.calculate_order_size() == pytest.approx(300.0)

    def test_withdraws_budget(self):
        """Test withdrawing budget from strategy."""
        manager = BudgetManager(
            initial_budget=10000.0,
            order_size_percentage=2.0,
            min_order_size=10.0,
        )

        manager.withdraw_budget(3000.0)
        assert manager.get_available_budget() == pytest.approx(7000.0)

        # New order size should be 2% of 7000 = 140
        assert manager.calculate_order_size() == pytest.approx(140.0)

    def test_insufficient_budget_returns_none(self):
        """Test that insufficient budget returns None for order size."""
        manager = BudgetManager(
            initial_budget=100.0,
            order_size_percentage=2.0,
            min_order_size=50.0,  # 2% = 2.0, which is < 50
        )

        order_size = manager.calculate_order_size()
        assert order_size is None  # Can't place order (2.0 < 50.0)

    def test_profit_returned_to_available_budget(self):
        """Test that profit from filled orders is returned to available budget."""
        manager = BudgetManager(
            initial_budget=10000.0,
            order_size_percentage=2.0,
            min_order_size=10.0,
        )

        # Lock 200 for order
        manager.lock_funds(200.0)
        assert manager.get_available_budget() == pytest.approx(9800.0)

        # Release with 50 profit (25% gain)
        manager.release_funds(200.0, profit=50.0)
        assert manager.get_available_budget() == pytest.approx(
            10050.0
        )  # 9800 + 200 + 50
        assert manager.get_locked_budget() == pytest.approx(0.0)


class TestConfiguration:
    """Test configuration validation."""

    def test_rejects_invalid_configuration(self):
        """Test that invalid configurations are rejected."""
        # Invalid: empty DCA distances
        with pytest.raises(ValueError):
            BuyDipConfig(
                order_size_percentage=2.0,
                dca_distances_pct=[],
            )

        # Invalid: order size too large (>100%)
        with pytest.raises(ValueError):
            BuyDipConfig(
                order_size_percentage=150.0,
                dca_distances_pct=[1.618, 2.718, 3.142],
            )
