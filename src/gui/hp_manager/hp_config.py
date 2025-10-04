"""HP Configuration and Formatting Helpers.

This module contains only the actively used data structures and helper functions
for HP Manager operations. Unused abstractions have been removed.
"""

from dataclasses import dataclass
from typing import Optional, Literal


@dataclass
class HPConfiguration:
    """Configuration data for HP creation modals.

    This is the only data model actually used by HpFront and modal_configurators.
    """

    hp_type: Literal["BUY", "SELL"]
    coin: str
    symbol: str
    hp_id: Optional[str] = None  # Generated if not provided

    # Buy-specific fields
    price_low: Optional[float] = None
    price_high: Optional[float] = None
    budget: Optional[float] = None
    order_trigger: Optional[float] = None
    mode: Optional[str] = None

    # Sell-specific fields
    quantity: Optional[float] = None
    sell_price: Optional[float] = None
    end_currency: Optional[str] = None
    inventory_source: Optional[str] = None  # For dummy buy positions


# Formatting Helper Functions (actually used throughout the codebase)


def format_currency(value: float, symbol: str = "$") -> str:
    """Format currency value for display."""
    if value == 0:
        return f"{symbol}0.00"
    elif abs(value) >= 1000:
        return f"{symbol}{value:,.0f}"
    else:
        return f"{symbol}{value:.2f}"


def format_percentage(value: float) -> str:
    """Format percentage value for display."""
    if value == 0:
        return "0%"
    return f"{value:.1f}%" if value < 100 else "100%"


def format_quantity(value: float, precision: int = 5) -> str:
    """Format quantity for display."""
    if value == 0:
        return "0.0"
    elif value < 0.001:
        return f"{value:.8f}".rstrip("0").rstrip(".")
    else:
        return f"{value:.{precision}f}".rstrip("0").rstrip(".")
