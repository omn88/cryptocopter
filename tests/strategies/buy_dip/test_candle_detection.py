"""Unit tests for Buy Dip candle detection components.

Tests cover:
- CandleBuffer: Ring buffer storage and retrieval (3 tests)
- ATR: Wilder's smoothing calculation (4 tests)
- RisingCandleDetector: Pattern detection (4 tests)
- HighWatermarkDetector: Top tracking and confirmation (5 tests)
- BudgetManager: Percentage-based sizing (6 tests)
- Integration: Complete pipeline (1 test)
- Configuration: Validation (1 test)

Total: 24 unit tests
"""

import pytest

# Component imports - modules to be implemented via TDD
from src.strategies.buy_dip.candle_buffer import CandleBuffer
from src.strategies.buy_dip.atr import ATR
from src.strategies.buy_dip.rising_detector import RisingCandleDetector
from src.strategies.buy_dip.hwm_detector import HighWatermarkDetector
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


class TestATR:
    """Test Average True Range calculation with Wilder's smoothing."""

    def test_calculates_true_range_correctly(self, sample_candle):
        """Test true range calculation: max(H-L, |H-PC|, |L-PC|)."""
        atr = ATR(period=14)

        # Add 14 candles with known TR values to test calculation
        # First candle: TR = high - low = 105 - 95 = 10
        atr.add_candle(sample_candle(high=105, low=95, close=100, timestamp=1000))

        # Second candle: TR = max(110-98=12, |110-100|=10, |98-100|=2) = 12
        atr.add_candle(sample_candle(high=110, low=98, close=108, timestamp=2000))

        # Add 12 more candles with TR=10 each
        for i in range(12):
            atr.add_candle(
                sample_candle(high=118, low=108, close=115, timestamp=3000 + i * 1000)
            )

        # After 14 candles: ATR = average of TRs = (10 + 12 + 10*12) / 14 = 142 / 14 ≈ 10.14
        result = atr.get_atr()
        assert result is not None
        assert abs(result - 10.14) < 0.01

    def test_wilders_smoothing_formula(self, sample_candle):
        """Test Wilder's smoothing: ATR = ((prior_ATR * 13) + current_TR) / 14."""
        atr = ATR(period=14)

        # Add 14 candles with TR=10 each (high-low=10)
        for i in range(14):
            atr.add_candle(
                sample_candle(high=110, low=100, close=105, timestamp=1000 * i)
            )

        assert atr.get_atr() == pytest.approx(10.0, rel=0.01)

        # Add one more with TR=20
        atr.add_candle(sample_candle(high=120, low=100, close=110, timestamp=15000))

        # New ATR = ((10 * 13) + 20) / 14 = 150 / 14 ≈ 10.714
        assert atr.get_atr() == pytest.approx(10.714, rel=0.01)

    def test_insufficient_data_returns_none(self, sample_candle):
        """Test that ATR returns None when insufficient candles (< period)."""
        atr = ATR(period=14)

        # No candles: should return None
        assert atr.get_atr() is None

        # Add only 5 candles (need 14 for valid ATR)
        for i in range(5):
            atr.add_candle(sample_candle(timestamp=1000 * i))

        # Still insufficient data
        assert atr.get_atr() is None

        # Add 8 more candles (total 13, still not enough)
        for i in range(8):
            atr.add_candle(sample_candle(timestamp=6000 + 1000 * i))

        assert atr.get_atr() is None

        # Add 14th candle - NOW ATR should be available
        atr.add_candle(sample_candle(timestamp=14000))
        assert atr.get_atr() is not None

    def test_btc_realistic_values(self, sample_candle):
        """Test ATR with realistic BTC price movements."""
        atr = ATR(period=14)

        # BTC at ~$67,000 with typical volatility
        btc_candles = [
            sample_candle(high=67500, low=66800, close=67200, timestamp=i * 1000)
            for i in range(14)
        ]

        for candle in btc_candles:
            atr.add_candle(candle)

        result = atr.get_atr()
        assert result is not None
        # TR = 67500 - 66800 = 700, so ATR should be around 700
        assert 650 < result < 750


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


