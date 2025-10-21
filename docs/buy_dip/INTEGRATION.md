# Buy Dip Strategy - Application Integration

## Overview

The Buy Dip strategy has been successfully integrated with the AsyncApp architecture, following the same patterns as the HP Manager strategy. This document describes the integration architecture and how to use it.

## Architecture

### Components Created

1. **BuyDipBrokerAdapter** (`src/strategies/buy_dip/broker_adapter.py`)
   - Bridges strategy with BinanceClient REST API
   - Handles order placement/cancellation
   - Processes WebSocket user stream events
   - Manages order fill/cancellation callbacks

2. **BuyDipExecutor** (`src/strategies/buy_dip/executor.py`)
   - Integrates strategy with AsyncApp lifecycle
   - Subscribes to WebSocket kline streams (15m candles)
   - Subscribes to user data stream for order updates
   - Routes market data to strategy
   - Handles async worker loop
   - Sends UI updates

3. **BuyDipFront** (`src/strategies/buy_dip/ui/buy_dip_front.py`)
   - Kivy UI for strategy monitoring
   - Displays budget status (total/available/locked)
   - Shows active/total positions count
   - Activity log for orders and position events

4. **AsyncApp Integration** (`src/gui/app/asyncapp.py`)
   - `setup_buy_dip()` method to initialize strategy
   - Shutdown handling for executor cleanup
   - Tab-based UI integration

### Integration Flow

```
Market Data Flow:
Binance WebSocket → BrokerSpot → worker_queue → BuyDipExecutor → BuyDipStrategy.process_candle()

Order Placement Flow:
BuyDipStrategy.place_order() → BuyDipBrokerAdapter.place_order() → BinanceClient REST API

Order Fill Flow:
Binance User Stream → BrokerSpot → worker_queue → BuyDipExecutor → BuyDipBrokerAdapter.handle_user_stream_update() → BuyDipStrategy.handle_order_fill()

UI Update Flow:
BuyDipStrategy → BuyDipExecutor → ui_queue → BuyDipFront
```

## Usage

### Enabling the Strategy

In `src/gui/app/asyncapp.py`, uncomment the line in `on_start()`:

```python
def on_start(self) -> None:
    self.setup_portfolio_manager()
    self.setup_hp_manager()
    # Enable Buy Dip strategy:
    self.setup_buy_dip()
```

### Configuration

Default configuration in `setup_buy_dip()`:

```python
config = BuyDipConfig(
    symbol="BTCUSDC",
    timeframe="15m",
    # Detection parameters
    min_consecutive_rising=3,
    min_total_gain_pct=0.3,
    atr_period=14,
    atr_multiplier=0.5,
    min_pullback_pct=0.5,
    # DCA levels (φ, e, π, 5%, 10%, 15%)
    dca_distances_pct=[1.618, 2.718, 3.142, 5.0, 10.0, 15.0],
)

# Budget settings
total_budget=Decimal("10000"),  # $10k total budget
order_budget_pct=Decimal("2.0"),  # 2% per order = $200
```

### Strategy Lifecycle

1. **Initialization**
   - BuyDipExecutor creates strategy instance
   - Subscribes to BTCUSDC 15m klines
   - Subscribes to user data stream
   - Starts async worker loop

2. **Market Data Processing**
   - Receives closed candles every 15 minutes
   - Processes through detection pipeline:
     - Rising candle detection
     - HWM (High Water Mark) detection
     - Top confirmation
     - Top invalidation handling

3. **Position Creation**
   - Rising pattern detected → WATCHING state
   - Top confirmed → POTENTIAL_TOP state → Place first DCA order
   - Order filled → ACTIVE state → Place next DCA order

4. **Position Lifecycle**
   - Sequential DCA orders (6 levels: φ, e, π, 5%, 10%, 15%)
   - ONE pending order at a time per position
   - Budget locked per order, released on fill/cancel
   - Sell order placed when position becomes ACTIVE
   - Position COMPLETED when sell order fills

5. **Shutdown**
   - AsyncApp.shutdown() calls executor.stop()
   - Worker loop exits cleanly
   - All async tasks cancelled

## Testing

### E2E Tests

All 11 E2E tests pass:
- Perfect position lifecycle
- Top invalidation before confirmation
- Sell cancels remaining orders
- Only one pending order at a time
- Percentage-based order sizing
- Budget released on position close
- Cancelled orders release funds immediately
- Multiple concurrent positions
- Insufficient funds graceful handling
- Rapid invalidations
- Sell crosses top (not invalidation)

Run tests:
```bash
python -m pytest tests/strategies/buy_dip/test_buy_dip_e2e.py -v
```

### Integration Testing

To test with paper trading:

1. Comment out real order placement in `BuyDipBrokerAdapter.place_order()`
2. Add mock fill simulation
3. Enable strategy in `on_start()`
4. Run application: `python main.py`
5. Monitor logs and UI

## Implementation Notes

### Async Compatibility

- Strategy methods remain synchronous (process_candle, place_order, etc.)
- BrokerAdapter handles async REST API calls via `asyncio.ensure_future()`
- Executor runs in dedicated thread with asyncio loop
- Worker queue bridges sync strategy with async I/O

### Order Management

- Orders placed via BinanceClient REST API (`create_order`)
- Order fills received via WebSocket user data stream
- Client order IDs used for tracking: `{position_id}_dca_{level}` or `{position_id}_sell`
- Broker adapter maintains pending orders dict for status tracking

### Budget Management

- Shared budget pool across all positions
- Funds locked when order placed
- Funds released when order filled/cancelled/expired
- Budget info sent to UI on every update

### Multi-Position Support

- Multiple positions can exist on same symbol
- Each tracks different historical top
- ONE WATCHING position per symbol (detects next rising pattern)
- Multiple POTENTIAL_TOP/ACTIVE positions (independent lifecycles)
- Budget prevents over-leverage

## Future Enhancements

### Phase 2: UI Improvements
- Position list with state indicators
- Real-time PnL tracking
- Order history table
- Chart overlays for tops/DCA levels

### Phase 3: Multi-Symbol Support
- Track multiple symbols simultaneously
- Symbol-specific broker adapters
- Dynamic symbol configuration from UI

### Phase 4: Persistence
- Save positions to database on creation
- Restore positions on restart
- Position history and analytics
- Performance tracking

### Phase 5: Advanced Features
- Configurable DCA levels from UI
- Dynamic budget allocation
- Stop-loss configuration
- Take-profit targets beyond confirmed top

## Troubleshooting

### Common Issues

**1. No orders being placed**
- Check WebSocket connection status
- Verify kline subscription is active
- Ensure budget is sufficient
- Check strategy detection logs

**2. Orders not filling**
- Verify price levels are reasonable
- Check order status on Binance
- Monitor user stream for execution reports
- Ensure order IDs are unique

**3. Memory leaks**
- Monitor position dictionary size
- Check for unreleased budget locks
- Verify completed positions are cleaned up
- Review async task cancellation

### Debug Mode

Enable detailed logging:
```python
logging.getLogger("buy_dip").setLevel(logging.DEBUG)
logging.getLogger("buy_dip_executor").setLevel(logging.DEBUG)
logging.getLogger("buy_dip_adapter").setLevel(logging.DEBUG)
```

## Conclusion

The Buy Dip strategy is now fully integrated with the application architecture and ready for live testing. The implementation follows established patterns from HP Manager, ensuring consistency and maintainability.

**Status**: ✅ Integration Complete
**Tests**: ✅ 11/11 Passing
**Documentation**: ✅ Complete
**Next Step**: Paper trading validation
