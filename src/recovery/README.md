# Recovery Module

This module handles crash recovery and position restoration after system restarts.

## Architecture

The recovery system is designed with a coordinator pattern and specialized helper classes:

### Main Coordinator

**`RecoveryService`** (`recovery_service.py`)
- Orchestrates the entire recovery process
- Coordinates between database, exchange, and trading system
- Handles both buy and sell position restoration
- Entry point: `recover_positions_from_crash()`

### Helper Classes

**`PositionConverter`** (`position_converter.py`)
- Converts database `Position` models to trading system structures (`HPBuy`, `HPSell`)
- Handles state mapping between database and application states
- Pure transformation logic with no side effects

**`OrderRestorer`** (`order_restorer.py`)
- Fetches orders from database for a position
- Aggregates duplicate order entries (from multiple saves during partial fills)
- Verifies order states with the exchange
- Updates database with current exchange state

**`MultihopRecoveryHandler`** (`multihop_recovery_handler.py`)
- Specializes in restoring two-leg (multihop) sell positions
- Determines which leg is active based on first leg completion status
- Manages parent-child position relationships

**`PositionVerifier`** (`position_verifier.py`)
- Validates position states against exchange
- Reconciles discrepancies between database and exchange
- Updates positions based on current order states

## Recovery Flow

```
1. RecoveryService.recover_positions_from_crash()
   ↓
2. Load active positions from database
   ↓
3. PositionVerifier: Verify/update states with exchange
   ↓
4. For each position:
   a. PositionConverter: Convert DB model → trading structure
   b. OrderRestorer: Fetch & verify orders from DB/exchange
   c. MultihopRecoveryHandler: Handle multihop logic (if applicable)
   d. Reconstruct HpStrategy with verified state
   ↓
5. Return restored strategies to StrategyExecutor
```

## Key Design Principles

1. **Separation of Concerns**: Each helper handles one specific aspect
2. **Stateless Helpers**: Helper classes have minimal state, focusing on operations
3. **Database as Source of Truth**: Recovery relies on database state verified against exchange
4. **Exchange Reconciliation**: Always verify DB state with exchange for critical fields
5. **Idempotency**: Recovery can be run multiple times safely

## Dependencies

- **Database Layer**: Uses `src.database.models` and `src.database.trading_database`
- **Trading System**: Creates `HpStrategy`, `HPPositionBuy`, `HPPositionSell` objects
- **Exchange**: Verifies states via `KrakenClient`

## Testing

Recovery logic is extensively tested in:
- `tests/strategies/test_hp_manager_recovery_db.py` (36 tests, 4000+ lines)

Tests cover:
- Buy position recovery (various states)
- Sell position recovery (direct and multihop)
- Partial fill scenarios
- Order cancellation recovery
- Database/exchange state reconciliation
- Edge cases and error handling
