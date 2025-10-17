# Buy Dip Strategy - Complete Design

## Overview

The **Buy Dip Strategy** identifies local tops and buys the dips during pullbacks, selling at breakeven (or small profit) when price returns to the top.

**Core Concept:**
1. Detect a **local top** using High-Watermark approach
2. Place **first buy order** when top is confirmed
3. **First fill confirms** the top is real (market validation)
4. Place **DCA ladder** for deeper dips
5. **Sell** when price returns to top (breakeven)

---

## Key Insight: Two-Phase Confirmation

### Phase 1: Provisional Top
**Pattern-based detection** - suggests a potential top might be forming

### Phase 2: Confirmed Top
**Market validation** - first buy order fills, proving price is actually dipping

**Why this matters:**
- Pattern alone can give false signals
- Order fill proves market is actually moving down
- No wasted capital on fake tops

---

## Architecture

### Data Flow

```
Binance WebSocket (15-min klines)
    ↓
CandleBuffer (ring buffer, last 100 candles)
    ↓
RisingCandleDetector (arms top watch)
    ↓
HighWatermarkDetector (confirms top)
    ↓
BuyDipPosition (places orders, manages position)
```

### Components

#### 1. CandleBuffer
**Purpose:** Store recent 15-min candles in memory

**Features:**
- Ring buffer (auto-evicts old data)
- Tracks current incomplete candle
- Provides last N candles for analysis

```python
buffer = CandleBuffer("BTCUSDT", maxlen=100)
candle = Candle.from_binance_kline(ws_message)
if buffer.update(candle):  # Returns True when candle closes
    # Process completed candle
```

---

#### 2. RisingCandleDetector
**Purpose:** Detect meaningful uptrends to "arm" top detection

**Logic:**
```
EITHER:
  - 3 consecutive rising candle highs
OR:
  - Total gain >= threshold (e.g., 0.25%) over window

Use HIGHS (not closes) for detecting tops
```

**Why flexible?**
- Catches clean uptrends: 100 → 102 → 104
- Catches choppy uptrends: 100 → 102 → 101 → 105 (same gain)

**Code:**
```python
detector = RisingCandleDetector(
    consecutive_required=3,
    min_total_gain_percent=0.25,  # 0.25% over ~45 min
    use_high=True  # Compare highs
)

recent_candles = buffer.get_last_n(5)
is_rising, start_price = detector.detect(recent_candles)
```

---

#### 3. ATR (Average True Range)
**Purpose:** Measure volatility for adaptive thresholds

**What it does:**
- Calculates typical price movement per candle
- Adjusts thresholds based on current volatility

**Formula:**
```
True Range = max(
    High - Low,
    abs(High - Previous Close),
    abs(Low - Previous Close)
)

ATR = Smoothed average of True Range over N periods (default: 14)
```

**Why use it?**
```
Calm market: ATR = $150 → use fixed threshold (0.35%)
Volatile market: ATR = $500 → use larger threshold (0.60%)

Prevents false signals during volatile periods
```

**Code:**
```python
atr = ATR(period=14)
atr.update(candle)

# Convert ATR to percentage
atr_pct = (atr.atr_value / current_price) * 100

# Adaptive threshold
threshold = max(0.35, atr_mult * atr_pct)
```

---

#### 4. HighWatermarkDetector
**Purpose:** Detect and confirm local tops

**Algorithm:**
1. Track **highest price** seen (high-watermark)
2. Track **lowest price** after HWM (local bottom)
3. Calculate **drawdown** = (HWM - bottom) / HWM
4. When drawdown >= threshold → **Top confirmed**
5. If new high before confirmation → **Top invalidated**

**Adaptive Threshold:**
```python
# Base threshold
threshold = 0.35%

# ATR adjustment (if volatile)
if use_atr:
    atr_threshold = (atr_value / price) * atr_mult
    threshold = max(0.35%, atr_threshold)

# Confirm top
if drawdown >= threshold:
    return "confirmed_top"
```

