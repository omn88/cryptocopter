# Buy Dip Strategy - Implementation Status

## Documentation Cleanup Complete ✅

### Removed (Obsolete Tick-Based Approach)
- ❌ BUY_DIP_THREE_PHASE_DETECTION.md
- ❌ BUY_DIP_IMPLEMENTATION_SUMMARY.md
- ❌ BUY_DIP_VISUAL_GUIDE.md
- ❌ Old BUY_DIP_STRATEGY_DESIGN.md
- ❌ BUY_DIP_STRATEGY_UPDATED.md

### Updated (Candle-Based Approach)
- ✅ **BUY_DIP_STRATEGY_DESIGN.md** - Complete technical design
- ✅ **BUY_DIP_KEY_INSIGHT.md** - Two-phase confirmation concept
- ✅ **BUY_DIP_README_FIRST.md** - Plain language guide
- ✅ **BUY_DIP_CANDLE_STORAGE.md** - Storage and ATR guide

---

## New Approach: Candle-Based High-Watermark

### What Changed

**Before (Tick-Based Three-Phase):**
- Process every 1-second tick
- Phase 1: Swing low detection (5 consecutive higher ticks)
- Phase 2: Retracement validation (% threshold)
- Phase 3: Top detection (3 consecutive lower ticks)
- **Problem:** Too many signals, noise, complexity

**After (Candle-Based HWM):**
- Process Binance 15-min candles
- Rising pattern detection (3 consecutive OR total gain)
- High-watermark tracking with pullback threshold
- ATR-based adaptive thresholds
- **Solution:** Cleaner signals, less noise, simpler

---

## Architecture

```
Binance WebSocket (15-min klines)
    ↓
CandleBuffer (ring buffer)
    ↓
RisingCandleDetector (arms top watch)
    ↓
HighWatermarkDetector (confirms top with ATR)
    ↓
BuyDipPosition (manages position lifecycle)
```

### Components to Implement

1. **CandleBuffer**
   - Ring buffer for last 100 candles
   - Tracks current incomplete candle
   - Provides last N candles API

2. **ATR (Average True Range)**
   - Calculates volatility (14-period default)
   - Wilder's smoothing method
   - Enables adaptive thresholds

3. **RisingCandleDetector**
   - EITHER: 3 consecutive higher highs
   - OR: Total gain >= threshold (e.g., 0.25%)
   - Flexible to catch both clean and choppy uptrends

4. **HighWatermarkDetector**
   - Tracks highest price (HWM)
   - Tracks lowest after HWM (local bottom)
   - Confirms top when drawdown >= threshold
   - ATR-adaptive: threshold = max(fixed%, ATR × mult)
   - Invalidates top if new high before confirmation

5. **BuyDipPosition** (State Machine)
   - WATCHING: Monitoring for patterns
   - POTENTIAL_TOP: First order placed, awaiting fill
   - ACTIVE: Position open, managing DCA
   - COMPLETED: Sold at target
   - CANCELLED: Top invalidated

---

## Test Suite Complete ✅

### File: `test_candle_detection.py` (29 tests)

#### CandleBuffer Tests (3)
- ✅ Stores completed candles
- ✅ Tracks current incomplete candle
- ✅ Ring buffer evicts old candles

#### ATR Tests (4)
- ✅ Calculates true range correctly
- ✅ Bootstrap with simple average
- ✅ Wilder's smoothing after bootstrap
- ✅ Realistic BTC candle calculations

#### RisingCandleDetector Tests (4)
- ✅ Detects 3 consecutive higher highs
- ✅ Detects total gain (allows dips)
- ✅ Rejects insufficient movement
- ✅ Configurable: highs vs closes

#### HighWatermarkDetector Tests (5)
- ✅ Basic top confirmation with pullback
- ✅ Tracks local bottom correctly
- ✅ Invalidates on new high
- ✅ ATR-adaptive threshold
- ✅ Realistic BTC scenario

#### Integration Tests (1)
- ✅ Complete cycle: rising → HWM → confirmation

#### Edge Cases (2)
- ✅ Invalid configuration handling
- ✅ Insufficient data handling

---

## Configuration Example

```python
buy_dip_config = {
    # Symbol and candles
    "symbol": "BTCUSDT",
    "candle_interval": "15m",
    "candle_buffer_size": 100,
    
    # Position sizing
    "first_order_size_usdt": 100,
    "dca_order_size_usdt": 100,
    "max_dca_levels": 3,
    
    # Rising detection
    "rising_consecutive": 3,
    "rising_min_gain_pct": 0.25,
    "rising_use_high": True,
    
    # HWM confirmation
    "pullback_threshold_pct": 0.35,
    "use_atr": True,
    "atr_period": 14,
    "atr_multiplier": 0.8,
    
    # DCA ladder
    "dca_distances_pct": [0.5, 1.0, 1.5],
    
    # Exit
    "sell_at_top": True,
}
```

---

## Next Steps (TDD Implementation)

### Phase 1: Core Detection Components

