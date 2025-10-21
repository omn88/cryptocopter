# Buy Dip Strategy - Complete Documentation

**Status**: ✅ Core logic implemented and tested (10/10 tests passing)  
**Next Step**: Integration with AsyncApp and BinanceClient

---

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Multi-Position Design](#multi-position-design)
3. [Test Results](#test-results)
4. [Integration Roadmap](#integration-roadmap)

---

## Architecture Overview

### Multi-Position Manager for Single Symbol

The Buy Dip strategy manages **multiple concurrent positions** on the same symbol, each tracking a different historical top.

```
BuyDipStrategy for BTCUSDC
├── Position 1 (Top: 10,000) - ACTIVE
│   ├── Buy Order 1: FILLED @ 9,838
│   ├── Buy Order 2: FILLED @ 9,728
│   ├── Buy Order 3: PENDING @ 9,686
│   └── Sell Order: Will place at 10,000
│
├── Position 2 (Top: 9,900) - ACTIVE
│   ├── Buy Order 1: FILLED @ 9,740
│   ├── Buy Order 2: PENDING @ 9,631
│   └── Sell Order: Will place at 9,900
│
├── Position 3 (Top: 8,500) - POTENTIAL_TOP
│   └── Buy Order 1: PENDING @ 8,363
│
└── Position 4 - WATCHING
    └── Detecting next rising pattern...
```

### Key Rules

1. **Multiple Positions Per Symbol** ✅
   - Each position tracks different historical top
   - Positions work independently through their lifecycle

2. **ONE WATCHING Position** ✅
   - Only one position detects next rising pattern
   - When top confirmed → becomes POTENTIAL_TOP
   - New WATCHING position created

3. **ONE Pending Order Per Position** ✅
   - Sequential DCA: Order 1 → fills → Order 2 → fills → Order 3
   - Across positions: Multiple pending orders allowed (different positions)

4. **Shared Budget** ✅
   - All positions share same budget pool
   - Budget locked when order placed
   - Budget released when order cancelled/filled

---

## Multi-Position Design

### Position Lifecycle

```
WATCHING → POTENTIAL_TOP → ACTIVE → COMPLETED

WATCHING:
- Monitors candles for rising pattern
- Only ONE position in this state
- Creates new position when rising detected

POTENTIAL_TOP:
- Top confirmed by HWM detector
- First DCA order placed (φ = 1.618% below top)
- Waiting for confirmation fill

ACTIVE:
- At least one order filled
- Sequential DCA progression (e, π levels)
- Sell order placed when all DCA filled

COMPLETED:
- Sell order filled
- Budget + PnL released
- Position archived
```

### Example Scenario (Your 11-Step Flow)

```
Step 1-3: Price 10k → 9k
├── Position 1 (Top: 10k) created
└── Orders filling at 9.8k, 9.7k, 9.6k

Step 4-5: Price rises to 9.9k, drops to 9.5k
├── Position 1 sell placed @ 9.8k (doesn't fill)
└── Position 1 waiting for recovery

Step 6: NEW top detected @ 9.9k
├── Position 2 created (Top: 9.9k)
└── Position 3 starts WATCHING

Step 7: Price drops to 8k
├── Position 1 orders: [FILLED, FILLED, FILLED]
├── Position 2 orders: [FILLED, FILLED, PENDING @ 9.5k]
└── Both positions active simultaneously!

Step 8: Price rises to 9.85k
├── Position 1 sell: PENDING @ 9.8k
├── Position 2 sell: PENDING @ 9.7k (9.9k * 0.98)
└── Both waiting to fill

Step 9: Price @ 9.95k
├── Position 2 sell fills @ 9.7k → COMPLETED
└── Position 1 still waiting

Step 10: Price crosses 10k
├── Position 1 sell fills @ 9.8k → COMPLETED
└── All positions closed

Step 11: Result
└── Only WATCHING position remains
```

---

## Test Results

### ✅ All Core Tests Passing (10/10)

1. **test_perfect_position_lifecycle** - Full DCA cycle with sell
2. **test_top_invalidation_before_confirmation** - Order replacement on invalidation
3. **test_sell_cancels_all_remaining_orders** - Position cleanup
4. **test_only_one_pending_order_at_a_time** - Sequential DCA constraint
5. **test_percentage_based_order_sizing** - Budget allocation
6. **test_budget_released_on_position_close** - Budget + PnL return
7. **test_cancelled_orders_release_funds_immediately** - Multi-position budget tracking
8. **test_multiple_concurrent_positions** - Sequential position creation
9. **test_rapid_invalidations** - Multiple top updates
10. **test_sell_crosses_top_not_invalidation** - Edge case handling

### ⏭️ Skipped (1 test)
- **test_insufficient_funds_graceful_wait** - Requires multi-symbol support (future work)

---

## Integration Roadmap

### Current State: Mock Testing ✅

**What Works:**
- Core position lifecycle logic
- Multi-position management
- Budget tracking
- DCA sequencing
- Top invalidation handling

**What's Mocked:**
- Broker (order placement/fills)
- Price data (simulated candles)
- Time (controlled in tests)

### Next Step: Real Integration 🎯

**Need to integrate with:**

1. **AsyncApp** - Main application runtime
   - Kivy async event loop
   - Strategy lifecycle management
   - UI updates

2. **BinanceClient** - Real exchange connection
   - WebSocket: Market data stream (klines)
   - WebSocket: User data stream (order updates)
   - REST API: Order placement/cancellation

3. **StrategyExecutor** - Central coordinator
   - Route market data to strategies
   - Route strategy events to UI
   - Handle broker integration

---

## Integration Architecture

### Proposed Flow

```
┌─────────────────────────────────────────────────────────────┐
│                        AsyncApp                             │
│                    (Kivy Event Loop)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   StrategyExecutor                          │
│              (Central Event Router)                         │
├─────────────────────────────────────────────────────────────┤
│  • Receives market data from BinanceClient                  │
│  • Routes to active strategies                              │
│  • Receives strategy events (orders, updates)              │
│  • Routes to BinanceClient (orders) and UI (updates)       │
└──────┬────────────────────────────┬─────────────────────────┘
       │                            │
       ▼                            ▼
┌─────────────────┐         ┌─────────────────┐
│ BuyDipStrategy  │         │ BinanceClient   │
│                 │         │                 │
│ • Process       │◄────────┤ • Kline stream  │
│   candles       │         │ • User stream   │
│ • Manage        │─────────┤ • REST API      │
│   positions     │  orders │                 │
│ • Calculate     │         │                 │
│   signals       │         │                 │
└─────────────────┘         └─────────────────┘
```

### Key Integration Points

#### 1. Market Data Flow
```python
# BinanceClient → StrategyExecutor → BuyDipStrategy
async def on_kline(self, kline_data):
    """Receive kline from BinanceClient"""
    candle = {
        'timestamp': kline_data['t'],
        'open': Decimal(kline_data['o']),
        'high': Decimal(kline_data['h']),
        'low': Decimal(kline_data['l']),
        'close': Decimal(kline_data['c']),
        'volume': Decimal(kline_data['v'])
    }
    self.process_candle(symbol, candle)
```

#### 2. Order Placement
```python
# BuyDipStrategy → StrategyExecutor → BinanceClient
def place_order(self, position_id, price, order_id):
    """Place order through broker"""
    if self.broker:  # Real broker
        self.broker.place_order(
            symbol=position.symbol,
            side='BUY',
            type='LIMIT',
            price=price,
            quantity=quantity,
            order_id=order_id
        )
```

#### 3. Order Fill Notifications
```python
# BinanceClient → StrategyExecutor → BuyDipStrategy
async def on_order_update(self, order_data):
    """Receive order update from user stream"""
    if order_data['X'] == 'FILLED':
        self._on_order_filled(
            order_id=order_data['c'],  # client order id
            filled_price=Decimal(order_data['p']),
            filled_quantity=Decimal(order_data['q'])
        )
```

#### 4. UI Updates
```python
# BuyDipStrategy → StrategyExecutor → UI Queue → Kivy
def _send_position_update(self, position):
    """Send position update to UI"""
    if self.ui_queue:
        self.ui_queue.put({
            'type': 'position_update',
            'strategy': 'buy_dip',
            'data': {
                'position_id': position.position_id,
                'state': position.state.value,
                'top_price': float(position.top_price),
                'orders': [order.to_dict() for order in position.buy_orders],
                'pnl': float(self.calculate_pnl(position))
            }
        })
```

---

## Files Structure

### Production Code
```
src/strategies/buy_dip/
├── __init__.py
├── strategy.py          # Main orchestrator (✅ DONE)
├── position.py          # Position state machine (✅ DONE)
├── config.py           # Configuration (✅ DONE)
├── budget_manager.py   # Budget tracking (✅ DONE)
├── candle_buffer.py    # Candle history (✅ DONE)
├── atr.py              # ATR indicator (✅ DONE)
├── rising_detector.py  # Rising pattern detection (✅ DONE)
└── hwm_detector.py     # High watermark detection (✅ DONE)
```

### Test Code
```
tests/strategies/buy_dip/
├── __init__.py
├── test_buy_dip_e2e.py      # E2E tests (✅ 10/10 passing)
├── buy_dip_simulator.py     # Test simulator (✅ DONE)
└── conftest.py              # Test fixtures (✅ DONE)
```

### Documentation
```
docs/buy_dip/
└── README.md  # This file
```

---

## Next Steps: Real Integration

### Phase 1: Basic Integration
1. **Create broker adapter** for BinanceClient
2. **Connect to StrategyExecutor** event routing
3. **Subscribe to kline stream** for market data
4. **Test with paper trading** (no real orders)

### Phase 2: Order Management
1. **Implement real order placement** via REST API
2. **Subscribe to user stream** for order updates
3. **Handle order fills** through callbacks
4. **Test with small real orders** ($5-10)

### Phase 3: UI Integration
1. **Add position display** in GUI
2. **Show real-time updates** (prices, orders, PnL)
3. **Add manual controls** (pause, resume, close positions)
4. **Add configuration panel** (DCA levels, budget, etc.)

### Phase 4: Production Ready
1. **Error handling** (connection loss, API errors)
2. **Position recovery** on restart
3. **Logging and monitoring**
4. **Performance optimization**

---

## Code Migration Checklist

### BuyDipStrategy Integration

- [ ] Add `async def start()` method for initialization
- [ ] Add `async def stop()` method for cleanup
- [ ] Add `ui_queue` parameter for GUI updates
- [ ] Add `worker_queue` for async event processing
- [ ] Implement real broker adapter (not mock)
- [ ] Add position persistence (save/load state)
- [ ] Add error handling for API failures
- [ ] Add logging for all operations
- [ ] Add metrics collection (orders placed, fills, PnL)

### StrategyExecutor Integration

- [ ] Add BuyDipStrategy to active strategies
- [ ] Route kline data to strategy
- [ ] Route order events from user stream
- [ ] Route position updates to UI
- [ ] Handle strategy lifecycle (start/stop)

### BinanceClient Integration

- [ ] Subscribe to BTCUSDC kline stream (15m)
- [ ] Subscribe to user data stream
- [ ] Implement order placement (LIMIT orders)
- [ ] Implement order cancellation
- [ ] Handle reconnection logic

---

## Summary

**Core Logic**: ✅ Complete and tested  
**Multi-Position**: ✅ Working correctly  
**Budget Management**: ✅ Accurate tracking  
**DCA Sequencing**: ✅ Sequential execution  

**Ready for**: Real integration with AsyncApp and BinanceClient! 🚀

**Next Session**: Focus on connecting the strategy to real market data and order execution.
