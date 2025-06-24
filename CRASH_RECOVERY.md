# Real Crash Recovery System

## Overview

This is a complete crash recovery system that restores active trading positions after system restart/crash. Unlike the previous test-only implementation, this system:

1. **Uses the real `trading.db` database** - not test databases
2. **Calls the real position setup methods** - `setup_buy_position()` and `setup_sell_position_with_new_hp()`
3. **Integrates with the actual application startup** - runs automatically when HPManager strategy is loaded
4. **Handles real trading scenarios** - exchange verification, order status synchronization, multihop positions

## How It Works

### 1. Database Integration
- Uses `TradingDatabase` class with the default `trading.db` file
- Stores positions, orders, and strategies persistently
- Survives system restarts and crashes

### 2. Recovery Process
When the application starts:

1. **AsyncApp.load_all_active_strategies()** - Loads existing strategies from database
2. **AsyncApp.setup_hp_manager()** - Creates StrategyExecutor for HPManager strategy
3. **StrategyExecutor.recover_positions_from_crash()** - Recovers positions (NEW METHOD)
4. **Real position restoration** - Calls existing setup methods to restore trading state

### 3. Recovery Service
The `RecoveryService` class:
- Loads active positions from database
- Verifies order status with Binance exchange
- Converts database objects to trading objects (`HPBuyData`, `HPSellData`)
- Handles exchange/database inconsistencies

### 4. Position Restoration
For each recovered position:
- **Buy positions**: Call `setup_buy_position(HPBuyData)` 
- **Sell positions**: Call `setup_sell_position_with_new_hp(SellPosition, sell_strategy)`

This restores the complete trading state including:
- Active orders
- Position status
- UI updates
- WebSocket subscriptions
- Strategy state machines

## Files Modified

### Core Implementation
- `src/strategy_executor.py`: Added `recover_positions_from_crash()` method
- `src/database/recovery_service.py`: Position recovery and exchange verification
- `src/database/trading_database.py`: Database operations for position persistence

### Integration
- Application startup automatically triggers recovery when HPManager strategy exists
- No manual intervention required - works transparently

### Tests
- `tests/integration/test_real_crash_recovery.py`: Integration tests with real database and setup methods
- `crash_recovery_demo.py`: Demonstration script showing complete flow

## Usage

### Automatic (Normal Operation)
1. Start the application normally with `python main.py`
2. If positions exist in `trading.db`, they are automatically recovered
3. Trading resumes from where it left off

### Manual Testing
```python
# Run the demo script
python crash_recovery_demo.py

# Run integration tests
pytest tests/integration/test_real_crash_recovery.py -v
```

### Database Inspection
```bash
# Examine the database directly
sqlite3 trading.db
.tables
SELECT * FROM positions WHERE status NOT IN ('CLOSED', 'CANCELED');
```

## Error Handling

The recovery system is designed to be robust:
- **Database errors**: Logs error, continues with empty state
- **Exchange errors**: Logs warning, uses database state
- **Invalid positions**: Skips invalid positions, continues with valid ones
- **Missing symbols**: Logs error, skips position

This ensures the trading system always starts successfully, even if recovery encounters issues.

## Configuration

The system uses default configurations:
- Database file: `trading.db` (in project root)
- Recovery runs automatically on startup
- No additional configuration required

## Development

### Adding New Position Types
1. Update `Position` model in `src/database/models.py`
2. Add conversion logic in `RecoveryService._convert_to_*_data()` methods
3. Handle in `StrategyExecutor.recover_positions_from_crash()`

### Testing Recovery Logic
1. Create positions in database
2. Restart application
3. Verify positions are restored correctly
4. Check logs for recovery status

### Debugging
- Enable debug logging: `logging.getLogger("recovery_service").setLevel(logging.DEBUG)`
- Check `artifacts/` folder for recovery logs
- Use SQLite browser to inspect database state

## Benefits

1. **Zero data loss** - All active positions survive system restarts
2. **Seamless operation** - Users don't notice crashes/restarts
3. **Exchange synchronization** - Positions stay in sync with Binance
4. **Real trading integration** - Uses actual position setup methods
5. **Robust error handling** - System always starts successfully
6. **Easy testing** - Real database makes testing straightforward

This crash recovery system ensures that your trading operations can continue reliably even after unexpected system failures.
