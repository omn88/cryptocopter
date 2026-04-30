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

logger = logging.getLogger(__name__)


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
        # Step 1: Add new price to recent_prices
        new_point = PricePoint(price=price, timestamp=timestamp)
        self.recent_prices.append(new_point)

        # Step 2: Remove prices outside lookback window
        cutoff_time = timestamp - self.lookback_window
        self.recent_prices = [
            p for p in self.recent_prices if p.timestamp >= cutoff_time
        ]

        # Step 3: Find highest price in window
        if not self.recent_prices:
            return None

        highest_point = max(self.recent_prices, key=lambda p: p.price)
        highest_price = highest_point.price

        # Step 4: Calculate drop percentage from highest to current
        if highest_price == 0:
            return None

        # Only detect top if current price is NOT the highest
        # (i.e., we've actually moved away from the peak)
        if price >= highest_price:
            return None

        drop_pct = ((highest_price - price) / highest_price) * 100

        # Step 5: Check if drop confirms a top (and it's different from current_top)
        if drop_pct >= self.min_drop_to_confirm:
            # Check if this is a new top (not the same one we already detected)
            if (
                self.current_top is None
                or highest_point.timestamp != self.current_top.timestamp
            ):
                self.current_top = highest_point
                logger.info(
                    "Top detected at %.2f (current: %.2f, drop: %.2f%%)",
                    highest_price,
                    price,
                    drop_pct,
                )
                return highest_price

        return None


if __name__ == "__main__":
    # Quick manual test
    detector = TopDetector()

    base_time = datetime.now()
    print(detector.update(1000, base_time))
    print(detector.update(1100, base_time + timedelta(minutes=1)))
    print(detector.update(1088, base_time + timedelta(minutes=2)))  # Should detect 1100
