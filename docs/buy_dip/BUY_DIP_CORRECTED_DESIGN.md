# Buy Dip Strategy - Corrected Design

## Critical Design Points

### 1. Order Placement Timing and Distance

**IMPORTANT:** 
- ✅ Send first buy order IMMEDIATELY when potential top is detected
- ✅ Order placed BELOW top at mathematical constant distance (φ = 1.618%)
- ✅ Order fill = price dipped enough → top confirmed
- ✅ If new higher top → cancel old order, send new one at new top × (1 - φ%)

**Mathematical Constants for DCA Ladder:**
- **Order 1:** top × (1 - 1.618%) = φ distance (golden ratio)
- **Order 2:** top × (1 - 2.718%) = e distance (Euler's number)
- **Order 3:** top × (1 - 3.142%) = π distance (pi)

**Example:**
```
Top detected: $10,000
Order 1: $10,000 × (1 - 0.01618) = $9,838.20
Order 2: $10,000 × (1 - 0.02718) = $9,728.20
Order 3: $10,000 × (1 - 0.03142) = $9,685.80
```

**NOT:**
- ❌ Place orders AT the top price
- ❌ Wait for pullback to send order
- ❌ Send all DCA orders at once

### 2. Sequential Order Strategy (ONE AT A TIME!)

**CRITICAL: Only one pending buy order at a time**

**Flow:**
1. Detect potential top → Send Buy Order 1 at (top × (1 - 1.618%))
2. Order 1 fills → Create sell at top + Send Buy Order 2 at (top × (1 - 2.718%))
3. Order 2 fills → Update sell quantity + Send Buy Order 3 at (top × (1 - 3.142%))
4. Order 3 fills → Update sell quantity + Send Order 4 (if configured)
5. Continue until max orders reached or position closed

**Key Principle:** **NEVER have multiple pending buy orders simultaneously**

**Why ONE at a time:**
- Capital efficiency (only lock funds for current order)
- Simpler state management (no concurrent order tracking)
- Adaptive to market (if price doesn't dip far enough, fewer orders placed)
- Budget management is straightforward
- Order execution report is trigger for next order

**Example State Progression:**
```
State: POTENTIAL_TOP
  Pending orders: [Order 1 at $66,792]  ← Only one!
  
Order 1 fills → State: ACTIVE
  Pending orders: [Order 2 at $66,046]  ← Only one!
  
Order 2 fills → State: ACTIVE
  Pending orders: [Order 3 at $65,758]  ← Only one!
  
Order 3 fills → State: ACTIVE
  Pending orders: []  ← All filled, waiting for recovery
```

### 3. Sell Order Behavior

**CRITICAL:** When sell order fills at top price:
- Price crosses ABOVE the top (sell executes)
- ✅ **CANCEL ALL** remaining buy orders immediately
- ✅ Position lifecycle is COMPLETE
- ✅ No orphaned orders left behind
- ❌ **DO NOT** treat sell as "new higher top" for invalidation

**Reasoning:**
- Sell fills = this position is DONE
- Remaining buy orders belong to THIS closed position
- Must clean up to avoid orphaned orders
- Clean slate for next opportunity

**Important Distinction:**

**Scenario A: Top NOT confirmed (POTENTIAL_TOP state)**
```
Order 1 at $9,838 (φ below $10k top) - pending
Price crosses above potential top to $10,100
→ Invalidation: Cancel Order 1
→ Recreate: $10,100 × (1 - 0.01618) = $9,936.50
→ Position continues
```

**Scenario B: Top confirmed (ACTIVE state)**
```
Orders 1-2 filled, Order 3-4 pending
Sell fills (position done)
→ Closure: Cancel Orders 3-4
→ Position complete
```

### 4. Budget Management

**Dynamic percentage-based sizing:**
```
Available budget: $10,000
Trade percentage: 2%

Order 1: $10,000 × 2% = $200
  (After sent: available = $9,800)

Order 2: $9,800 × 2% = $196
  (After sent: available = $9,604)

Sell fills: +$200 received
  (Now: available = $9,804)
```

**Budget operations:**
- ✅ Add funds: Increase available budget
- ✅ Withdraw gains: Decrease available budget
- ✅ Insufficient funds: Wait gracefully (no errors)

---

## Corrected Flow

### Scenario: Complete Position Lifecycle

#### Step 1: Detect Potential Top
```
15-min candles (highs):
$67,000 → $67,200 → $67,400 → $67,600 (3 consecutive rising)

RisingCandleDetector: ✅ Pattern confirmed

HighWatermarkDetector:
  HWM: $67,600
  Status: POTENTIAL TOP
```

**Action: Send First Buy Order IMMEDIATELY**
```
Available budget: $10,000
Trade size: 2% = $200

Order 1:
  Side: BUY
  Price: $67,600 (AT the top, not below)
  Quantity: $200 / $67,600 = 0.00295858 BTC
  Status: OPEN

Available budget: $10,000 - $200 = $9,800
Position state: POTENTIAL_TOP
```

#### Step 2: Price Drops, Order Fills (TOP CONFIRMED)
```
Price: $67,600 → $67,400 → $67,200

Order 1 fills at $67,600

Position state: POTENTIAL_TOP → ACTIVE ✅
Top confirmed: $67,600
```

**Actions:**
```
1. Create sell order:
   Price: $67,600 (same as buy = breakeven)
   Quantity: 0.00295858 BTC
   
2. Send second buy order:
   Available budget: $9,800
   Trade size: 2% = $196
   Distance: 0.5% below first order
   
   Order 2:
     Price: $67,600 × (1 - 0.005) = $67,262
     Quantity: $196 / $67,262 = 0.00291338 BTC
     Status: OPEN
     
   Available budget: $9,800 - $196 = $9,604
```

#### Step 3: Deeper Dip, Order 2 Fills
```
Price: $67,200 → $67,000 → $66,900

Order 2 fills at $67,262

Total position:
  Order 1: 0.00295858 BTC @ $67,600
  Order 2: 0.00291338 BTC @ $67,262
  Average: $67,431
  Total qty: 0.00587196 BTC
```

**Actions:**
```
1. Update sell order:
   Price: $67,600 (unchanged - still at top)
   Quantity: 0.00587196 BTC (updated!)
   
2. Send third buy order:
   Available budget: $9,604
   Trade size: 2% = $192
   Distance: 1.0% below first order
   
   Order 3:
     Price: $67,600 × (1 - 0.010) = $66,924
     Quantity: $192 / $66,924 = 0.00286878 BTC
     Status: OPEN
     
   Available budget: $9,604 - $192 = $9,412
```

#### Step 4: Price Recovers, Sell Fills
```
Price: $66,900 → $67,200 → $67,400 → $67,600

Sell order fills at $67,600

Total sold: 0.00587196 BTC @ $67,600 = $396.90

Profit:
  Invested: $200 + $196 = $396
  Received: $396.90
  Profit: $0.90 (0.23%)
```

**Actions:**
```
1. Add sold amount to budget:
   Available budget: $9,412 + $396.90 = $9,808.90
   
2. Keep Order 3 active!
   ✅ DO NOT CANCEL (it's below top, still valid)
   ✅ Price crossed top for SELL, not new high
   
3. Position state: COMPLETED
   
4. Order 3 remains:
   - Can create NEW position if it fills
   - Or cancel if new actual top is detected
```

---

## State Machine (Corrected)

### WATCHING
**Monitoring:** Rising patterns, HWM

**Trigger:** Potential top detected (3 rising candles OR X% gain)

**Action:**
- Calculate order size from budget
- Send Buy Order 1 at HWM price
- Transition to POTENTIAL_TOP

---

### POTENTIAL_TOP
**Waiting:** First order to fill

**Two outcomes:**

**A) Order Fills** → TOP CONFIRMED
- Transition to ACTIVE
- Create sell order at top price
- Send Order 2 (X% below Order 1)

**B) New Higher Top Detected**
- Cancel Order 1
- Update HWM to new top
- Send new Order 1 at new top
- Stay in POTENTIAL_TOP

