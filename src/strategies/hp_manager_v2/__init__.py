"""HP Manager V2 - Clean rewrite with proper state separation and strategy pattern.

This module provides a complete rewrite of the HP (High Price) manager strategy with:
- Clean 5-state lifecycle (IDLE → BUYING → BOUGHT → SELLING → CLOSED)
- Separate order execution states (6 states for granular tracking)
- Strategy pattern for sell scenarios (direct, convert, multihop)
- Reduced complexity (40% less code than V1)
- Dedicated executor following BuyDipExecutor pattern
"""

from src.common.identifiers import OrderExecutionState, PositionLifecycleState
from src.strategies.hp_manager_v2.executor_v2 import HpExecutorV2
from src.strategies.hp_manager_v2.hp_manager_v2 import HpStrategyV2

__all__ = [
    "HpStrategyV2",
    "HpExecutorV2",
    "PositionLifecycleState",
    "OrderExecutionState",
]
