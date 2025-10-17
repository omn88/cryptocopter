"""TopDetector - Identifies local tops in price movement.

A local top is defined as:
1. The highest price within a lookback window
2. Followed by a price drop of at least min_drop_to_confirm percentage

This is the foundation of the Buy Dip strategy - accurate top detection
determines when to start placing buy orders.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger("top_detector")


@dataclass
class PricePoint:
    """A price observation at a specific time."""

    price: float
    timestamp: datetime


class TopDetector:
    """Detects local tops in price movement.

    Usage:
        detector = TopDetector(
            lookback_window=timedelta(minutes=15),
            min_drop_to_confirm=1.0
        )

        # Update with each new price
        top_price = detector.update(current_price, datetime.now())

        if top_price:
            print(f"Local top detected at ${top_price}")
    """

    def __init__(
        self,
        lookback_window: timedelta = timedelta(minutes=15),
        min_drop_to_confirm: float = 1.0,
    ):
        """Initialize TopDetector.

        Args:
            lookback_window: How far back to look for highs (default: 15 minutes)
            min_drop_to_confirm: Percentage drop required to confirm top (default: 1.0%)
        """
        self.lookback_window = lookback_window
        self.min_drop_to_confirm = min_drop_to_confirm

        self.recent_prices: List[PricePoint] = []
        self.current_top: Optional[PricePoint] = None

        logger.debug(
            "TopDetector initialized: lookback=%s, min_drop=%.2f%%",
            lookback_window,
            min_drop_to_confirm,
        )

    def update(self, price: float, timestamp: datetime) -> Optional[float]:
        """Update with new price and check for top detection.

        Args:
            price: Current price
            timestamp: When this price was observed

        Returns:
            float: Top price if new top detected, None otherwise

        Algorithm:
            1. Add new price to recent_prices
            2. Remove prices outside lookback window
            3. Find highest price in window
            4. Check if price has dropped enough from highest to confirm as top
            5. Return top price if detected (and different from current_top)
        """
        # TODO: Implement the logic described in tests
        # Start with test_top_detector_identifies_simple_local_top

        # Hint: Follow these steps:
        # 1. Add new price to self.recent_prices
        # 2. Clean up old prices (outside lookback_window)
        # 3. Find highest price in recent_prices
        # 4. Calculate drop percentage from highest to current
        # 5. If drop >= min_drop_to_confirm, we have a top!

        raise NotImplementedError("Remove this and implement the logic!")


if __name__ == "__main__":
    # Quick manual test
    detector = TopDetector()

    base_time = datetime.now()
    print(detector.update(1000, base_time))
    print(detector.update(1100, base_time + timedelta(minutes=1)))
    print(detector.update(1088, base_time + timedelta(minutes=2)))  # Should detect 1100
