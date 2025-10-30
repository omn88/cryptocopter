# HP Simulator V2 - Module Structure

## Files Created

### `tests/strategies/hp_v2/hp_simulator_v2.py` (180 lines)

A dedicated simulator module for V2 testing, following the same pattern as `tests/strategies/hp/hp_simulator.py`.

**Key Components:**

#### HPSimulatorV2 Class
```python
class HPSimulatorV2:
    """Simulator for HP Manager V2 end-to-end tests."""
    
    def __init__(self, front: HpFront, back: HpExecutorV2)
    
    def new_price(self, price: float, symbol: str = "BTCUSDC")
        """Send ticker price update to V2 executor."""
    
    def simulate_buy_position(self, symbol: str, budget: float = 1000.0, ...)
        """Simulate creating a buy position from the frontend."""
    
    async def assert_default_buy_position(self)
        """Assert that default buy position was created correctly."""
    
    async def wait_for_state(self, expected_state: PositionLifecycleState, timeout: float = 2.0)
        """Wait for V2 strategy to reach expected lifecycle state."""
    
    def get_current_state(self) -> PositionLifecycleState
        """Get current lifecycle state of V2 strategy."""
    
    def assert_state(self, expected_state: PositionLifecycleState)
        """Assert current state matches expected state."""
```

**Key Architectural Differences from V1:**

| Aspect | V1 (HPSimulator) | V2 (HPSimulatorV2) |
|--------|------------------|-------------------|
| Backend Type | StrategyExecutor | HpExecutorV2 |
| Strategy Access | `back.strategies["1000"]` | `back.strategy` |
| Worker Queue | `strategy.worker_queue` | `back.worker_queue` |
| State Type | `State` (12 states) | `PositionLifecycleState` (5 states) |

## Updated Test File

### `tests/strategies/hp_v2/test_hp_manager_v2_e2e.py`

Simplified to ~90 lines by moving simulator to dedicated module:

```python
from tests.strategies.hp_v2.hp_simulator_v2 import HPSimulatorV2

async def test_get_default_buy_position_v2(frontend_backend_v2_setup):
    front, back = frontend_backend_v2_setup
    sim = HPSimulatorV2(front=front, back=back)
    
    # V2 executor should be running
    assert back.thread.is_alive()
    
    # Initial state should be IDLE
    assert back.strategy.lifecycle_state == PositionLifecycleState.IDLE
    
    # Simulate buy position
    sim.simulate_buy_position(symbol="BTCUSDC")
    await sim.assert_default_buy_position()
```

## Module Structure

```
tests/
└─ strategies/
   ├─ hp/                          # V1 tests
   │  ├─ hp_simulator.py           # V1 simulator
   │  └─ test_hp_manager_e2e.py    # V1 E2E tests
   │
   └─ hp_v2/                       # V2 tests
      ├─ hp_simulator_v2.py        # V2 simulator (NEW)
      ├─ test_hp_manager_v2_e2e.py # V2 E2E tests
      └─ test_executor_v2_examples.py
```

## Usage Examples

### Basic Test
```python
from tests.strategies.hp_v2.hp_simulator_v2 import HPSimulatorV2

async def test_something(frontend_backend_v2_setup):
    front, back = frontend_backend_v2_setup
    sim = HPSimulatorV2(front=front, back=back)
    
    # Send price update
    sim.new_price(50000.0, symbol="BTCUSDC")
    
    # Check state
    sim.assert_state(PositionLifecycleState.IDLE)
```

### Wait for State Transition
```python
async def test_state_transition(frontend_backend_v2_setup):
    front, back = frontend_backend_v2_setup
    sim = HPSimulatorV2(front=front, back=back)
    
    # Trigger buy
    sim.new_price(49400.0)  # Below trigger
    
    # Wait for transition
    await sim.wait_for_state(PositionLifecycleState.BUYING, timeout=2.0)
```

### Get Current State
```python
def check_state(sim: HPSimulatorV2):
    current = sim.get_current_state()
    print(f"Current state: {current}")
```

## Benefits of Separate Module

✅ **Reusability** - Can be imported by any V2 test file
✅ **Maintainability** - Single source of truth for V2 test utilities
✅ **Consistency** - Follows V1 pattern (hp_simulator.py)
✅ **Clean Tests** - Test files stay focused on test logic

## Status

✅ Module created and working
✅ Test file updated to use new module
✅ No compilation errors
✅ Ready for use in all V2 E2E tests