---

### ACTIVE
**Managing:** Open position with sell order

**Sequential buy orders:**
- Order N fills → Send Order N+1
- Update sell quantity after each fill
- Continue until max orders OR budget exhausted

**Sell order fills:**
- Add funds to budget
- Transition to COMPLETED
- **Keep unfilled buy orders active**

**New higher top while ACTIVE:**
- ❌ **Ignore if it's from sell execution**
- ✅ Only cancel if it's actual new market high

---

### COMPLETED
**Position closed, but:**
- Unfilled buy orders may remain active
- Can create new position if they fill
- Or cancel if strategy detects new opportunity

---

## Budget Manager Design

### Core Concept
```python
class BudgetManager:
    def __init__(self, initial_budget: float, trade_percentage: float):
        self.total_budget = initial_budget
        self.available_budget = initial_budget
        self.locked_budget = 0.0  # In pending orders
        self.trade_percentage = trade_percentage / 100.0
        
    def calculate_order_size(self) -> float:
        """Calculate next order size based on available budget"""
        return self.available_budget * self.trade_percentage
        
    def lock_funds(self, amount: float) -> bool:
        """Lock funds for pending order"""
        if amount > self.available_budget:
            return False  # Insufficient funds
            
        self.available_budget -= amount
        self.locked_budget += amount
        return True
        
    def release_funds(self, amount: float):
        """Release funds from filled/cancelled order"""
        self.locked_budget -= amount
        self.available_budget += amount
        
    def add_budget(self, amount: float):
        """Add funds to strategy"""
        self.total_budget += amount
        self.available_budget += amount
        
    def withdraw(self, amount: float) -> bool:
        """Withdraw funds from strategy"""
        if amount > self.available_budget:
            return False
            
        self.total_budget -= amount
        self.available_budget -= amount
        return True
```

