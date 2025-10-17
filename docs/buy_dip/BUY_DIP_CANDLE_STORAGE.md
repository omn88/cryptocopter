# Buy Dip Strategy - Candle Storage & ATR Guide

## Using Binance 15-min Candles (No Aggregator Needed!)

Binance WebSocket provides `kline` streams - subscribe to 15-min candles directly:
```
wss://fstream.binance.com/ws/btcusdt@kline_15m
```

---

## Storage Strategy: Ring Buffer + Optional DB

### Ring Buffer (In-Memory, Fast)

```python
from collections import deque
from dataclasses import dataclass
from typing import Optional

@dataclass
class Candle:
    timestamp: int      # Unix timestamp (ms)
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool     # False for current/incomplete candle
    
    @classmethod
    from_binance_kline(cls, kline_data):
        """Create from Binance kline WebSocket event"""
        k = kline_data['k']
        return cls(
            timestamp=k['t'],
            open=float(k['o']),
            high=float(k['h']),
            low=float(k['l']),
            close=float(k['c']),
            volume=float(k['v']),
            is_closed=k['x']  # 'x' = is candle closed
        )

class CandleBuffer:
    """Ring buffer storing last N completed candles."""
    
    def __init__(self, symbol: str, maxlen: int = 100):
        self.symbol = symbol
        self.candles = deque(maxlen=maxlen)
        self.current_candle: Optional[Candle] = None
        
    def update(self, candle: Candle) -> bool:
        """
        Update with new candle from WebSocket.
        Returns True if a new candle was completed.
        """
        if candle.is_closed:
            self.candles.append(candle)
            self.current_candle = None
            return True
        else:
            self.current_candle = candle
            return False
            
    def get_last_n(self, n: int) -> list[Candle]:
        """Get last N completed candles"""
        return list(self.candles)[-n:]
```

---

## Rising Candles - Flexible Detection

**Problem with strict "3 consecutive":**
- Misses valid uptrends with minor dips
- Example: 100 → 102 → 101 → 105 → 107 (7% gain but not "3 consecutive")

**Solution: EITHER consecutive OR total gain**

```python
class RisingCandleDetector:
    """
    Flexible rising detection:
    - EITHER: N consecutive higher (by high or close)
    - OR: Total % gain over window
    """
    
    def __init__(
        self,
        consecutive_required: int = 3,
        min_total_gain_percent: float = 0.3,
        use_high: bool = True  # True = highs, False = closes
    ):
        self.consecutive_required = consecutive_required
        self.min_total_gain = min_total_gain_percent / 100.0
        self.use_high = use_high
        
    def detect(self, candles: list[Candle]) -> tuple[bool, float]:
        """
        Returns: (is_rising, start_price)
        """
        if len(candles) < self.consecutive_required:
            return False, None
            
        prices = [c.high if self.use_high else c.close for c in candles]
        
        # Method 1: Consecutive rising
        consecutive = 0
        for i in range(1, len(prices)):
            if prices[i] > prices[i-1]:
                consecutive += 1
            else:
                consecutive = 0
                
        if consecutive >= self.consecutive_required:
            start_idx = len(prices) - consecutive - 1
            return True, prices[start_idx]
            
        # Method 2: Total gain (allows dips)
        total_gain = (prices[-1] - prices[0]) / prices[0]
        if total_gain >= self.min_total_gain:
            return True, prices[0]
            
        return False, None
```

**Example:**
```python
# Candle highs: [100, 102, 101, 105, 107]
#                ───────────────────────
#                +7% total (meets 0.3% threshold)
#                But not "3 consecutive" (dip at 101)

detector = RisingCandleDetector(
    consecutive_required=3,
    min_total_gain_percent=0.3,
    use_high=True
)

is_rising, start = detector.detect(candles)
# Returns: (True, 100) ← Valid uptrend!
```

---

## ATR (Average True Range) - Explained Simply

### What is ATR?

**Measures typical price movement (volatility).**

### Why Use It?

Fixed thresholds don't adapt to market conditions:
- Bull run: ±2% swings normal → need larger thresholds
- Sideways: ±0.3% swings → smaller thresholds okay

ATR **adapts automatically**.

### How It Works

**True Range = largest of:**
1. High - Low (candle range)
2. |High - Previous Close|
3. |Low - Previous Close|

**ATR = Smoothed average over N periods (default: 14)**

```python
class ATR:
    """Average True Range - volatility indicator"""
    
    def __init__(self, period: int = 14):
        self.period = period
        self.prev_close = None
        self.atr_value = None
        self.tr_sum = 0.0
        self.count = 0
        
    def update(self, candle: Candle) -> float:
        """Update ATR with new candle"""
        
        # Calculate True Range
        if self.prev_close is None:
            tr = candle.high - candle.low
        else:
            tr = max(
                candle.high - candle.low,
                abs(candle.high - self.prev_close),
                abs(candle.low - self.prev_close)
            )
            
        self.prev_close = candle.close
        self.count += 1
        
        # Calculate ATR
        if self.atr_value is None:
            # Bootstrap: simple average for first N
            self.tr_sum += tr
            if self.count == self.period:
                self.atr_value = self.tr_sum / self.period
        else:
            # Wilder's smoothing
            self.atr_value = ((self.atr_value * (self.period - 1)) + tr) / self.period
            
        return self.atr_value
```

### Using ATR for Adaptive Thresholds