class TestHighWatermarkDetector:
    """Test high watermark tracking and top confirmation."""

    def test_tracks_high_watermark(self, sample_candle):
        """Test that HWM tracks the highest high seen."""
        detector = HighWatermarkDetector(
            atr_multiplier=2.0,
            min_pullback_pct=0.5,
        )

        # Provide mock ATR
        detector.update_atr(500.0)

        candles = [
            sample_candle(high=67000, timestamp=1000),
            sample_candle(high=67500, timestamp=2000),
            sample_candle(high=67200, timestamp=3000),  # Pullback
        ]

        for candle in candles:
            detector.add_candle(candle)

        assert detector.get_hwm() == 67500

    def test_confirms_top_on_threshold_pullback(self, sample_candle):
        """Test that top is confirmed when pullback exceeds threshold."""
        detector = HighWatermarkDetector(
            atr_multiplier=2.0,
            min_pullback_pct=0.5,
        )

        # ATR = 500, threshold = 2.0 * 500 = 1000
        detector.update_atr(500.0)

        # HWM at 67500
        detector.add_candle(sample_candle(high=67500, timestamp=1000))

        # Pullback to 66400 (1100 below HWM, exceeds 1000 threshold)
        detector.add_candle(sample_candle(high=66400, low=66300, timestamp=2000))

        assert detector.is_top_confirmed() is True
        assert detector.get_confirmed_top() == 67500

    def test_invalidates_top_on_new_high(self, sample_candle):
        """Test that confirmed top is invalidated by a new higher high."""
        detector = HighWatermarkDetector(
            atr_multiplier=2.0,
            min_pullback_pct=0.5,
        )

        detector.update_atr(500.0)

        # First top at 67500
        detector.add_candle(sample_candle(high=67500, timestamp=1000))
        detector.add_candle(sample_candle(high=66400, timestamp=2000))  # Confirm

        assert detector.is_top_confirmed() is True
        assert detector.get_confirmed_top() == 67500

        # New high at 68000 (invalidates previous top)
        detector.add_candle(sample_candle(high=68000, timestamp=3000))

        assert detector.is_top_confirmed() is False
        assert detector.get_hwm() == 68000

    def test_atr_adaptive_threshold(self, sample_candle):
        """Test that threshold adapts to ATR changes."""
        # Low volatility: ATR = 200, threshold = 400
        detector = HighWatermarkDetector(atr_multiplier=2.0, min_pullback_pct=0.5)
        detector.update_atr(200.0)
        detector.add_candle(sample_candle(high=67500, timestamp=1000))
        detector.add_candle(sample_candle(high=67050, timestamp=2000))  # 450 pullback
        assert detector.is_top_confirmed() is True  # 450 > 400

        # High volatility: ATR = 800, threshold = 1600
        detector_2 = HighWatermarkDetector(atr_multiplier=2.0, min_pullback_pct=0.5)
        detector_2.update_atr(800.0)
        detector_2.add_candle(sample_candle(high=67500, timestamp=1000))
        detector_2.add_candle(sample_candle(high=67050, timestamp=2000))  # 450 pullback
        assert detector_2.is_top_confirmed() is False  # 450 < 1600

    def test_tracks_bottom_during_pullback(self, sample_candle):
        """Test that detector tracks the lowest point during pullback."""
        detector = HighWatermarkDetector(
            atr_multiplier=2.0,
            min_pullback_pct=0.5,
        )

        detector.update_atr(500.0)
        detector.add_candle(sample_candle(high=67500, timestamp=1000))

        # Pullback sequence
        detector.add_candle(sample_candle(high=67200, low=67100, timestamp=2000))
        detector.add_candle(
            sample_candle(high=67000, low=66800, timestamp=3000)
        )  # Lowest
        detector.add_candle(sample_candle(high=67100, low=66900, timestamp=4000))

        # Should track 66800 as the bottom
        assert detector.get_bottom() == 66800


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


class TestCandleDetectionPipeline:
    """Test complete pipeline: Buffer → ATR → Rising → HWM."""

    def test_complete_detection_pipeline(self, sample_candle):
        """Test full pipeline from candle ingestion to top detection."""
        # Setup components
        buffer = CandleBuffer(maxlen=100)
        atr = ATR(period=14)
        rising = RisingCandleDetector(min_consecutive=3, min_total_gain_pct=0.25)
        hwm = HighWatermarkDetector(atr_multiplier=2.0, min_pullback_pct=0.5)

        # Add 14 candles to initialize ATR (around 67000)
        for i in range(14):
            candle = sample_candle(
                high=67000 + (i * 10),
                low=66800 + (i * 10),
                close=66900 + (i * 10),
                timestamp=1000 * i,
            )
            buffer.add(candle)
            atr.add_candle(candle)

        atr_value = atr.get_atr()
        assert atr_value is not None
        hwm.update_atr(atr_value)

        # Add 3 rising candles
        for i in range(3):
            candle = sample_candle(
                high=67140 + (i * 50),
                close=67120 + (i * 50),
                timestamp=14000 + (1000 * i),
            )
            buffer.add(candle)
            rising.add_candle(candle)
            hwm.add_candle(candle)

        # Should detect rising pattern
        assert rising.is_rising() is True
        assert hwm.get_hwm() == 67240  # Last high

        # Add pullback candle (large enough to confirm top)
        pullback_candle = sample_candle(
            high=66000,
            low=65900,
            close=65950,
            timestamp=17000,
        )
        buffer.add(pullback_candle)
        hwm.add_candle(pullback_candle)

        # Should confirm top at 67240
        assert hwm.is_top_confirmed() is True
        assert hwm.get_confirmed_top() == 67240


class TestConfiguration:
    """Test configuration validation."""

    def test_rejects_invalid_configuration(self):
        """Test that invalid configurations are rejected."""
        # Invalid: negative percentages
        with pytest.raises(ValueError):
            BuyDipConfig(
                atr_period=-14,
                order_size_percentage=2.0,
                dca_distances_pct=[1.618, 2.718, 3.142],
            )

        # Invalid: empty DCA distances
        with pytest.raises(ValueError):
            BuyDipConfig(
                atr_period=14,
                order_size_percentage=2.0,
                dca_distances_pct=[],
            )

        # Invalid: order size too large (>100%)
        with pytest.raises(ValueError):
            BuyDipConfig(
                atr_period=14,
                order_size_percentage=150.0,
                dca_distances_pct=[1.618, 2.718, 3.142],
            )
