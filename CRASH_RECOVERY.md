# Crash Recovery System

## Overview

The crash recovery system provides robust restoration of trading positions after system restarts, crashes, or unexpected shutdowns. The system ensures zero data loss and seamless continuation of trading operations.

## Key Features

✅ **Real Database Integration** - Uses production `trading.db` SQLite database  
✅ **Exchange Verification** - Synchronizes position states with Binance exchange  
✅ **Complete State Restoration** - Restores positions with original HP IDs and order states  
✅ **Automatic Integration** - Runs automatically during application startup  
✅ **Error Resilience** - Handles missing data, invalid symbols, and exchange errors gracefully  
✅ **Type Safety** - Full type annotations and mypy compliance  

## Architecture

### Core Components

1. **TradingDatabase** (`src/database/trading_database.py`)
   - SQLite-based persistence layer
   - Stores positions, orders, strategies, and trades
   - Cross-platform compatibility (Windows/Linux)

2. **RecoveryService** (`src/database/recovery_service.py`)
   - Orchestrates the recovery process
   - Verifies positions with Binance exchange
   - Converts database objects to trading system objects

3. **StrategyExecutor** (`src/strategy_executor.py`)
   - Integrates recovery into application startup
   - Calls real position setup methods
   - Manages strategy lifecycle

## Recovery Process

### 1. Database Loading
```python
# Load all active positions from database
active_positions = await self.database.get_active_positions()
```

### 2. Exchange Verification
```python
# Verify each position's orders with Binance
for position in active_positions:
    orders = await self.database.get_position_orders(position.id)
    for order in orders:
        if order.exchange_order_id:
            exchange_order = await self.client.get_order(
                symbol=order.symbol, orderId=order.exchange_order_id
            )
            # Update status if changed
```

### 3. Position Restoration
```python
# Convert to trading system objects
buy_positions, sell_positions = await recovery_service.recover_all_positions()

# Restore using real setup methods
for buy_data in buy_positions:
    await self.setup_buy_position(buy_data, is_restoration=True)

for sell_data in sell_positions:
    await self.setup_sell_position_with_new_hp(sell_data, is_restoration=True)
```

## Implementation Details

### Database Schema

**Positions Table** (Core recovery data):
```sql
CREATE TABLE positions (
    id TEXT PRIMARY KEY,
    hp_id TEXT NOT NULL,           -- Original position identifier
    strategy_id TEXT,
    position_type TEXT NOT NULL,   -- BUY/SELL
    status TEXT NOT NULL,          -- NEW/OPEN/FILLED/CLOSED
    symbol TEXT NOT NULL,
    price_low REAL,
    price_high REAL,
    order_trigger REAL,            -- Percentage (1.0 = 1%)
    budget REAL,
    quantity REAL,
    realized_quantity REAL,
    -- ... additional fields
);
```

### Recovery Flow

1. **Application Startup**
   ```python
   async def recover_positions_from_crash(self):
       """Called automatically during StrategyExecutor initialization"""
   ```

2. **Position Loading**
   ```python
   buy_positions, sell_positions = await self.recovery_service.recover_all_positions()
   ```

3. **Setup Method Integration**
   ```python
   # Uses existing methods with restoration flag
   await self.setup_buy_position(buy_data, is_restoration=True)
   await self.setup_sell_position_with_new_hp(sell_data, is_restoration=True)
   ```

4. **Order State Preservation**
   - Original HP IDs are preserved
   - Order statuses are synchronized with exchange
   - No new orders are sent during restoration

## Configuration

### Order Trigger Format
`order_trigger` values are stored as percentages:
- `1.0` = 1%
- `2.5` = 2.5%
- `10.0` = 10%

Usage in HP Manager:
```python
trigger_price = base_price * (1 + (order_trigger / 100))
```

### Database Location
- Production: `trading.db` (project root)
- Tests: Temporary files (`/tmp/tmp*.db`)

## Testing

### Integration Tests
```bash
# Run crash recovery tests
pytest tests/integration/test_real_crash_recovery.py -v
```

Test scenarios:
- ✅ Recovery with real database and setup methods
- ✅ RecoveryService position finding
- ✅ Empty database handling
- ✅ Graceful error handling for invalid data

### Demo Script
```bash
# Interactive demonstration
python crash_recovery_demo.py
```

Shows complete flow:
1. Creating positions in database
2. Simulating system restart
3. Recovering positions
4. Validation checks

## Error Handling

### Robust Recovery
- **Missing symbols**: Logs error, skips position, continues
- **Exchange errors**: Logs warning, uses database state
- **Invalid data**: Gracefully handles and continues
- **Network issues**: Retries with fallback to database state

### Logging
```python
logger.info("Starting position recovery process...")
logger.info("Found %d active positions in database", len(positions))
logger.info("Recovered %d buy positions and %d sell positions", len(buy), len(sell))
```

## File Structure

```
src/
├── database/
│   ├── trading_database.py      # SQLite operations
│   ├── recovery_service.py      # Recovery orchestration
│   ├── models.py               # Database models
│   └── exceptions.py           # Recovery exceptions
├── strategy_executor.py        # Integration point
└── identifiers.py             # Trading system types

tests/integration/
└── test_real_crash_recovery.py # Integration tests

crash_recovery_demo.py          # Demo script
```

## Benefits

### For Trading Operations
- **Zero data loss** - All positions survive system failures
- **Seamless continuation** - Trading resumes exactly where it left off
- **Exchange synchronization** - Positions stay in sync with Binance
- **Original state preservation** - HP IDs and order relationships maintained

### For Development
- **Real integration** - Uses actual setup methods, not mocks
- **Type safety** - Full mypy compliance and type annotations
- **Easy testing** - Real database makes testing straightforward
- **Clean architecture** - Separation of concerns between database, recovery, and trading logic

### For Operations
- **Automatic operation** - No manual intervention required
- **Robust error handling** - System always starts successfully
- **Cross-platform** - Works on Windows and Linux
- **Monitoring** - Comprehensive logging for troubleshooting

## Usage Examples

### Automatic Recovery (Normal Operation)
```bash
# Start application - recovery happens automatically
python main.py
```

### Manual Database Inspection
```bash
# Examine positions in database
sqlite3 trading.db
.tables
SELECT hp_id, symbol, status, created_at FROM positions 
WHERE status NOT IN ('CLOSED', 'CANCELED');
```

### Programmatic Access
```python
from src.database.trading_database import TradingDatabase

db = TradingDatabase()
positions = await db.get_active_positions()
for pos in positions:
    print(f"Position {pos.hp_id}: {pos.symbol} ({pos.status.value})")
```

## Development Guidelines

### Adding New Position Types
1. Update `Position` model in `models.py`
2. Add conversion logic in `RecoveryService._convert_to_*_data()`
3. Handle in `StrategyExecutor.recover_positions_from_crash()`
4. Add integration tests

### Testing Recovery Changes
1. Create test positions in database
2. Restart application
3. Verify positions restored correctly
4. Check logs for any issues
5. Run integration test suite

This crash recovery system ensures reliable, uninterrupted trading operations with complete state preservation across system restarts.
