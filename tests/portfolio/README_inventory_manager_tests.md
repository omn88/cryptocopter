# Inventory Manager Unit Tests

This directory contains comprehensive unit tests for the `InventoryManager` class located at `src/portfolio/inventory_manager.py`.

## Test File

- `test_inventory_manager.py` - Complete test suite for inventory manager with locking semantics

## Coverage

- **Previous Coverage**: 49%
- **New Coverage**: 100%
- **Increase**: +51 percentage points

## Test Structure

The test suite is organized into 10 test classes:

### 1. TestBasicInventoryOperations
Tests fundamental CRUD operations:
- Initialization (empty and with items)
- Adding items
- Removing items (existing and non-existent)
- Getting items by ID
- Updating items
- Clearing inventory

### 2. TestCoinQueries
Tests coin-specific aggregation queries:
- Get items by coin
- Get total quantity by coin
- Get available quantity by coin
- Get locked quantity by coin

### 3. TestLockingInvariants
Validates critical locking invariants:
- Total quantity = available + locked (per coin)
- No negative quantities allowed
- Per-item quantity = available + locked

### 4. TestValueCalculations
Tests financial calculations with locked quantities:
- Total value by coin
- Weighted average price
- Total portfolio value
- Edge cases (zero quantity)

### 5. TestCoinSummary
Tests the coin summary aggregation:
- Complete summary generation
- Empty inventory handling

### 6. TestBackwardCompatibility
Tests backward compatibility features:
- `__getitem__` for coin access
- `__len__` for item count
- `__iter__` for iteration

### 7. TestFIFOLotSelection
Tests FIFO (First-In-First-Out) lot selection:
- Ordering by buy price (lowest first)
- Partial lot locking simulation

### 8. TestConcurrentLocks
Tests concurrent locking scenarios:
- Multiple locks on same coin
- Insufficient quantity handling
- Per-position tracking

### 9. TestUnlockSemantics
Tests unlock operations:
- Full unlock (all locked quantity released)
- Partial unlock (reduce locked, increase available)
- Over-unlock (clamping to zero)
- Unlock after position cancel

### 10. TestEdgeCases
Tests edge cases and boundary conditions:
- Empty inventory queries
- Multiple sequential operations
- Zero quantity items
- Very small quantities (precision)
- Very large quantities

### 11. TestMultipleLots
Tests scenarios with multiple lots per coin:
- FIFO selection across multiple lots
- Weighted average across lots with different lock states

### 12. TestStatePersistence
Tests state serialization and restoration:
- Inventory state preservation
- Recovery after serialization

## Running the Tests

### Local Development

```bash
# Run all inventory manager tests
ENVIRONMENT=GITLAB .venv/bin/python -m pytest tests/portfolio/test_inventory_manager.py -v

# Run specific test class
ENVIRONMENT=GITLAB .venv/bin/python -m pytest tests/portfolio/test_inventory_manager.py::TestLockingInvariants -v

# Run with coverage report
ENVIRONMENT=GITLAB .venv/bin/coverage run -m pytest tests/portfolio/test_inventory_manager.py
ENVIRONMENT=GITLAB .venv/bin/coverage report --include="src/portfolio/inventory_manager.py"
```

### CI/CD

In CI environments, set the `ENVIRONMENT=GITLAB` variable to ensure Kivy runs in headless mode:

```bash
ENVIRONMENT=GITLAB make ut
```

## Test Fixtures

### `empty_inventory_manager`
Creates an empty `InventoryManager` instance for testing initialization and basic operations.

### `sample_inventory_items`
Creates a list of 5 sample inventory items with various states:
- 3 BTC lots (different prices, various lock states)
- 1 ETH lot (partially locked)
- 1 USDC lot (fully available)

### `inventory_manager_with_items`
Creates a pre-populated `InventoryManager` with the `sample_inventory_items`.

## Key Testing Patterns

1. **Invariant Validation**: All tests verify that `total = available + locked` holds
2. **Edge Case Coverage**: Tests include zero quantities, very small/large numbers, non-existent items
3. **State Isolation**: Each test uses fresh fixtures to ensure independence
4. **Precision Handling**: Uses `pytest.approx()` for floating-point comparisons
5. **Comprehensive Coverage**: Tests all public methods and properties

## Dependencies

- pytest >= 8.0
- pytest-cov (for coverage reports)
- src.portfolio.inventory_manager.InventoryManager
- src.common.identifiers.InventoryItem

## Notes

- The `InventoryManager` class provides aggregation and query methods but does not implement lock/unlock logic itself
- Actual locking/unlocking is handled by `PortfolioUI._lock_quantities_fifo()` and `_unlock_quantities_fifo()`
- These tests validate that the manager correctly aggregates and reports locked/available quantities
- All tests pass and achieve 100% line coverage on the inventory_manager.py module