### Budget Tracking

**Order placed:**
```python
order_size = budget.calculate_order_size()  # 2% of available
if budget.lock_funds(order_size):
    place_order(order_size)
else:
    # Insufficient funds - wait gracefully
    log.info("Insufficient funds, waiting for fills/withdrawals")
```

**Order filled (buy):**
```python
# Funds stay locked (now in position)
# Don't release until sell
```

**Order cancelled:**
```python
budget.release_funds(order_size)
# Funds available again
```

**Order filled (sell):**
```python
budget.release_funds(original_buy_amount)
# Position closed, funds available
```

**Add funds:**
```python
budget.add_budget(1000)  # Add $1000 to strategy
# Immediately available for new orders
```

**Withdraw gains:**
```python
if budget.withdraw(500):  # Withdraw $500
    transfer_to_wallet(500)
```

---

## Multiple Positions Management

### Challenge
```
Position 1: $200 locked (Order 1 pending)
Position 2: $196 locked (Order 1 filled, Order 2 pending)
Position 3: $192 locked (Order 1 pending)

Total locked: $588
Available: $9,412

New opportunity detected:
  Next order size: $9,412 × 2% = $188 ✅ (sufficient)
```

### Position Budget Tracking

```python
class PositionBudgetTracker:
    """Track budget per position"""
    
    def __init__(self, position_id: str, budget_manager: BudgetManager):
        self.position_id = position_id
        self.budget = budget_manager
        self.invested = 0.0
        self.locked_orders = {}
        
    def place_next_order(self, order_id: str) -> Optional[float]:
        """Calculate and lock funds for next order"""
        size = self.budget.calculate_order_size()
        
        if not self.budget.lock_funds(size):
            return None  # Insufficient funds
            
        self.locked_orders[order_id] = size
        return size
        
    def on_buy_fill(self, order_id: str, fill_amount: float):
        """Track filled buy order"""
        self.invested += fill_amount
        # Funds stay locked (in position)
        
    def on_sell_fill(self, total_received: float):
        """Position closed, release all funds"""
        for order_id, amount in self.locked_orders.items():
            self.budget.release_funds(amount)
            
        # Profit/loss reflected in received amount
        self.locked_orders.clear()
        self.invested = 0.0
```

---

## Top Invalidation Logic (Clarified)

### Scenario 1: New High BEFORE First Fill
```
Potential top: $67,600
Order 1 placed at $67,600 (pending)

Price: $67,800 (NEW HIGH)

Action:
  ✅ Cancel Order 1
  ✅ Release locked funds
  ✅ Update HWM to $67,800
  ✅ Send new Order 1 at $67,800
```

### Scenario 2: New High WHILE ACTIVE
```
Position active:
  Top: $67,600
  Order 1 filled at $67,600
  Order 2 pending at $67,262
  Sell pending at $67,600

Price: $67,900 (NEW HIGH)

Question: Is this a new opportunity or noise?

Logic:
  If price > top + threshold (e.g., 0.2%):
    ✅ New higher top
    ✅ Cancel unfilled buy orders (Order 2)
    ✅ Keep sell order (exit current position first)
    
  After sell fills:
    ✅ Start watching new top at $67,900
```

### Scenario 3: Sell Fills (Price Crosses Top)
```
Position active:
  Top: $67,600
  Order 3 pending at $66,924
  Sell pending at $67,600

Price: $67,600 (SELL FILLS)

Price momentarily at/above $67,600

Action:
  ✅ Position COMPLETED
  ✅ Funds released to budget
  ❌ DO NOT cancel Order 3 (it's still valid opportunity)
  ❌ DO NOT treat as "new top"
  
Order 3 remains:
  - If fills: Creates NEW position with top = $67,600
  - If new actual top detected: Gets cancelled
```

