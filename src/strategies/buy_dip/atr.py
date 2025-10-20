"""ATR - Average True Range calculator using Wilder's smoothing.

Calculates volatility-based threshold for top confirmation.
Uses Wilder's smoothing: ATR = ((prior_ATR * (period-1)) + current_TR) / period
"""

from typing import Dict, Optional


class ATR:
    """Calculate Average True Range with Wilder's smoothing."""

    def __init__(self, period: int = 14):
        """Initialize ATR calculator.

        Args:
            period: Number of periods for ATR calculation (default: 14)
        """
        self._period = period
        self._true_ranges: list[float] = []
        self._atr: Optional[float] = None
        self._previous_close: Optional[float] = None

    def add_candle(self, candle: Dict) -> None:
        """Add a candle and update ATR calculation.

        Args:
            candle: Dictionary with high, low, close values
        """
        # Calculate True Range
        high = candle["high"]
        low = candle["low"]
        close = candle["close"]

        if self._previous_close is None:
            # First candle: TR = high - low
            true_range = high - low
        else:
            # TR = max(H-L, |H-PC|, |L-PC|)
            true_range = max(
                high - low,
                abs(high - self._previous_close),
                abs(low - self._previous_close),
            )

        self._previous_close = close
        self._true_ranges.append(true_range)

        # Update ATR only after we have enough data
        if len(self._true_ranges) == self._period:
            # First ATR: simple average of first N TRs
            self._atr = sum(self._true_ranges) / self._period
        elif len(self._true_ranges) > self._period:
            # Wilder's smoothing: ATR = ((prior_ATR * (period-1)) + current_TR) / period
            # At this point, _atr must be set (from the previous condition)
            assert self._atr is not None
            self._atr = ((self._atr * (self._period - 1)) + true_range) / self._period

    def get_atr(self) -> Optional[float]:
        """Get current ATR value.

        Returns:
            ATR value, or None if insufficient data (< period candles)
        """
        return self._atr
