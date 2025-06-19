# New Trading Database System

This document describes the redesigned database system for the RSI-based futures trading application. The new system is built from the ground up with a focus on **recovery**, **multihop trade support**, and **cross-platform reliability**.

## Key Design Principles

### 1. Recovery-First Design
- **Primary Goal**: Restore all active positions after system restart
- **State Verification**: Automatically verify position states with exchange after recovery
- **Data Integrity**: Ensure no positions are lost during system outages

### 2. Cross-Platform Compatibility
- **SQLite-based**: Works reliably on both Windows (development) and Linux (production)
- **No External Dependencies**: No MySQL server setup required
- **Portable**: Single database file that can be easily backed up and moved

### 3. Multihop Trade Support
- **Parent-Child Relationships**: Track complex trade hierarchies
- **Trade Types**: Support for DIRECT, TWOHOP, and CONVERT trades
- **Sequence Tracking**: Maintain order of operations in multihop chains

### 4. Simplified Architecture
- **Clean Models**: Clear data structures that map directly to trading concepts
- **Single Source of Truth**: One database for all position and order data
- **Easy Querying**: Simple SQL queries for common operations

## Database Schema

### Core Tables

#### Positions Table
The heart of the recovery system - stores all position information:

```sql
CREATE TABLE positions (
    id TEXT PRIMARY KEY,                    -- Unique position ID
    hp_id TEXT NOT NULL,                   -- Human-readable position ID
    strategy_id TEXT,                      -- Reference to strategy
    position_type TEXT NOT NULL,           -- 'BUY' or 'SELL'
    status TEXT NOT NULL,                  -- Position status
    symbol TEXT NOT NULL,                  -- Trading symbol (e.g., BTCUSDC)
    coin TEXT NOT NULL,                    -- Base coin (e.g., BTC)
    
    -- Pricing and quantities
    target_price REAL DEFAULT 0.0,
    buy_price REAL DEFAULT 0.0,
    sell_price REAL DEFAULT 0.0,
    quantity REAL DEFAULT 0.0,
    realized_quantity REAL DEFAULT 0.0,
    budget REAL DEFAULT 0.0,
    
    -- Multihop support
    parent_position_id TEXT,               -- Parent for child positions
    child_position_ids TEXT,               -- JSON array of child IDs
    trade_type TEXT DEFAULT 'DIRECT',      -- DIRECT, TWOHOP, CONVERT
    hop_sequence INTEGER DEFAULT 0,        -- Order in multihop chain
    
    -- Configuration
    price_low REAL DEFAULT 0.0,
    price_high REAL DEFAULT 0.0,
    order_trigger REAL DEFAULT 0.0,
    end_currency TEXT DEFAULT 'USDC',
    mode TEXT DEFAULT 'DCA',
    
    -- State tracking
    completeness REAL DEFAULT 0.0,        -- 0.0 to 1.0
    next_monitor_time TIMESTAMP,
    
    -- Metadata
    metadata TEXT,                         -- JSON for additional data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Core Components

### 1. TradingDatabase
Main database interface providing async SQLite operations, position persistence, and recovery queries.

### 2. RecoveryService
Handles position recovery after system restart by loading active positions, verifying states with exchange, and reconstructing trading objects.

### 3. PositionManager
Integrates trading system with database by converting between trading objects and database models.

## Installation and Setup

### Install Dependencies
```bash
pip install aiosqlite
```

### Initialize Database
```python
from src.database import TradingDatabase

db = TradingDatabase("trading.db")
# Tables created automatically
```

### Integration Example
```python
# In main.py, replace MySQL with:
from src.database import TradingDatabase, RecoveryService, PositionManager

db = TradingDatabase("data/trading.db")
recovery_service = RecoveryService(db, client, symbols_info)  
position_manager = PositionManager(db)

# Recover positions on startup
buy_positions, sell_positions = await recovery_service.recover_all_positions()
```

## Key Benefits

1. **Reliability**: No MySQL dependency, ACID transactions, crash recovery
2. **Simplicity**: Single file database, easy backups, clear schema
3. **Performance**: Local access, optimized queries, efficient indexing
4. **Development**: Same database on Windows and Linux, easy testing

This system provides a solid foundation for reliable position management and recovery in multihop trading environments.
