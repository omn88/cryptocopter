# Buy Dip Strategy - Start Here

## What is This Strategy?

The **Buy Dip Strategy** automatically:
1. Identifies local price tops
2. Buys during pullbacks (dips)
3. Sells when price returns to the top (breakeven or small profit)

Think of it as **"buying the dip and selling the bounce"** - automatically.

---

## How It Works (Plain Language)

### Step 1: Detect a Top

**Watch for an uptrend:**
- BTC rises from $67,000 to $67,890 over ~1 hour (three 15-min green candles)
- This shows bullish momentum

**Wait for pullback:**
- Price drops from $67,890 to $67,300 (0.87% drop)
- This suggests the top might be in

**Result:** Potential top detected at $67,890

### Step 2: Place First Order IMMEDIATELY

**Action:** Place first buy order at $67,890 × (1 - 1.618%) = **$66,792.78**

**Why BELOW the top?**
- We're buying the DIP, not the top!
- 1.618% distance = golden ratio (φ)
- Order fill = price dipped far enough → top confirmed
- If price goes higher → cancel and replace at new top

**Mathematical Constants for DCA Distances:**
- Order 1: 1.618% below top (φ - golden ratio)
- Order 2: 2.718% below top (e - Euler's number)
- Order 3: 3.142% below top (π - pi)

**State:** POTENTIAL_TOP (waiting for dip to Order 1 price)

### Step 3: Market Confirms (or Invalidates)

**Scenario A: Order 1 Fills** ✅
```
Top: $67,890
Order 1: $66,792.78 (-1.618% φ distance)

Price drops from $67,890 to $66,792.78
Order 1 fills!
→ Market confirmed the top is real!
→ Position now ACTIVE
→ Create sell order at $67,890 (at top price)
→ Place Order 2 at $67,890 × (1 - 2.718%) = $66,046.50 (e distance)
→ Only ONE pending order at a time!
```

**Scenario B: New Higher High** ❌
```
Top was: $67,890
Order 1 at: $66,792.78 (pending - only this one!)

Price rises: $67,890 → $68,100 (new high!)
→ It wasn't the real top
→ Cancel Order 1 at $66,792.78 (never filled)
→ Calculate NEW Order 1: $68,100 × (1 - 1.618%) = $66,998.22
→ Place at new price
→ Still only ONE pending order
→ No money wasted!
```

### Step 4: Sequential DCA Orders (ONE AT A TIME!)

**CRITICAL: Only one pending buy order at a time**

**Order 1 fills: $66,792.78 (φ distance from $67,890)**
```
✅ Order 1 executed
→ Update position: investment = $200
→ Update sell quantity
→ NOW place Order 2 at: $67,890 × (1 - 2.718%) = $66,046.50 (e distance)
→ Only ONE pending order now (Order 2)
```

**Order 2 fills: $66,046.50**
```
✅ Order 2 executed
→ Update position: investment = $396
→ Update sell quantity (now 2 orders worth)
→ Recalculate average entry price
→ NOW place Order 3 at: $67,890 × (1 - 3.142%) = $65,758.30 (π distance)
→ Only ONE pending order now (Order 3)
```

**Order 3 fills: $65,758.30**
```
✅ Order 3 executed
→ Update position: investment = $588
→ Update sell quantity (now 3 orders worth)
→ Recalculate average entry price
→ Max DCA reached (or place Order 4 if configured)
```

**Key Points:**
- ✅ ONE pending buy order at a time
- ✅ Fill execution report triggers next order placement
- ✅ Capital efficient: don't lock all funds upfront
- ✅ Adaptive: deeper dips get more orders naturally
- ❌ NEVER have multiple pending buy orders simultaneously

**Example Timeline:**
```
T0: Top at $67,890 detected
T1: Place Order 1 at $66,792.78 (pending: 1)
T2: Order 1 fills (pending: 0)
T3: Place Order 2 at $66,046.50 (pending: 1)
T4: Order 2 fills (pending: 0)
T5: Place Order 3 at $65,758.30 (pending: 1)
T6: Order 3 fills (pending: 0)
T7: All orders complete, waiting for price recovery
```

Order 3 fills: $67,215
→ Update sell quantity (now 3 orders worth)
→ Place Order 4 at: $67,890 × (1 - 0.015) = $66,878

Continue until max orders OR budget exhausted
```

**Key:** Each order waits for previous to fill (not all at once)

### Step 5: Sell at Top and Order Cleanup

**Price recovers to $67,890:**
- Sell order fills
- Position CLOSED
- Profit = (sell price - avg buy price) × quantity

**CRITICAL:** Cancel ALL remaining buy orders!
- Sell fills = this position's lifecycle is COMPLETE
- Remaining orders belong to THIS closed position
- Must cancel immediately to avoid orphaned orders
- Clean slate for next opportunity

**Example:**
```
Bought: 3 orders filled @ avg $67,552
Sold:   At $67,890
Profit: $338 per position

Order 4 pending at $66,878:
  ❌ CANCEL immediately (position closed)
  ✅ Don't leave orphaned orders
```

**Important Distinction - Top Crossing:**

**A) BEFORE first order fills (POTENTIAL_TOP):**
```
Order 1 at $67,890 (pending)
Price crosses $67,900 (new high)
→ INVALIDATION: Cancel Order 1, place at new HWM
→ Position continues tracking
```

**B) AFTER orders filled (ACTIVE):**
```
Orders 1-3 filled, Order 4 pending
Sell fills at $67,890
→ CLOSURE: Cancel Order 4 (position done)
→ Position lifecycle complete
```

---

## Budget Management

### Dynamic Percentage-Based Sizing

**Instead of fixed $100 per order:**
- Start with total budget (e.g., $10,000)
- Each order = X% of AVAILABLE budget (e.g., 2%)
- Available budget decreases as orders are placed
- Increases when positions close

**Example:**
```
Initial: $10,000 available

Order 1: $10,000 × 2% = $200
  Available: $9,800

Order 2: $9,800 × 2% = $196
  Available: $9,604

Order 3: $9,604 × 2% = $192
  Available: $9,412

Position closes: +$400 received
  Available: $9,812
  
Next order: $9,812 × 2% = $196
```

### Adding/Withdrawing Funds

**Add funds:**
```python
strategy.add_budget(1000)  # Add $1,000
# Immediately available for new orders
```

**Withdraw gains:**
```python
strategy.withdraw(500)  # Withdraw $500
# Reduces available budget
```

**Use cases:**
- Got more USDC → Add to strategy (no restart needed)
- Want to take profits → Withdraw gains
- Rebalance between strategies

### Insufficient Funds Handling

**Graceful waiting:**
```
Available: $50
Next order would be: $50 × 2% = $1
Minimum order: $10

Action:
  ✅ Log: "Insufficient funds, waiting..."
  ✅ Don't place order
  ✅ Don't error/crash
  ✅ Wait for positions to close
  ❌ Don't skip opportunities
```

**Recovery:**
- Position closes → funds available → resume
- User adds funds → resume immediately

---

## Key Insight: Two-Phase Confirmation

### Most strategies: Pattern = Immediate action
```
Detect top → Create position → Risk capital immediately
Problem: False signals cost money
```

### This strategy: Pattern → Test → Confirm
```
Detect top → Place test order → Wait for fill
→ Fill = Real top, create position ✅
→ No fill + new high = False signal, cancel ❌
```

**Benefit:** Market validates our hypothesis before committing capital!

---

## Why Use 15-Min Candles?

### Problem with 1-second ticks:
- Too noisy (thousands of price updates)
- False signals every few minutes
- Overwhelmed with positions

### Solution: 15-min candles:
- Filters noise automatically
- ~1 hour to detect top (4 candles)
- Meaningful timeframe for analysis
- Binance provides them directly (no aggregation needed)

**Configuration:**
- Conservative: Use 1-hour candles (fewer signals, higher confidence)
- Balanced: Use 15-min candles (good mix)
- Aggressive: Use 5-min candles (more signals, more noise)

---

## Components Explained

### 1. CandleBuffer
**Purpose:** Store recent candles in memory

**Think of it as:** A sliding window showing last 100 candles

**Why:** Need history to detect patterns (rising, pullbacks)

### 2. ATR (Average True Range)
**Purpose:** Measure how volatile the market is

**Simple explanation:**
- Calm market: Price moves $150 per 15-min
- Volatile market: Price moves $500 per 15-min

**Use:** Adjust thresholds based on volatility
- Calm → use smaller threshold (0.35%)
- Volatile → use larger threshold (0.60%)

**Benefit:** Prevents false signals during wild price swings

### 3. RisingCandleDetector
**Purpose:** Spot uptrends that precede tops

**Logic:**
```
EITHER:
  3 consecutive rising candles (compare highs)
OR:
  Total gain >= 0.25% over window

Both indicate bullish momentum before a potential top
```

**Why flexible?**
- Catches clean uptrends: 100 → 102 → 104
- Catches choppy uptrends: 100 → 102 → 101 → 105 (same result)

### 4. HighWatermarkDetector
**Purpose:** Find the actual top price

**Algorithm:**
1. Track highest price seen (high-watermark)
2. Track lowest price after that (local bottom)
3. Calculate drawdown: (high - low) / high
4. If drawdown >= threshold (e.g., 0.35%) → Top confirmed!

**Top invalidation:**
- If price makes NEW high before order fills
- Cancel order, update high-watermark
- No money wasted

### 5. BuyDipPosition
**Purpose:** Manage entire position lifecycle

**States:**
- WATCHING: Looking for tops
- POTENTIAL_TOP: Test order placed, awaiting fill
- ACTIVE: Position open, managing DCA + sell
- COMPLETED: Sold successfully, profit calculated
- CANCELLED: Top invalidated or error

---

## Complete Example Walkthrough

### Initial Market Conditions
```
Symbol: BTCUSDT
Time: 12:00 PM
Price: $67,000
Strategy: Watching for opportunities
```

### 12:00 - 12:45 PM: Rising Pattern
```
12:00: $67,000 (candle high)
12:15: $67,200 (candle high) +$200 ↑
12:30: $67,400 (candle high) +$200 ↑
12:45: $67,600 (candle high) +$200 ↑

RisingCandleDetector:
  3 consecutive rising candles ✓
  Total gain: 0.9% (> 0.25% threshold) ✓
  → Rising pattern confirmed!
```

### 12:45 - 01:00 PM: Peak Formation
```
01:00: $67,890 (candle high) +$290 ↑

HighWatermarkDetector:
  High-watermark: $67,890
  Status: Watching for pullback
```

### 01:00 - 01:45 PM: Pullback
```
01:15: $67,700 (high) -$190 ↓
01:30: $67,500 (high) -$200 ↓
01:45: $67,300 (close) -$200 ↓

HighWatermarkDetector:
  HWM: $67,890
  Local bottom: $67,300
  Drawdown: (67,890 - 67,300) / 67,890 = 0.87%
  
  Threshold: 0.35% (with ATR adjustment)
  0.87% > 0.35% → POTENTIAL TOP CONFIRMED!
```

### 01:45 PM: Order Placement
```
Event: potential_top_confirmed
  top_price: $67,890
  entry_price: $67,300
  
BuyDipPosition:
  State: WATCHING → POTENTIAL_TOP
  
Action:
  Place limit buy order: $67,300, qty: 0.001486 BTC ($100 USDT)
  Status: Awaiting fill...
```

### 01:50 PM: First Fill (CONFIRMATION!)
```
Order filled: 0.001486 BTC @ $67,300

BuyDipPosition:
  State: POTENTIAL_TOP → ACTIVE ✅
  Top confirmed by market!
  
Actions:
  1. Calculate DCA ladder:
     Level 1: $67,890 × 0.995 = $67,550 ($100 USDT)
     Level 2: $67,890 × 0.990 = $67,215 ($100 USDT)
     Level 3: $67,890 × 0.985 = $66,880 ($100 USDT)
     
  2. Place DCA orders (limits)
  
  3. Place sell order:
     Price: $67,890 (top)
     Quantity: 0.001486 BTC
```

### 02:00 - 02:30 PM: Deeper Dip
```
02:00: $67,200 (DCA Level 2 fills!)
  Filled: 0.001488 BTC @ $67,215
  Total position: 0.002974 BTC
  Average price: $67,258
  
  Update sell order:
    Price: $67,890 (unchanged)
    Quantity: 0.002974 BTC (updated)

02:30: $66,900 (DCA Level 3 fills!)
  Filled: 0.001495 BTC @ $66,880
  Total position: 0.004469 BTC
  Average price: $67,131
  
  Update sell order:
    Price: $67,890 (unchanged)
    Quantity: 0.004469 BTC (updated)
```

### 03:00 - 04:30 PM: Recovery
```
03:00: $67,000
03:30: $67,300
04:00: $67,600
04:30: $67,890 (Sell order fills!)

BuyDipPosition:
  State: ACTIVE → COMPLETED ✅
  
Profit Calculation:
  Buy average: $67,131
  Sell price: $67,890
  Profit %: (67,890 - 67,131) / 67,131 = 1.13%
  
  Investment: $300 USDT (3 DCA levels filled)
  Profit: $300 × 1.13% = $3.39 USDT
```

---

## Configuration Example

```python
buy_dip_config = {
    # Symbol and candles
    "symbol": "BTCUSDT",
    "candle_interval": "15m",  # Use Binance 15-min klines
    "candle_buffer_size": 100,  # Keep last 100 candles
    
    # Budget Management (NEW!)
    "initial_budget": 10000,              # Starting USDC
    "order_size_percentage": 2.0,         # 2% of available per order
    "min_order_size": 10,                 # Minimum $10 per order
    
    # Rising pattern detection
    "rising_consecutive": 3,      # 3 consecutive highs OR...
    "rising_min_gain_pct": 0.25,  # ...0.25% total gain
    "rising_use_high": True,      # Compare highs (not closes)
    
    # Top confirmation
    "pullback_threshold_pct": 0.35,  # 0.35% min drawdown
    "use_atr": True,                 # Enable ATR adjustment
    "atr_period": 14,                # 14 candles for ATR
    "atr_multiplier": 0.8,           # Threshold = max(0.35%, 0.8×ATR%)
    
    # DCA ladder (sequential placement!)
    "dca_distances_pct": [1.618, 2.718, 3.142],  # φ, e, π (golden, Euler, pi)
    "max_dca_levels": 3,                          # Up to 3 DCA orders per position
    
    # Exit
    "take_profit_pct": 0.0,  # Sell at top price (breakeven from top, profit from avg)
}
```

**Key Changes:**
- ✅ Budget management: percentage-based sizing
- ✅ Sequential DCA: One order at a time, wait for fill
- ✅ Removed fixed order sizes (now dynamic)
- ✅ Min order size prevents dust orders

---

## Differences from HP Manager

| Feature | HP Manager | Buy Dip |
|---------|-----------|---------|
| **Goal** | Scale into position, hedge at top | Buy dips, sell at top |
| **Entry** | Market/limit at start price | Limit at pullback |
| **Position Building** | Buy up as price rises | Buy down as price drops |
| **Exit** | Complex hedge logic | Simple: sell at top |
| **Complexity** | 11 states, 80+ transitions | 5 states, ~15 transitions |
| **Risk** | Can be underwater if drop | Lower cost avg via DCA |
| **States** | IDLE, INITIAL_BUY, BUYING, HEDGED, etc. | WATCHING, POTENTIAL_TOP, ACTIVE, etc. |

**Buy Dip is much simpler!**

---

## Common Questions

### Q: Why sell at breakeven (top)? Why not profit target?

**A:** Simplicity and capital efficiency.
- Breakeven = no risk, free trades
- Quick exits = capital available for next dip
- Can configure profit target if desired (e.g., +0.5% above top)

### Q: What if price never returns to top?

**A:** Position stays open.
- Can manually close at a loss
- Can adjust sell price lower
- Future strategy: trailing stop or time-based exit

### Q: How many positions run simultaneously?

**A:** Configurable per symbol.
- Conservative: 1 position at a time
- Aggressive: 3-5 positions
- Each position tracks its own top

### Q: What if I run out of DCA levels?

**A:** Position waits.
- All DCA filled = max investment reached
- Sell order active, waiting for recovery
- No new orders until this position closes

### Q: Can I use different candle intervals?

**A:** Yes!
- 5-min: More signals, more noise
- 15-min: Balanced (recommended)
- 1-hour: Fewer signals, higher confidence

---

## Complete Scenario Walkthrough with Budget Tracking

**Starting State:**
- Budget: $10,000 available
- Config: 2% per order, DCA at [φ=1.618%, e=2.718%, π=3.142%], sell at top
- BTC rising from $67,000 → $67,890

### Position 1: Perfect Fill Scenario

**T1: Rising detected → HWM at $67,890**
```
Order 1: Place BUY at $66,792.78 (1.618% below top)
  Calculation: $67,890 × (1 - 0.01618) = $66,792.78
  Size: $10,000 × 2% = $200
  Budget locked: $200
  Available: $9,800
```

**T2: Order 1 fills**
```
Position 1: ACTIVE (top confirmed!)
  Entry: $66,792.78
  Investment: $200
  Sell order: $67,890 (at top price)
  
Order 2: Place BUY at $66,046.50 (2.718% below top)
  Calculation: $67,890 × (1 - 0.02718) = $66,046.50
  Size: $9,800 × 2% = $196
  Budget locked: $196
  Available: $9,604
```


**T3: Order 2 fills**
```
Position 1 updated:
  Avg entry: $66,419.64 (weighted average)
  Investment: $396
  Sell updated quantity (sell at $67,890, same price)

Order 3: Place BUY at $65,758.30 (3.142% below top)
  Calculation: $67,890 × (1 - 0.03142) = $65,758.30
  Size: $9,604 × 2% = $192
  Budget locked: $192
  Available: $9,412
```

**T4: Sell fills at $67,890**
```
Position 1: CLOSED
  Entry avg: $66,419.64
  Exit: $67,890 (top price)
  Profit per unit: $1,470.36
  Total investment: $396
  Realized P&L: ~$22 profit (depending on quantities)
  
Order 3: CANCELLED (position closed!)
  Released: $192 (unlocked)
  
Budget updates:
  Total released: $780 ($588 invested + $192 cancelled)
  Profit: +$677
  Available: $10,677
  
Position 1: Lifecycle COMPLETE
```

### Position 2: New Top Detection

**T5: BTC forms new top at $68,200**
```
Rising detected → New HWM
Order 5: Place BUY at $68,200
  Size: $10,677 × 2% = $214
  Budget locked: $214
  Available: $10,463
```

**T6: Order 5 fills**
```
Position 2: ACTIVE (new position!)
  Entry: $68,200
  Investment: $214
  Sell order: $68,882 (+1%)

Order 6: Place BUY at $67,859 (-0.5%)
  Size: $10,463 × 2% = $209
  Budget locked: $209
  Available: $10,254
```

**T7: Sell fills at $68,882**
```
Position 2: CLOSED
  Realized P&L: +$682 profit
  
Order 6: CANCELLED (position closed!)
  Released: $209 (unlocked)
  
Budget updates:
  Total released: $423 ($214 invested + $209 cancelled)
  Profit: +$682
  Available: $11,359
  
Total profit: $1,359 from two complete positions!
```

### Budget Tracking Through Multiple Positions

**Key Observations:**
1. **Sell = Cancel all orders** - Position lifecycle complete
2. **Each position independent** - New top detection starts fresh
3. **Budget percentages recalculated** at each order placement
4. **Locked funds released** on cancel OR fill
5. **Profit compounds** into available budget
6. **Order cancellation returns funds** immediately

**Concurrent Positions Example:**
```
Position A: 3 filled orders ($200 + $196 + $192 = $588 locked)
Position B: 1 filled order ($198 locked)
Position C: 2 pending orders ($194 + $190 = $384 locked)

Total locked: $1,170
Available: $8,830
Next order: $8,830 × 2% = $177
```

---

## Next Steps

1. **Read:** `BUY_DIP_CORRECTED_DESIGN.md` for critical corrections
2. **Read:** `BUY_DIP_STRATEGY_DESIGN.md` for technical details
3. **Understand:** `BUY_DIP_KEY_INSIGHT.md` for core concept
4. **Storage:** `BUY_DIP_CANDLE_STORAGE.md` for implementation details
5. **Implement:** Tests first (TDD), then components
6. **Integrate:** WebSocket → Detection → Position → Database
7. **Test:** Backtest with historical data
8. **Deploy:** Live trading with small sizes

---

## Status

- [x] Strategy designed
- [x] Documentation written
- [x] Critical corrections applied
- [ ] Tests updated for sequential orders and budget (next step!)
- [ ] BudgetManager implemented
- [ ] PositionBudgetTracker implemented
- [ ] Core components implemented
- [ ] Integration with infrastructure
- [ ] GUI for configuration
- [ ] Live trading

**Ready to update tests and start TDD implementation!** 🚀
