"""Data models for the unified HP Manager interface.

This module defines the data structures used in the new unified HP Manager
that replaces the tabbed Buy/Sell interface with a streamlined hierarchical view.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict, Any, Set
from enum import Enum


class PositionType(Enum):
    """Type of position in the unified HP view."""

    HP = "HP"  # Parent HP position
    BUY = "BUY"  # Buy child position (real or dummy)
    SELL = "SELL"  # Sell child position


class PositionState(Enum):
    """State of a position."""

    NEW = "NEW"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    BUYING = "BUYING"
    SELLING = "SELLING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SOLD = "SOLD"
    CLOSED = "CLOSED"


@dataclass
class UnifiedPosition:
    """Unified position data structure for hierarchical HP display.

    This structure supports both parent HP positions and their child buy/sell positions
    with essential columns only for a clean, streamlined interface.
    """

    # Essential display fields
    position_type: PositionType
    hp_id: str
    coin: str
    quantity: str  # Formatted quantity string
    price: str  # Context-appropriate price (buy avg, sell target, current)
    progress: str  # Completion percentage (e.g., "75%")
    net: str  # P&L string (e.g., "+$1,250", "-$50")
    state: str  # Human-readable state

    # Hierarchy management
    is_child: bool = False
    parent_hp_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    is_expanded: bool = False

    # Special flags
    is_dummy: bool = False  # For inventory-based buy positions in sell-only HPs
    has_children: bool = False

    # Raw data for calculations (not displayed directly)
    raw_quantity: float = 0.0
    raw_price: float = 0.0
    raw_net: float = 0.0
    progress_percent: float = 0.0

    # UI state
    can_cancel: bool = False
    can_sell: bool = False
    can_edit: bool = False

    # Additional UI fields for action buttons and side tracking
    action_buttons: List[str] = field(default_factory=list)
    side: str = "UNKNOWN"

    def get_type_display(self) -> str:
        """Get display string for position type."""
        if self.position_type == PositionType.HP:
            return "HP"
        elif self.position_type == PositionType.BUY:
            return "🟢 BUY" if not self.is_dummy else "🟡 BUY"
        else:  # SELL
            return "🔴 SELL"

    def get_quantity_display(self) -> str:
        """Get formatted quantity for display."""
        return self.quantity

    def get_price_display(self) -> str:
        """Get formatted price for display."""
        return self.price

    def get_progress_display(self) -> str:
        """Get formatted progress for display."""
        return self.progress

    def get_net_display(self) -> str:
        """Get formatted net P&L for display."""
        return self.net

    def get_state_display(self) -> str:
        """Get formatted state for display."""
        return self.state


@dataclass
@dataclass
class HPConfiguration:
    """Configuration data for HP creation modals."""

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


@dataclass
class UnifiedHPData:
    """Container for all unified HP data."""

    positions: List[UnifiedPosition] = field(default_factory=list)
    hp_map: Dict[str, UnifiedPosition] = field(default_factory=dict)
    expanded_hp_ids: Set[str] = field(default_factory=set)

    def get_parent_positions(self) -> List[UnifiedPosition]:
        """Get all parent HP positions."""
        return [pos for pos in self.positions if pos.position_type == PositionType.HP]

    def get_children(self, parent_hp_id: str) -> List[UnifiedPosition]:
        """Get all children for a parent HP."""
        return [
            pos
            for pos in self.positions
            if pos.is_child and pos.parent_hp_id == parent_hp_id
        ]

    def get_visible_positions(self) -> List[UnifiedPosition]:
        """Get positions that should be visible in the UI (respecting expansion state)."""
        visible = []
        for pos in self.positions:
            if not pos.is_child:
                # Always show parent positions
                visible.append(pos)
                # Show children if parent is expanded
                if pos.hp_id in self.expanded_hp_ids:
                    children = self.get_children(pos.hp_id)
                    visible.extend(children)
        return visible

    def toggle_expansion(self, hp_id: str) -> bool:
        """Toggle expansion state of an HP position."""
        if hp_id in self.expanded_hp_ids:
            self.expanded_hp_ids.remove(hp_id)
            return False
        else:
            self.expanded_hp_ids.add(hp_id)
            return True

    def add_position(self, position: UnifiedPosition) -> None:
        """Add a position to the data structure."""
        self.positions.append(position)
        self.hp_map[position.hp_id] = position

        # Update parent's children list and has_children flag
        if position.is_child and position.parent_hp_id:
            parent = self.hp_map.get(position.parent_hp_id)
            if parent:
                if position.hp_id not in parent.children:
                    parent.children.append(position.hp_id)
                parent.has_children = len(parent.children) > 0

    def update_position(self, hp_id: str, **kwargs: Any) -> None:
        """Update an existing position."""
        position = self.hp_map.get(hp_id)
        if position:
            for key, value in kwargs.items():
                if hasattr(position, key):
                    setattr(position, key, value)

    def remove_position(self, hp_id: str) -> None:
        """Remove a position and clean up references."""
        position = self.hp_map.get(hp_id)
        if not position:
            return

        # Remove from positions list
        self.positions = [pos for pos in self.positions if pos.hp_id != hp_id]

        # Clean up parent references
        if position.is_child and position.parent_hp_id:
            parent = self.hp_map.get(position.parent_hp_id)
            if parent and hp_id in parent.children:
                parent.children.remove(hp_id)
                parent.has_children = len(parent.children) > 0

        # Remove from map
        del self.hp_map[hp_id]

        # Remove from expanded set
        self.expanded_hp_ids.discard(hp_id)

    def clear_all(self) -> None:
        """Clear all positions and reset state."""
        self.positions.clear()
        self.hp_map.clear()
        self.expanded_hp_ids.clear()


def create_parent_hp_position(
    hp_id: str, coin: str, state: str = "NEW"
) -> UnifiedPosition:
    """Create a parent HP position."""
    return UnifiedPosition(
        position_type=PositionType.HP,
        hp_id=hp_id,
        coin=f"{coin}→USD",  # Default format, will be updated based on actual trade
        quantity="0.0",
        price="$0.00",
        progress="0%",
        net="$0.00",
        state=state,
        is_child=False,
        has_children=False,
        can_cancel=True,
    )


def create_buy_child_position(
    hp_id: str, parent_hp_id: str, coin: str, is_dummy: bool = False
) -> UnifiedPosition:
    """Create a buy child position (real or dummy)."""
    child_id = f"{parent_hp_id}_buy"
    return UnifiedPosition(
        position_type=PositionType.BUY,
        hp_id=child_id,
        coin=coin,
        quantity="0.0",
        price="$0.00",
        progress="0%",
        net="$0.00",
        state="COMPLETED" if is_dummy else "NEW",
        is_child=True,
        parent_hp_id=parent_hp_id,
        is_dummy=is_dummy,
        can_cancel=not is_dummy,
    )


def create_sell_child_position(
    hp_id: str, parent_hp_id: str, coin: str, hop_suffix: str = "a"
) -> UnifiedPosition:
    """Create a sell child position (for multihop: 'a', 'b', etc.)."""
    child_id = f"{parent_hp_id}{hop_suffix}"
    return UnifiedPosition(
        position_type=PositionType.SELL,
        hp_id=child_id,
        coin=coin,
        quantity="0.0",
        price="$0.00",
        progress="0%",
        net="$0.00",
        state="NEW",
        is_child=True,
        parent_hp_id=parent_hp_id,
        can_cancel=True,
    )


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
