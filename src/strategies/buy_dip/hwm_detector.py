"""HighWatermarkDetector - Tracks high watermark and confirms tops.

Tracks the highest high seen and confirms a top when price pulls back
by a threshold (ATR-based or percentage-based). Also tracks the bottom
(lowest point) during pullbacks.
"""

from typing import Dict, Optional


class HighWatermarkDetector:
    """Track high watermark and confirm tops with adaptive thresholds."""

    def __init__(self, atr_multiplier: float = 2.0, min_pullback_pct: float = 0.5):
        """Initialize high watermark detector.

        Args:
            atr_multiplier: Multiplier for ATR-based threshold (default: 2.0)
            min_pullback_pct: Minimum pullback percentage (default: 0.5%)
        """
        self._atr_multiplier = atr_multiplier
        self._min_pullback_pct = min_pullback_pct
        self._atr: Optional[float] = None
        self._hwm: Optional[float] = None
        self._confirmed_top: Optional[float] = None
        self._bottom: Optional[float] = None

    def update_atr(self, atr: float) -> None:
        """Update the ATR value for adaptive threshold calculation.

        Args:
            atr: Current ATR value from ATR calculator
        """
        self._atr = atr

    def add_candle(self, candle: Dict) -> None:
        """Process a candle and update HWM/top tracking.

        Args:
            candle: Dictionary with high, low values
        """
        high = candle["high"]
        low = candle.get("low", high)

        # Initialize or update HWM
        if self._hwm is None:
            self._hwm = high
        elif high > self._hwm:
            # New high! Update HWM and invalidate previous top
            self._hwm = high
            self._confirmed_top = None
            self._bottom = None
        else:
            # Not a new high - check for pullback confirmation
            if not self._confirmed_top and self._hwm is not None:
                # Calculate threshold: max(ATR * multiplier, HWM * min_pullback_pct / 100)
                if self._atr is not None:
                    atr_threshold = float(self._atr) * self._atr_multiplier
                else:
                    atr_threshold = 0.0

                pct_threshold = float(self._hwm) * (self._min_pullback_pct / 100.0)
                threshold = max(atr_threshold, pct_threshold)

                # Check if pullback exceeds threshold
                pullback = self._hwm - high
                if pullback >= threshold:
                    self._confirmed_top = self._hwm

            # Track bottom during pullback
            if self._bottom is None:
                self._bottom = low
            else:
                self._bottom = min(self._bottom, low)

    def get_hwm(self) -> Optional[float]:
        """Get current high watermark.

        Returns:
            Highest high seen so far, or None if no candles processed yet
        """
        return self._hwm

    def is_top_confirmed(self) -> bool:
        """Check if a top has been confirmed.

        Returns:
            True if pullback exceeds threshold, False otherwise
        """
        return self._confirmed_top is not None

    def get_confirmed_top(self) -> Optional[float]:
        """Get the confirmed top price.

        Returns:
            Top price if confirmed, None otherwise
        """
        return self._confirmed_top

    def get_bottom(self) -> Optional[float]:
        """Get the lowest point during pullback.

        Returns:
            Lowest low during pullback, or None if no pullback
        """
        return self._bottom
