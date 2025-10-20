"""RisingCandleDetector - Detects rising candle patterns.

Identifies uptrends using two criteria (OR logic):
1. N consecutive candles with higher highs
2. Total gain percentage threshold over N candles

Uses candle HIGHS (not closes) for detection.
"""

from typing import Dict


class RisingCandleDetector:
    """Detect rising candle patterns for potential top identification."""

    def __init__(self, min_consecutive: int = 3, min_total_gain_pct: float = 0.25):
        """Initialize rising candle detector.

        Args:
            min_consecutive: Minimum consecutive higher highs (default: 3)
            min_total_gain_pct: Minimum total gain percentage (default: 0.25%)
        """
        self._min_consecutive = min_consecutive
        self._min_total_gain_pct = min_total_gain_pct
        self._highs: list[float] = []

    def add_candle(self, candle: Dict) -> None:
        """Add a candle for pattern analysis.

        Args:
            candle: Dictionary with high value and timestamp
        """
        self._highs.append(candle["high"])

    def is_rising(self) -> bool:
        """Check if rising pattern is detected.

        Returns:
            True if EITHER consecutive highs OR total gain threshold met
        """
        if len(self._highs) < self._min_consecutive:
            return False

        # Get last N highs
        recent_highs = self._highs[-self._min_consecutive :]

        # Check consecutive higher highs
        consecutive = all(
            recent_highs[i] < recent_highs[i + 1] for i in range(len(recent_highs) - 1)
        )

        # Check total gain percentage
        first_high = recent_highs[0]
        last_high = recent_highs[-1]
        total_gain_pct = ((last_high - first_high) / first_high) * 100
        gain_threshold_met = total_gain_pct >= self._min_total_gain_pct

        # OR logic: either condition sufficient
        return consecutive or gain_threshold_met
