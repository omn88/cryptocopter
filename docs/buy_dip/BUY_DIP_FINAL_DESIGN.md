# Buy Dip Strategy - Final Design Summary

## Critical Design Principles

### 1. Mathematical Constants for DCA Distances
- **Order 1:** φ (phi) = 1.618% below top (golden ratio)
- **Order 2:** e (Euler) = 2.718% below top (natural log base)
- **Order 3:** π (pi) = 3.142% below top (circle constant)
- Configurable in GUI, but defaults have mathematical significance

### 2. ONE Pending Order at a Time
**CRITICAL CONSTRAINT:**
- Never have multiple pending buy orders simultaneously
- Order execution report triggers next order placement
- Sequential: Order 1 → Fill → Order 2 → Fill → Order 3 → Fill

**Why:**
- Capital efficiency (only lock funds for current order)
- Simpler state management (no concurrent tracking)
- Adaptive (if price doesn't dip far enough, fewer orders naturally)
- Clear flow (Fill → Place Next → Repeat)

### 3. Order Placement BELOW Top
- Orders placed at mathematical distances BELOW the detected top
- NOT at the top price itself
- Buy the dip, not the top!

### 4. Sell at Top Price
- Sell order placed at the detected top price
- Breakeven from top perspective
- Profit from average entry price perspective

### 5. Top Confirmation
- Top detection (rising + HWM) = POTENTIAL_TOP state
- First order FILL = TOP CONFIRMED (position ACTIVE)
- Market validation, not just pattern

### 6. Sequential Order Triggers
- Order fill execution report is the trigger
- Place next order immediately after fill
- One at a time until max DCA reached

---

## Complete Lifecycle Example

### Initial State
```
Budget: $10,000 available
Config: 2% per order, 3 DCA levels [φ, e, π]
Symbol: BTCUSDC
```

### Step 1: Rising Detection
```
Candles: $67,000 → $67,200 → $67,400 → $67,890
Detection: 3 consecutive highs OR 0.25% total gain
Result: High Watermark = $67,890
State: WATCHING → Evaluating for potential top
```

### Step 2: Place Order 1
```
Top detected: $67,890
Calculate Order 1: $67,890 × (1 - 0.01618) = $66,792.78
Size: $10,000 × 2% = $200
Action: Place limit buy at $66,792.78
State: POTENTIAL_TOP
Pending: [Order 1]  ← Only one!
Budget: Available $9,800, Locked $200
```

### Step 3A: Order 1 Fills (Top Confirmed!)
```
Execution report: Order 1 filled at $66,792.78
State: POTENTIAL_TOP → ACTIVE
Position:
  - Entry: $66,792.78
  - Investment: $200
  - Top price: $67,890

Actions:
  1. Create sell order at $67,890 (top price)
  2. Calculate Order 2: $67,890 × (1 - 0.02718) = $66,046.50
  3. Size: $9,800 × 2% = $196
  4. Place limit buy at $66,046.50

Pending: [Order 2]  ← Only one!
Budget: Available $9,604, Locked $196
```

### Step 3B: Alternative - Top Invalidated
```
Order 1 still pending at $66,792.78
Price rises: $67,890 → $68,100 (new high!)

Actions:
  1. Cancel Order 1 (never filled, no cost!)
  2. Release locked funds: $200
  3. Update HWM: $68,100
  4. Calculate new Order 1: $68,100 × (1 - 0.01618) = $66,998.22
  5. Place at new price

State: Still POTENTIAL_TOP
Pending: [New Order 1]  ← Only one!
Budget: Available $10,000, Locked $200 (for new order)
```

### Step 4: Order 2 Fills
```
Execution report: Order 2 filled at $66,046.50
Position updated:
  - Average entry: ($66,792.78 + $66,046.50) / 2 = $66,419.64
  - Investment: $396
  - Top price: $67,890

Actions:
  1. Update sell quantity (now 2 orders worth)
  2. Calculate Order 3: $67,890 × (1 - 0.03142) = $65,758.30
  3. Size: $9,604 × 2% = $192
  4. Place limit buy at $65,758.30

Pending: [Order 3]  ← Only one!
Budget: Available $9,412, Locked $192
```

### Step 5: Order 3 Fills (Max DCA Reached)
```
Execution report: Order 3 filled at $65,758.30
Position updated:
  - Average entry: ~$66,199.19 (weighted)
  - Investment: $588
  - Top price: $67,890

Actions:
  1. Update sell quantity (now 3 orders worth)
  2. Max DCA reached (3 configured)
  3. NO next order placed

Pending: []  ← None!
Budget: Available $9,412, Locked $0
Waiting: For price recovery to $67,890
```

### Step 6: Price Recovers
```
Price movement: $65,758 → $66,500 → $67,200 → $67,890

Sell order triggers at $67,890
Execution report: Sell filled

Position closed:
  - Entry average: $66,199.19
  - Exit: $67,890
  - Profit per unit: $1,690.81
  - Total profit: ~$30 (depending on quantities)

Actions:
  1. Release all locked funds: $0 (nothing locked)
  2. Return invested capital: $588
  3. Add profit: $30
  4. Cancel any remaining orders: None exist

State: ACTIVE → COMPLETED
Budget: Available $10,030, Locked $0
Result: +$30 profit, 0.3% return on capital
```

---

## State Machine

```
┌─────────────┐
│  WATCHING   │  Monitoring candles for rising pattern
└──────┬──────┘
       │ Rising detected + HWM identified
       ↓
┌─────────────────┐
│ POTENTIAL_TOP   │  Order 1 pending (φ below top)
└────┬────────┬───┘
     │        │
     │        └─→ New high → Cancel + replace at new top
     │
     │ Order 1 fills
     ↓
┌─────────────────┐
│     ACTIVE      │  Position confirmed, sequential orders
└────┬────────────┘
     │
     ├─→ Order 2 placed (e below) → fills → Order 3 placed (π below)
     │
     ├─→ All orders filled → Waiting for recovery
     │
     │ Sell fills
     ↓
┌─────────────────┐
│   COMPLETED     │  Position closed, profit realized
└─────────────────┘
```

---

## Key Assertions (For Tests)

### Order Count Constraints
```python
# At any time, check pending orders
pending = position.pending_orders
assert len(pending) <= 1, "NEVER have more than 1 pending buy order"

# Specific states
if position.state == "POTENTIAL_TOP":
    assert len(pending) == 1, "Should have Order 1 pending"

if position.state == "ACTIVE" and position.filled_orders < max_dca:
    assert len(pending) <= 1, "Should have 0 or 1 pending (between fills)"

if position.state == "ACTIVE" and position.filled_orders == max_dca:
    assert len(pending) == 0, "Should have 0 pending (max reached)"
```

### Order Price Validation
```python
top = position.top_price

order_1_expected = top * (1 - 0.01618)  # φ
order_2_expected = top * (1 - 0.02718)  # e
order_3_expected = top * (1 - 0.03142)  # π

assert abs(order_1.price - order_1_expected) < 1.0
assert abs(order_2.price - order_2_expected) < 1.0
assert abs(order_3.price - order_3_expected) < 1.0
```

### Sequential Trigger Validation
```python
# After Order N fills, Order N+1 should be placed
await sim.fill_order(order_1.order_id, order_1.price)
await sim.wait_for_order_placed(position.position_id)
assert len(position.pending_orders) == 1, "Order 2 should now be pending"
```

---

## Configuration Structure

```python
buy_dip_config = {
    # Symbol
    "symbol": "BTCUSDC",
    "candle_interval": "15m",
    
    # Budget
    "initial_budget": 10000,          # Starting USDC
    "order_size_percentage": 2.0,     # 2% of available per order
    "min_order_size": 10,             # Minimum $10
    
    # Rising detection
    "rising_consecutive": 3,          # 3 consecutive highs OR...
    "rising_min_gain_pct": 0.25,      # ...0.25% total gain
    "rising_use_high": True,          # Compare highs (not closes)
    
    # Top confirmation (HWM)
    "pullback_threshold_pct": 0.35,   # Min 0.35% drawdown (not used after fill!)
    "use_atr": True,                  # Enable ATR adjustment
    "atr_period": 14,                 # 14 candles
    "atr_multiplier": 0.8,            # Threshold = max(0.35%, 0.8×ATR%)
    
    # DCA ladder (mathematical constants!)
    "dca_distances_pct": [1.618, 2.718, 3.142],  # φ, e, π
    "max_dca_levels": 3,              # Up to 3 orders
    
    # Exit
    "take_profit_pct": 0.0,           # Sell at top (not above)
}
```

---

## Implementation Checklist

### Components to Build
- [ ] `CandleBuffer` - Ring buffer for candles
- [ ] `ATR` - Average True Range calculator
- [ ] `RisingCandleDetector` - Pattern recognition
- [ ] `HighWatermarkDetector` - Top detection
- [ ] `BudgetManager` - Fund allocation
- [ ] `BuyDipPosition` - Position state machine
- [ ] `BuyDipStrategy` - Main strategy orchestrator

### Critical Implementation Points
1. **BuyDipPosition state machine:**
   - Ensure `pending_orders` list NEVER exceeds length 1
   - `on_order_fill()` triggers next order placement
   - `place_next_order()` checks if max DCA reached

2. **BudgetManager:**
   - `calculate_order_size()` returns None if insufficient funds
   - `lock_funds()` called when order placed
   - `release_funds()` called when order cancelled OR filled

3. **Sequential order logic:**
   ```python
   def on_order_fill(self, execution_report):
       """Handle order fill - triggers next order placement."""
       self.filled_orders.append(execution_report)
       self.update_position_metrics()
       
       if len(self.filled_orders) < self.max_dca_levels:
           self.place_next_order()  # Sequential!
       else:
           # Max DCA reached, wait for recovery
           pass
   ```

4. **Order placement:**
   ```python
   def place_next_order(self):
       """Place next sequential order."""
       assert len(self.pending_orders) == 0, "Should have no pending orders!"
       
       order_index = len(self.filled_orders)
       distance_pct = self.dca_distances[order_index]  # φ, e, or π
       price = self.top_price * (1 - distance_pct / 100)
       
       order = self.broker.place_limit_buy(price, quantity)
       self.pending_orders.append(order)
       
       assert len(self.pending_orders) == 1, "Should have exactly 1 pending!"
   ```

---

## Summary

✅ **Mathematical constants (φ, e, π)** for DCA distances  
✅ **ONE pending order at a time** - strict constraint  
✅ **Orders BELOW top** - buying the dip  
✅ **Sell AT top** - breakeven from top, profit from average  
✅ **Fill triggers next order** - sequential placement  
✅ **Top confirmation via fill** - market validation  

**Philosophy:** Simple, elegant, adaptive. Let the market decide position size through sequential fills. Use nature's proportions for order spacing. One order at a time keeps it clean.

**Ready for implementation!** 🎯
