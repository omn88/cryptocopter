# New Trading Database System

## Overview

This document describes the new database system designed specifically for the RSI-based futures trading system. The new design prioritizes **recovery**, **multihop trade support**, and **cross-platform compatibility**.

## Key Design Principles

### 1. Recovery-First Design
- **Primary Goal**: Restore all active positions after system restart
- **Simple Queries**: Easy to retrieve and reconstruct trading state
- **Data Integrity**: Ensure consistency even after unexpected shutdowns
- **Exchange Verification**: Compare database state with exchange state on recovery

### 2. Multihop Trade Support
- **Parent-Child Relationships**: Track hierarchical position dependencies
- **Trade Chains**: Support 1-hop, 2-hop, and conversion trades
- **State Coordination**: Manage complex state transitions across multiple positions
- **Atomic Operations**: Ensure consistency for complex multihop operations

### 3. Cross-Platform Compatibility
- **SQLite Backend**: Works reliably on both Windows and Linux
- **No External Dependencies**: No need for MySQL server setup
- **Portable**: Database file can be easily moved between systems
- **Backup/Restore**: Simple file-based backup and restore

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Trading System                           │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  │  Recovery       │  │  Position       │  │  Integration    │
│  │  Service        │  │  Manager        │  │  Layer          │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Trading Database                           │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐       │ │
│  │  │ Positions   │ │   Orders    │ │   Trades    │       │ │
│  │  └─────────────┘ └─────────────┘ └─────────────┘       │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                      SQLite                                 │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. TradingDatabase
The main database class providing:
- Position persistence
- Order tracking
- Trade recording
- Recovery queries
- Backup/restore functionality

### 2. RecoveryService
Handles system recovery:
- Loads active positions from database
- Verifies state with exchange
- Reconstructs trading system objects
- Handles data discrepancies

### 3. PositionManager
Integrates with existing trading system:
- Converts between trading objects and database models
- Manages real-time position updates
- Handles multihop position relationships
- Provides clean API for trading system

### 4. Models
Core data models:
- `Position`: Central position record
- `Order`: Individual order tracking
- `Trade`: Trade execution records
- `Strategy`: Strategy configuration

## Database Schema

### Positions Table
The core table for recovery operations:

```sql
CREATE TABLE positions (
    id TEXT PRIMARY KEY,
    hp_id TEXT NOT NULL,                    -- Human-readable position ID
    strategy_id TEXT,
    position_type TEXT NOT NULL,            -- BUY/SELL
    status TEXT NOT NULL,                   -- NEW/OPEN/FILLED/CLOSED
    symbol TEXT NOT NULL,
    coin TEXT NOT NULL,
    
    -- Pricing and quantities
    target_price REAL DEFAULT 0.0,
    buy_price REAL DEFAULT 0.0,
    sell_price REAL DEFAULT 0.0,
    quantity REAL DEFAULT 0.0,
    realized_quantity REAL DEFAULT 0.0,
    budget REAL DEFAULT 0.0,
    
    -- Multihop support
    parent_position_id TEXT,
    child_position_ids TEXT,                -- JSON array
    trade_type TEXT DEFAULT 'DIRECT',       -- DIRECT/TWOHOP/CONVERT
    hop_sequence INTEGER DEFAULT 0,
    
    -- Configuration
    price_low REAL DEFAULT 0.0,
    price_high REAL DEFAULT 0.0,
    order_trigger REAL DEFAULT 0.0,
    end_currency TEXT DEFAULT 'USDC',
    mode TEXT DEFAULT 'DCA',
    
    -- State tracking
    completeness REAL DEFAULT 0.0,
    next_monitor_time TIMESTAMP,
    metadata TEXT,                          -- JSON for additional data
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Orders Table
Tracks individual orders:

```sql
CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL,
    exchange_order_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT DEFAULT 'LIMIT',
    status TEXT NOT NULL,
    price REAL DEFAULT 0.0,
    quantity REAL DEFAULT 0.0,
    quantity_stable REAL DEFAULT 0.0,
    realized_quantity REAL DEFAULT 0.0,
    time_in_force TEXT DEFAULT 'GTC',
    filled_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Usage Examples

### Basic Operations

```python
from src.database import TradingDatabase, PositionManager

# Initialize database
db = TradingDatabase("trading.db")
position_manager = PositionManager(db)

# Save a buy position
buy_data = HPBuyData(config=buy_config, state_info=state_info)
position_id = await position_manager.save_buy_position(buy_data)

# Get active positions for recovery
active_positions = await db.get_active_positions()
```

### Recovery Process

```python
from src.database import RecoveryService

# Initialize recovery service
recovery = RecoveryService(db, client, symbols_info)

# Recover all positions
buy_positions, sell_positions = await recovery.recover_all_positions()

# Validate recovery integrity
validation_report = await recovery.validate_recovery_integrity()
```

### Multihop Trades