---

## Configuration Example (Updated)

```python
buy_dip_config = {
    # Symbol and candles
    "symbol": "BTCUSDT",
    "candle_interval": "15m",
    
    # Budget management
    "initial_budget_usdt": 10000,
    "trade_percentage": 2.0,  # 2% of available per order
    "allow_budget_additions": True,
    "allow_withdrawals": True,
    
    # Rising detection (for potential top)
    "rising_consecutive": 3,
    "rising_min_gain_pct": 0.25,
    "rising_use_high": True,
    
    # Order placement
    "first_order_at_top": True,  # NOT below top
    "sequential_orders": True,   # One at a time
    "max_orders_per_position": 5,
    
    # DCA spacing (from first order)
    "dca_distances_pct": [0.5, 1.0, 1.5, 2.0],  # Order 2, 3, 4, 5
    
    # Exit
    "sell_at_top": True,  # Breakeven
    
    # Top invalidation
    "new_top_threshold_pct": 0.2,  # Need +0.2% to cancel orders
    "keep_orders_after_sell": True,  # Don't cancel on sell
    
    # Multiple positions
    "max_concurrent_positions": 20,
    "graceful_budget_exhaustion": True,  # Wait, don't error
}
```

---

## Example: Budget Through Complete Cycle

```
Initial state:
  Total budget: $10,000
  Available: $10,000
  Trade %: 2%

─────────────────────────────────────────

Potential Top 1 detected at $67,600:
  Order size: $10,000 × 2% = $200
  Send Buy Order 1
  
  Available: $9,800
  Locked: $200

─────────────────────────────────────────

Order 1 fills:
  Invested: $200
  Send Order 2: $9,800 × 2% = $196
  
  Available: $9,604
  Locked: $396

─────────────────────────────────────────

Order 2 fills:
  Invested: $396
  Send Order 3: $9,604 × 2% = $192
  
  Available: $9,412
  Locked: $588

─────────────────────────────────────────

Potential Top 2 detected at $68,100 (NEW OPPORTUNITY):
  Order size: $9,412 × 2% = $188
  Send Buy Order 1 (Position 2)
  
  Available: $9,224
  Locked: $776 (Position 1: $588, Position 2: $188)

─────────────────────────────────────────

Position 1 sell fills: Received $400
  Release: $588
  
  Available: $9,224 + $588 = $9,812
  Locked: $188 (only Position 2)
  
  Profit: $400 - $396 = $4

─────────────────────────────────────────

User adds funds: +$1,000
  Available: $9,812 + $1,000 = $10,812
  Total budget: $11,000

─────────────────────────────────────────

User withdraws gains: -$500
  Available: $10,812 - $500 = $10,312
  Total budget: $10,500
```

---

## Edge Cases

### 1. Budget Exhausted
```python
def place_next_order(self):
    order_size = budget.calculate_order_size()
    
    if not budget.lock_funds(order_size):
        log.info(f"Insufficient funds for order (need ${order_size:.2f}, have ${budget.available:.2f})")
        self.state = "WAITING_FOR_FUNDS"
        return
        
    # Continue with order placement
```

### 2. All Positions Closed, Orders Remain
```
20 positions all sold
Budget: $10,000 (back to start)
Remaining orders: 15 unfilled buy orders (from old positions)

Action:
  ✅ Keep monitoring these orders
  ✅ If they fill, create new positions
  ✅ If new tops detected, cancel and replace
```

### 3. Withdrawal Request Exceeds Available
```python
def request_withdrawal(self, amount: float) -> bool:
    if amount > budget.available_budget:
        log.error(f"Cannot withdraw ${amount}, only ${budget.available} available")
        return False
        
    budget.withdraw(amount)
    return True
```

---

## Summary of Key Changes

| Aspect | Previous Understanding | Corrected Design |
|--------|----------------------|------------------|
| **Order Timing** | After pullback | IMMEDIATELY at top |
| **Order Sequence** | All at once | One at a time |
| **Confirmation** | Pullback threshold | First order fill |
| **Sell Behavior** | Keep unfilled orders | **Cancel ALL orders** (position done!) |
| **Budget** | Fixed per order | % of available |
| **Additions** | Not mentioned | Dynamic add/withdraw |
| **Exhaustion** | Error | Graceful wait |

---

This corrected design matches your vision perfectly! Should I now update the README_FIRST and test suite to reflect this?
