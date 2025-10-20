"""CandleBuffer - Ring buffer storage for 15-min candles.

Stores candles in chronological order with automatic eviction of oldest
candles when maxlen is reached. Used to maintain recent candle history
for pattern detection and analysis.
"""

from collections import deque
from typing import Dict, List


class CandleBuffer:
    """Ring buffer for storing candles with automatic FIFO eviction."""

    def __init__(self, maxlen: int = 100):
        """Initialize the candle buffer.

        Args:
            maxlen: Maximum number of candles to store (default: 100)
        """
        self._buffer: deque[Dict] = deque(maxlen=maxlen)

    def add(self, candle: Dict) -> None:
        """Add a candle to the buffer.

        Args:
            candle: Dictionary with OHLCV data and timestamp
        """
        self._buffer.append(candle)

    def get_last_n(self, n: int) -> List[Dict]:
        """Get the last N candles.

        Args:
            n: Number of candles to retrieve

        Returns:
            List of up to N most recent candles in chronological order
        """
        return list(self._buffer)[-n:]

    def get_all(self) -> List[Dict]:
        """Get all candles in the buffer.

        Returns:
            List of all candles in chronological order
        """
        return list(self._buffer)
