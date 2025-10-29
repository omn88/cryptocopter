"""Tests for TopDetector - Local top identification.

Tests cover:
- Simple top detection
- Multiple tops detection
- Time-based window expiry
- Edge cases (no prices, zero prices, etc.)
"""

import pytest
from datetime import datetime, timedelta
from src.strategies.buy_dip.top_detector import TopDetector


class TestTopDetectorBasic:
    """Basic top detection functionality."""

    def test_simple_local_top_detection(self):
        """Test detection of a simple local top."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # Price rises
        assert detector.update(1000, base_time) is None
        assert detector.update(1050, base_time + timedelta(minutes=1)) is None
        assert detector.update(1100, base_time + timedelta(minutes=2)) is None

        # Price drops 1.1% - should detect top at 1100
        result = detector.update(1088, base_time + timedelta(minutes=3))
        assert result == 1100

    def test_insufficient_drop_no_detection(self):
        """Test that insufficient drop doesn't trigger detection."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # Price rises
        detector.update(1000, base_time)
        detector.update(1100, base_time + timedelta(minutes=1))

        # Price drops only 0.5% - should NOT detect top
        result = detector.update(1094.5, base_time + timedelta(minutes=2))
        assert result is None

    def test_no_duplicate_top_detection(self):
        """Test that same top isn't detected multiple times."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # Rise to 1100
        detector.update(1000, base_time)
        detector.update(1100, base_time + timedelta(minutes=1))

        # Drop 1.5% - detects top
        result1 = detector.update(1084, base_time + timedelta(minutes=2))
        assert result1 == 1100

        # Continue dropping - should NOT detect same top again
        result2 = detector.update(1080, base_time + timedelta(minutes=3))
        assert result2 is None

        result3 = detector.update(1075, base_time + timedelta(minutes=4))
        assert result3 is None


class TestTopDetectorMultipleTops:
    """Tests for detecting multiple tops over time."""

    def test_detects_new_higher_top(self):
        """Test detection of a new, higher top after first top."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # First top at 1100
        detector.update(1000, base_time)
        detector.update(1100, base_time + timedelta(minutes=1))
        result1 = detector.update(1089, base_time + timedelta(minutes=2))
        assert result1 == 1100

        # Price recovers and makes new high at 1200
        detector.update(1095, base_time + timedelta(minutes=3))
        detector.update(1150, base_time + timedelta(minutes=4))
        detector.update(1200, base_time + timedelta(minutes=5))

        # Drop from 1200 - should detect new top
        result2 = detector.update(1188, base_time + timedelta(minutes=6))
        assert result2 == 1200

    def test_ignores_lower_top_within_window(self):
        """Test that a lower top within window doesn't trigger detection."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # Highest point at 1200
        detector.update(1100, base_time)
        detector.update(1200, base_time + timedelta(minutes=1))

        # Drop to 1150 - this should detect the top at 1200
        result1 = detector.update(1150, base_time + timedelta(minutes=2))
        assert result1 == 1200  # Drop of 4.17% detects top

        # Recovery to 1180 - no new top (still same top at 1200)
        result2 = detector.update(1180, base_time + timedelta(minutes=3))
        assert result2 is None

        # Another drop to 1188 - should not re-detect same top
        result3 = detector.update(1188, base_time + timedelta(minutes=4))
        assert result3 is None


class TestTopDetectorTimeWindow:
    """Tests for time-based window management."""

    def test_old_prices_expire_from_window(self):
        """Test that old prices expire and don't affect detection."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=5),  # Short window
            min_drop_to_confirm=1.0,
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # Old high at 1200
        result1 = detector.update(1200, base_time)
        assert result1 is None  # No drop yet

        # Time passes (6 minutes - outside window)
        # New lower prices that form a new mini-peak at 1150
        detector.update(1100, base_time + timedelta(minutes=6))
        detector.update(1150, base_time + timedelta(minutes=7))

        # Drop from 1150 (highest in current window) by 1.04% should detect 1150, not old 1200
        result2 = detector.update(1138, base_time + timedelta(minutes=8))
        assert result2 == 1150  # Detects recent top, not expired one

    def test_empty_window_returns_none(self):
        """Test that empty price window returns None."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=5), min_drop_to_confirm=1.0
        )

        # No prices yet - should return None
        result = detector.update(1000, datetime(2025, 1, 1, 12, 0))
        assert result is None


class TestTopDetectorEdgeCases:
    """Edge case testing."""

    def test_zero_price_handling(self):
        """Test handling of zero prices (shouldn't crash)."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # Should handle zero without crashing
        result = detector.update(0, base_time)
        assert result is None

        detector.update(1000, base_time + timedelta(minutes=1))
        result = detector.update(990, base_time + timedelta(minutes=2))
        # Should work normally after zero
        assert result == 1000

    def test_very_small_drop_percentage(self):
        """Test detection with very small drop percentage threshold."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=0.1
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        detector.update(1000, base_time)
        detector.update(1100, base_time + timedelta(minutes=1))

        # Drop just 0.11% - should detect with 0.1% threshold
        result = detector.update(1098.8, base_time + timedelta(minutes=2))
        assert result == 1100

    def test_exact_threshold_drop(self):
        """Test that exact threshold drop is detected."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        detector.update(1000, base_time)
        detector.update(1100, base_time + timedelta(minutes=1))

        # Exactly 1.0% drop
        result = detector.update(1089, base_time + timedelta(minutes=2))
        assert result == 1100

    def test_flat_prices_no_detection(self):
        """Test that flat prices don't trigger detection."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # All same price
        assert detector.update(1000, base_time) is None
        assert detector.update(1000, base_time + timedelta(minutes=1)) is None
        assert detector.update(1000, base_time + timedelta(minutes=2)) is None


class TestTopDetectorRealWorldScenarios:
    """Real-world usage scenarios."""

    def test_volatile_market_with_multiple_tops(self):
        """Test detection in volatile market conditions."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)
        prices_and_results = [
            (1000, None),  # Start
            (1050, None),  # Rising
            (1100, None),  # First peak
            (1089, 1100),  # Drop - detects first top
            (1095, None),  # Recovery
            (1080, None),  # Down again
            (1120, None),  # New high
            (1150, None),  # Higher
            (1138, 1150),  # Drop - detects second top
            (1145, None),  # Recovery
            (1135, None),  # Lower
        ]

        for i, (price, expected) in enumerate(prices_and_results):
            result = detector.update(price, base_time + timedelta(minutes=i))
            assert (
                result == expected
            ), f"At minute {i}: price={price}, expected={expected}, got={result}"

    def test_gradual_decline_no_top(self):
        """Test that gradual decline doesn't trigger false positives."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=15), min_drop_to_confirm=1.0
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # Gradual decline - no sharp drop from a peak
        prices = [1100, 1095, 1090, 1085, 1080, 1075, 1070]

        for i, price in enumerate(prices):
            result = detector.update(price, base_time + timedelta(minutes=i))
            # First price should detect nothing
            # Subsequent prices should only detect if they drop > 1% from 1100
            if i == 0:
                assert result is None
            elif price <= 1100 * 0.99:  # More than 1% drop
                assert result == 1100  # First price is the top
                break
            else:
                assert result is None

    def test_recovery_then_higher_top(self):
        """Test realistic scenario: top, recovery, then higher top."""
        detector = TopDetector(
            lookback_window=timedelta(minutes=20), min_drop_to_confirm=1.5
        )

        base_time = datetime(2025, 1, 1, 12, 0)

        # First cycle
        detector.update(50000, base_time)  # BTC starting price
        detector.update(51000, base_time + timedelta(minutes=2))
        detector.update(52000, base_time + timedelta(minutes=4))

        # Drop 1.6% - detects first top
        result1 = detector.update(51168, base_time + timedelta(minutes=6))
        assert result1 == 52000

        # Recovery
        detector.update(51500, base_time + timedelta(minutes=8))
        detector.update(52500, base_time + timedelta(minutes=10))
        detector.update(53500, base_time + timedelta(minutes=12))

        # Drop 1.7% from 53500 - detects new top
        result2 = detector.update(52591, base_time + timedelta(minutes=14))
        assert result2 == 53500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