**Top Invalidation:**
```python
if new_high > provisional_top:
    # Cancel pending orders
    # Update top to new high
    # Continue watching
```

---

#### 5. BuyDipPosition
**Purpose:** Manage individual position lifecycle

**States:**
- **WATCHING**: Monitoring for potential top
- **POTENTIAL_TOP**: First order placed, awaiting fill
- **ACTIVE**: Position open, managing DCA ladder
- **COMPLETED**: Sold at target, profit calculated
- **CANCELLED**: Top invalidated or error

**Lifecycle:**

```
WATCHING
  ↓ (rising candles detected + HWM top confirmed)
Place first buy order
  ↓
POTENTIAL_TOP (awaiting first fill)
  ↓
  ├─ Fill → ACTIVE (top confirmed by market)
  └─ New high → CANCELLED (cancel order, reset)
  
ACTIVE (position open)
  ↓
Place DCA ladder orders
Monitor for fills
Update sell order quantity
  ↓
COMPLETED (all sold at top)
```

---

## Complete Flow Example

### Setup
```python
# Configuration
config = {
    "symbol": "BTCUSDT",
    "candle_interval": "15m",
    "trade_size_usdt": 100,
    
    # Rising detection
    "consecutive_rising": 3,
    "min_total_gain_percent": 0.25,
    "use_high": True,
    
    # HWM confirmation
    "confirm_pullback_percent": 0.35,
    "use_atr": True,
    "atr_period": 14,
    "atr_mult": 0.8,
    
    # DCA ladder
    "ladder_distances_percent": [0.5, 1.0, 1.5],
    
    # Take profit
    "sell_at_top": True,
}
```

### Scenario: BTC Top Detection

**Initial State:**
```
Price action (15-min candles):
$67,000 → $67,200 → $67,400 → $67,600 → $67,890

RisingCandleDetector:
  3 consecutive rising highs ✓
  Total gain: 1.3% (> 0.25%) ✓
  → Rising pattern confirmed, arm top watch
  
HighWatermarkDetector:
  HWM = $67,890
  Status: Watching for pullback
```

**Pullback Begins:**
```
$67,890 → $67,700 → $67,500 → $67,300

HighWatermarkDetector:
  HWM: $67,890
  Local bottom: $67,300
  Drawdown: (67,890 - 67,300) / 67,890 = 0.87%
  
  ATR: $250 → 0.37%
  Threshold: max(0.35%, 0.8 × 0.37%) = 0.35%
  
  0.87% > 0.35% → TOP CONFIRMED! ✅
```

**Order Placement:**
```
Event: "confirmed_top"
  top_price: $67,890
  bottom_price: $67,300
  
BuyDipPosition:
  State: WATCHING → POTENTIAL_TOP
  
Actions:
  1. Place first buy: $67,300 (current price)
  2. Prepare DCA ladder:
     - Level 1: $67,890 × (1 - 0.005) = $67,550
     - Level 2: $67,890 × (1 - 0.010) = $67,215
     - Level 3: $67,890 × (1 - 0.015) = $66,880
```

**First Order Fills:**
```
First buy fills at $67,300

BuyDipPosition:
  State: POTENTIAL_TOP → ACTIVE ✅
  Top confirmed by market!
  
Actions:
  1. Place DCA ladder orders (already calculated)
  2. Place sell order: $67,890 (breakeven at top)
     Quantity: 100 USDT / $67,300 = 0.001486 BTC
```

**DCA Fills:**
```
Price continues down: $67,300 → $67,000 → $66,900

DCA Level 2 fills at $67,215
  Quantity: 0.001488 BTC
  
Average price: (67,300 + 67,215) / 2 = $67,258
Total quantity: 0.002974 BTC

Actions:
  1. Update sell order quantity: 0.002974 BTC
  2. Keep sell price at $67,890 (original top)
```

