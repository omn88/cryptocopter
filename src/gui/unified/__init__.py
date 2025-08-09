"""Unified HP Manager components.

This package contains the unified HP interface components that replace
the overengineered tabbed Buy/Sell interface with a streamlined
hierarchical view and modal configurators.

Key components:
- models.py: Data structures for unified HP display
- modal_configurators.py: Modal dialogs for HP creation
- unified_hp_manager.py: Main widget replacing tabbed interface
"""

from .models import (
    UnifiedPosition,
    UnifiedHPData,
    HPConfiguration,
    PositionType,
    PositionState,
)
from .modal_configurators import BuyHPModal, SellHPModal
from .unified_hp_manager import UnifiedHPManager

__all__ = [
    "UnifiedPosition",
    "UnifiedHPData",
    "HPConfiguration",
    "PositionType",
    "PositionState",
    "BuyHPModal",
    "SellHPModal",
    "UnifiedHPManager",
]