```python
# Save multihop sell positions
sell_positions = [position1, position2]  # From HPPositionSell
position_ids = await position_manager.save_multihop_sell_positions(
    sell_positions, parent_hp_id="parent_001"
)

# Retrieve complete hierarchy
hierarchy = await db.get_position_hierarchy("parent_001")
```

## Migration from Old Database

### Migration Process

1. **Backup Current Database**: Create backup of existing MySQL database
2. **Run Migration Script**: Use provided migration utilities
3. **Validate Migration**: Verify all data was transferred correctly
4. **Test Recovery**: Ensure recovery process works with migrated data
5. **Update Configuration**: Switch to new database in production

### Migration Script Example

```python
from src.database.migration import run_migration

# Configure old database
old_db_config = {
    'host': 'localhost',
    'port': 3306,
    'user': 'trading_user',
    'password': 'password',
    'name': 'trading_db'
}

# Run migration
summary = await run_migration(old_db_config, "new_trading.db")
print(f"Migration completed: {summary}")
```

## Benefits of New Design

### 1. Simplified Recovery
- **Single Query**: Get all active positions with one query
- **Complete State**: All necessary data in one record
- **Hierarchy Support**: Easy to reconstruct multihop chains
- **Verification**: Built-in exchange state verification

### 2. Better Multihop Support
- **Relationship Tracking**: Clear parent-child relationships
- **State Coordination**: Proper state management across hops
- **Atomic Updates**: Consistent updates for complex operations
- **Recovery Integrity**: Complete chain recovery

### 3. Improved Reliability
- **Cross-Platform**: Works on Windows and Linux
- **No External Dependencies**: SQLite is built-in
- **File-Based**: Easy backup and restore
- **Transaction Safety**: ACID compliance

### 4. Enhanced Monitoring
- **Statistics**: Built-in database statistics
- **Backup**: Automated backup functionality
- **Validation**: Data integrity checks
- **Performance**: Optimized for recovery queries

## Configuration

### Environment Variables

```bash
# Optional: Specify database path
TRADING_DB_PATH="/path/to/trading.db"

# Optional: Enable debug logging
DB_DEBUG=true

# Optional: Backup directory
DB_BACKUP_DIR="/path/to/backups"
```

### Application Configuration

```python
# In main.py or configuration module
from src.database import TradingDatabase, RecoveryService, PositionManager

# Initialize database system
db = TradingDatabase("trading.db")
recovery_service = RecoveryService(db, client, symbols_info)
position_manager = PositionManager(db)

# Use in trading system
await position_manager.save_buy_position(buy_data)
```

## Testing

### Running Tests

```bash
# Run all database tests
python -m pytest src/database/test_trading_database.py -v

# Run specific test categories
python -m pytest src/database/test_trading_database.py::TestTradingDatabase -v
python -m pytest src/database/test_trading_database.py::TestRecoveryService -v
```

### Test Coverage

The test suite covers:
- Basic database operations
- Position CRUD operations
- Order management
- Multihop position relationships
- Recovery scenarios
- Performance characteristics
- Concurrent operations
- Data integrity

## Troubleshooting

### Common Issues

1. **Database Lock Errors**
   - Ensure all connections are properly closed
   - Use async context managers
   - Check for long-running transactions

2. **Migration Issues**
   - Verify old database accessibility
   - Check data type compatibility
   - Validate foreign key relationships

3. **Recovery Problems**
   - Check exchange API connectivity
   - Verify symbol information
   - Review position state consistency

### Debugging

```python
# Enable debug logging
import logging
logging.getLogger("trading_database").setLevel(logging.DEBUG)

# Get database statistics
stats = await db.get_database_stats()
print(f"Database stats: {stats}")

# Validate data integrity
validation = await recovery_service.validate_recovery_integrity()
print(f"Validation result: {validation}")
```

## Performance Considerations

### Optimization Tips

1. **Batch Operations**: Use transactions for multiple updates
2. **Index Usage**: Queries are optimized with proper indices
3. **Connection Pooling**: Reuse connections when possible
4. **Regular Backups**: Schedule automated backups
5. **Monitoring**: Track database size and performance

### Scaling

The SQLite design supports:
- **Thousands of positions**: Adequate for most trading scenarios
- **Concurrent reads**: Multiple readers supported
- **Single writer**: Appropriate for trading system architecture
- **File size limits**: Suitable for typical trading data volumes

## Future Enhancements

### Planned Features

1. **Compression**: Database compression for large datasets
2. **Sharding**: Multiple database files for very large datasets
3. **Replication**: Master-slave replication for backup
4. **Analytics**: Built-in trading analytics queries
5. **Monitoring**: Enhanced monitoring and alerting

### Extension Points

The design supports:
- Custom metadata fields
- Additional position types
- Extended order information
- Custom recovery logic
- Integration with external systems

## Support

For questions or issues with the new database system:

1. **Check Documentation**: Review this README and code comments
2. **Run Tests**: Execute test suite to verify functionality
3. **Check Logs**: Enable debug logging for troubleshooting
4. **Validate Data**: Use built-in validation tools
5. **Create Backup**: Always backup before major changes