```python
# Without ATR (fixed):
if pullback_pct >= 0.35:
    confirm_top()

# With ATR (adaptive):
atr_pct = (atr_value / current_price) * 100  # Convert $ to %
threshold = max(0.35, atr_mult * atr_pct)

if pullback_pct >= threshold:
    confirm_top()
```

**Example:**
```
Price: $67,000
ATR: $250
ATR%: (250 / 67,000) * 100 = 0.37%

With atr_mult = 0.8:
Threshold = max(0.35%, 0.8 * 0.37%) = 0.35% (use fixed)

But if volatile (ATR = $500):
ATR%: (500 / 67,000) * 100 = 0.75%
Threshold = max(0.35%, 0.8 * 0.75%) = 0.60% (use ATR)
```

**Result:** Thresholds **adapt to volatility**!

---

## Tracking Local Bottoms

**You're correct!** To calculate potential gain, need:
1. **Local top** (high-watermark)
2. **Local bottom** (lowest after top)
3. **Drawdown = (top - bottom) / top**

```python
class HighWatermarkDetector:
    def __init__(
        self,
        confirm_threshold_pct: float = 0.35,
        use_atr: bool = True,
        atr_mult: float = 0.8
    ):
        self.confirm_threshold = confirm_threshold_pct / 100.0
        self.use_atr = use_atr
        self.atr_mult = atr_mult
        self.atr = ATR(14) if use_atr else None
        
        self.hwm = None           # High-watermark (potential top)
        self.local_bottom = None  # Lowest after HWM
        self.provisional_top = None
        
    def update(self, candle: Candle):
        if self.use_atr:
            self.atr.update(candle)
            
        # Update high-watermark
        if self.hwm is None or candle.high > self.hwm:
            if self.provisional_top and candle.high > self.provisional_top:
                # New high - invalidate old top
                return {"event": "top_invalidated", "new_top": candle.high}
                
            self.hwm = candle.high
            self.local_bottom = None  # Reset on new high
            
        # Track lowest after HWM
        if self.hwm:
            if self.local_bottom is None or candle.low < self.local_bottom:
                self.local_bottom = candle.low
                
            # Calculate drawdown
            drawdown_pct = (self.hwm - self.local_bottom) / self.hwm
            
            # Adaptive threshold
            threshold = self.confirm_threshold
            if self.use_atr and self.atr.atr_value:
                atr_pct = self.atr.atr_value / self.hwm
                threshold = max(threshold, self.atr_mult * atr_pct)
                
            if drawdown_pct >= threshold:
                # Top confirmed!
                return {
                    "event": "confirmed_top",
                    "top": self.hwm,
                    "bottom": self.local_bottom,
                    "drawdown": drawdown_pct * 100
                }
                
        return None
```

---

## Complete Example

```python
# Initialize components
candle_buffer = CandleBuffer("BTCUSDT", maxlen=100)
rising_detector = RisingCandleDetector(
    consecutive_required=3,
    min_total_gain_percent=0.25,  # 0.25% gain OR 3 consecutive
    use_high=True
)
hwm_detector = HighWatermarkDetector(
    confirm_threshold_pct=0.35,
    use_atr=True,
    atr_mult=0.8
)

# WebSocket handler
def on_kline_message(msg):
    candle = Candle.from_binance_kline(msg)
    candle_completed = candle_buffer.update(candle)
    
    if not candle_completed:
        return  # Wait for candle to close
        
    # Get recent candles
    recent = candle_buffer.get_last_n(5)
    
    # Check for rising candles (arm top watch)
    is_rising, start_price = rising_detector.detect(recent)
    if is_rising:
        print(f"Rising detected from ${start_price:.2f}")
        
    # Update HWM detector
    event = hwm_detector.update(candle)
    if event:
        if event["event"] == "confirmed_top":
            print(f"✅ TOP CONFIRMED: ${event['top']:.2f}")
            print(f"   Bottom: ${event['bottom']:.2f}")
            print(f"   Drawdown: {event['drawdown']:.2f}%")
            # Place first buy order
            
        elif event["event"] == "top_invalidated":
            print(f"❌ Top invalidated, new high: ${event['new_top']:.2f}")
            # Cancel pending orders
```

---

## Recommended Configuration

### For BTC/ETH (15-min candles):

```python
config = {
    # Rising detection
    "consecutive_rising": 3,
    "min_total_gain": 0.25,  # 0.25% over ~45 min
    "use_high": True,        # Compare candle highs
    
    # HWM confirmation
    "confirm_pullback": 0.35,  # 0.35% min drawdown
    "use_atr": True,
    "atr_period": 14,
    "atr_mult": 0.8,
    
    # DCA ladder
    "ladder_distances": [0.5, 1.0, 1.5],  # % below top
    
    # Take profit
    "tp_mode": "return_to_top",  # Sell at breakeven
}
```

### For BNB/LTC (more volatile):

```python
config = {
    "consecutive_rising": 3,
    "min_total_gain": 0.4,     # Need bigger moves
    "confirm_pullback": 0.5,   # Bigger pullback
    "atr_mult": 1.0,           # More ATR influence
    "ladder_distances": [0.8, 1.5, 2.5],  # Wider spacing
}
```

---

## Summary

✅ **No candle aggregator needed** - use Binance 15-min klines directly  
✅ **Ring buffer** - fast in-memory storage  
✅ **Flexible rising detection** - consecutive OR total gain  
✅ **ATR-based thresholds** - adapts to volatility  
✅ **Local bottom tracking** - calculates drawdown correctly  
✅ **Top invalidation** - moves up if new high before fill  

This is **much simpler** than tick-based three-phase approach!