1. **Create skeleton files:**
   ```
   src/strategies/buy_dip/
       ├── __init__.py
       ├── candle_buffer.py
       ├── atr.py
       ├── rising_candle_detector.py
       └── high_watermark_detector.py
   ```

2. **TDD Workflow:**
   - Remove `pytest.skip()` from one test
   - Implement just enough to pass
   - Refactor
   - Repeat for next test

3. **Test Execution:**
   ```bash
   # Run all tests
   pytest tests/strategies/buy_dip/test_candle_detection.py -v
   
   # Run specific component
   pytest tests/strategies/buy_dip/test_candle_detection.py -k candle_buffer -v
   pytest tests/strategies/buy_dip/test_candle_detection.py -k atr -v
   pytest tests/strategies/buy_dip/test_candle_detection.py -k rising -v
   pytest tests/strategies/buy_dip/test_candle_detection.py -k hwm -v
   ```

### Phase 2: Position Management

1. **Create BuyDipPosition state machine**
   - Tests for state transitions
   - Order placement logic
   - DCA ladder management
   - Top invalidation handling

2. **Integration with existing infrastructure**
   - Broker (WebSocket klines)
   - Database (position persistence)
   - BinanceClient (order execution)

### Phase 3: Integration & Testing

1. **WebSocket integration**
   - Subscribe to 15-min klines
   - Feed candles to CandleBuffer
   - Trigger detection on candle close

2. **Backtesting**
   - Load historical 15-min data
   - Replay through detection system
   - Calculate performance metrics

3. **Live testing**
   - Small position sizes
   - Monitor performance
   - Tune parameters

### Phase 4: GUI

1. **Configuration screen**
   - Symbol selection
   - Candle interval
   - Detection parameters
   - Position sizing

2. **Monitoring interface**
   - Active positions
   - Current HWM
   - Recent candles visualization
   - Performance metrics

---

## Key Improvements Over Previous Design

### 1. No Time-Based Sampling Needed
- **Before:** Had to implement sampling logic for 1-second ticks
- **After:** Use Binance 15-min candles directly

### 2. Cleaner Signal Detection
- **Before:** Three separate phases (swing low, retracement, top)
- **After:** Rising pattern + HWM pullback (two steps)

### 3. Volatility Adaptation
- **Before:** Fixed thresholds only
- **After:** ATR-based adaptive thresholds

### 4. Simpler Testing
- **Before:** Complex tick sequences, timing issues
- **After:** Clean candle arrays, deterministic

### 5. Mature Algorithm
- **Before:** Custom three-phase design
- **After:** Based on GPT-5's proven HWM approach

---

## Success Criteria

### Component Tests
- [ ] All 29 tests passing
- [ ] Code coverage > 90%
- [ ] No lint errors

### Integration Tests
- [ ] WebSocket → Detection pipeline works
- [ ] Position lifecycle complete
- [ ] Order execution successful

### Backtesting
- [ ] Profitable on historical data (BTC, ETH)
- [ ] Win rate > 60%
- [ ] Max drawdown < 5%

### Live Trading
- [ ] No errors in 24h continuous run
- [ ] Orders execute as expected
- [ ] Position tracking accurate

---

## Current Status

- [x] Documentation complete and refactored
- [x] Test suite written (29 tests, all skipped)
- [ ] Core components implementation
- [ ] Position management implementation
- [ ] Integration with infrastructure
- [ ] GUI implementation
- [ ] Backtesting
- [ ] Live trading

**Next Action:** Start TDD implementation of CandleBuffer! 🚀

---

## Quick Start Commands

```bash
# Run all buy dip tests
pytest tests/strategies/buy_dip/ -v

# Run with coverage
pytest tests/strategies/buy_dip/ --cov=src/strategies/buy_dip --cov-report=html

# Watch mode (re-run on file changes)
pytest-watch tests/strategies/buy_dip/

# Type checking
mypy src/strategies/buy_dip/
```

---

## Documentation Reading Order

1. **BUY_DIP_README_FIRST.md** - Start here! Plain language explanation
2. **BUY_DIP_KEY_INSIGHT.md** - Understand two-phase confirmation
3. **BUY_DIP_STRATEGY_DESIGN.md** - Complete technical design
4. **BUY_DIP_CANDLE_STORAGE.md** - Storage and ATR details
5. **test_candle_detection.py** - See expected behavior

---

## Questions & Answers

**Q: Why 15-min candles instead of 1-min or 5-min?**
A: Balance between signal quality and responsiveness. 15-min filters noise but still catches meaningful moves. Can be configured.

**Q: What if Binance WebSocket disconnects?**
A: Reconnect logic + load recent candles from database/API to rebuild buffer.

**Q: How to tune for different symbols (BNB, LTC)?**
A: Adjust thresholds (volatility different). Use ATR multiplier. Backtest to optimize.

**Q: What about 1-hour candles for even cleaner signals?**
A: Absolutely! Just change candle_interval config. Strategy is interval-agnostic.

**Q: Can I use this for spot trading (not futures)?**
A: Yes! Just change symbol format (BTCUSDT vs BTCUSDC).

---

**Ready to implement! Start with CandleBuffer tests.** 🎯
