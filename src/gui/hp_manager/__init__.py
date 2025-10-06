"""HP Manager components.

This package contains HP interface components with clear separation of concerns:
- hp_config.py: Configuration data structures and formatting helpers
- modal_configurators.py: Modal dialogs for HP creation
- hpfront.py: Main HP display and coordination
"""

from .hp_config import (
    HPConfiguration,
    format_currency,
    format_percentage,
    format_quantity,
)
from .modal_configurators import BuyHPModal

__all__ = [
    "HPConfiguration",
    "format_currency",
    "format_percentage",
    "format_quantity",
    "BuyHPModal",
]