**Price Recovery:**
```
Price rises: $66,900 → $67,200 → $67,500 → $67,890

Sell order fills at $67,890

BuyDipPosition:
  State: ACTIVE → COMPLETED ✅
  
Profit Calculation:
  Buy average: $67,258
  Sell price: $67,890
  Profit: (67,890 - 67,258) / 67,258 = 0.94%
  Profit USDT: 200 × 0.0094 = $1.88
```

---

## Top Invalidation Scenario

**What if price makes new high before first order fills?**

```
HWM: $67,890 (provisional top)
First order placed at: $67,500
Status: POTENTIAL_TOP (awaiting fill)

Price action: $67,500 → $67,800 → $68,100 (NEW HIGH!)

HighWatermarkDetector:
  New high detected: $68,100 > $67,890
  → TOP INVALIDATED! ❌
  
BuyDipPosition:
  State: POTENTIAL_TOP → CANCELLED
  
Actions:
  1. Cancel pending buy order at $67,500
  2. Update HWM to $68,100
  3. Reset to WATCHING state
  4. Wait for new pullback from $68,100
```

---

## Configuration Guidelines

### Conservative (BTC/ETH, 15-min candles)
```python
{
    "consecutive_rising": 3,
    "min_total_gain_percent": 0.3,     # Need clear uptrend
    "confirm_pullback_percent": 0.5,   # Bigger pullback
    "atr_mult": 1.0,                   # More ATR influence
    "ladder_distances": [0.5, 1.0, 1.5],
}
```

### Balanced (Default)
```python
{
    "consecutive_rising": 3,
    "min_total_gain_percent": 0.25,
    "confirm_pullback_percent": 0.35,
    "atr_mult": 0.8,
    "ladder_distances": [0.5, 1.0, 1.5],
}
```

### Aggressive (More trades)
```python
{
    "consecutive_rising": 2,           # Easier to trigger
    "min_total_gain_percent": 0.2,
    "confirm_pullback_percent": 0.25,  # Smaller pullback
    "atr_mult": 0.6,                   # Less ATR influence
    "ladder_distances": [0.3, 0.8, 1.3],
}
```

---

## Advantages

✅ **No candle aggregation needed** - Use Binance 15-min klines directly  
✅ **Flexible pattern detection** - Consecutive OR total gain  
✅ **Volatility adaptive** - ATR adjusts thresholds automatically  
✅ **Market validated** - First fill confirms top is real  
✅ **Top invalidation** - Cancels if new high appears  
✅ **Simple to understand** - Clear states and transitions  
✅ **Risk managed** - DCA ladder with predefined distances  
✅ **Breakeven bias** - Sell at top minimizes risk  

---

## Implementation Phases

### Phase 1: Core Detection
- [ ] CandleBuffer (storage)
- [ ] ATR (volatility)
- [ ] RisingCandleDetector
- [ ] HighWatermarkDetector

### Phase 2: Position Management
- [ ] BuyDipPosition (state machine)
- [ ] Order placement logic
- [ ] Top invalidation handling
- [ ] DCA ladder management

### Phase 3: Integration
- [ ] WebSocket integration (Broker)
- [ ] Database persistence
- [ ] Position recovery on restart

### Phase 4: UI
- [ ] Configuration screen
- [ ] Position monitoring
- [ ] Performance metrics

---

## Testing Strategy

### Unit Tests
- CandleBuffer: Storage and retrieval
- ATR: Calculation accuracy
- RisingCandleDetector: Pattern detection
- HighWatermarkDetector: Top confirmation

### Integration Tests
- Complete detection cycle
- Top invalidation handling
- DCA ladder logic
- Profit calculations

### Backtesting
- Historical 15-min candle data
- Multiple market conditions
- Performance metrics

---

## Next Steps

1. ✅ Documentation complete
2. ⏳ Write comprehensive test suite
3. ⏳ Implement core components (TDD)
4. ⏳ Integration with existing infrastructure
5. ⏳ GUI implementation

**Ready to implement using TDD!** 🚀
