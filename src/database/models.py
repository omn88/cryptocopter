"""
Database models for the trading system.

This module defines the core data models used for persistence,
focusing on recovery and multihop trade support.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
import uuid

from src.domain.inventory import (
    InventoryItem,
)  # noqa: F401  # re-exported for convenience


class PositionType(Enum):
    """Type of position."""

    BUY = "BUY"
    SELL = "SELL"


class PositionStatus(Enum):
    """Status of a position."""

    NEW = "NEW"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    CLOSED = "CLOSED"
    WAITING_PARENT = "WAITING_PARENT"
    WAITING_CHILD = "WAITING_CHILD"
    REMOTE = "REMOTE"  # For remote/virtual positions


class TradeType(Enum):
    """Type of trade execution."""

    DIRECT = "DIRECT"  # Direct trade (e.g., BTC/USDC)
    TWOHOP = "TWOHOP"  # Two-hop trade (e.g., BTC->ETH->USDC)
    CONVERT = "CONVERT"  # Binance Convert API


class OrderStatus(Enum):
    """Status of an order."""

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


@dataclass
class Position:
    """
    Core position record that can represent both buy and sell positions.
    Designed for easy recovery and multihop support.
    """

    # Core identification
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    hp_id: str = ""  # Human-readable position ID
    strategy_id: str = ""

    # Position details
    position_type: PositionType = PositionType.BUY
    status: PositionStatus = PositionStatus.NEW
    strategy_state: str = "NEW"  # Strategy execution state (NEW, BUYING, SELLING, etc.)
    symbol: str = ""
    coin: str = ""

    # Pricing and quantities
    target_price: float = 0.0
    buy_price: float = 0.0
    sell_price: float = 0.0
    quantity: float = 0.0
    realized_quantity: float = 0.0
    budget: float = 0.0

    # Multihop support
    parent_position_id: Optional[str] = None
    child_position_ids: List[str] = field(default_factory=list)
    trade_type: TradeType = TradeType.DIRECT
    hop_sequence: int = 0  # 0=original, 1=first hop, 2=second hop

    # Configuration
    order_trigger: float = 0.0
    end_currency: str = "USDC"

    # State tracking
    completeness: float = 0.0
    next_monitor_time: Optional[datetime] = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Additional data for recovery
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    """Order record for tracking individual orders."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    position_id: str = ""
    exchange_order_id: Optional[int] = None

    # Order details
    symbol: str = ""
    side: str = ""  # BUY or SELL
    order_type: str = "LIMIT"
    status: OrderStatus = OrderStatus.NEW

    # Pricing and quantities
    price: float = 0.0
    quantity: float = 0.0
    quantity_stable: float = 0.0
    realized_quantity: float = 0.0

    # Execution details
    time_in_force: str = "GTC"
    filled_at: Optional[datetime] = None

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class Trade:
    """Individual trade execution record."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    order_id: str = ""
    position_id: str = ""
    exchange_trade_id: Optional[int] = None

    # Trade details
    symbol: str = ""
    side: str = ""
    price: float = 0.0
    quantity: float = 0.0
    commission: float = 0.0
    commission_asset: str = ""

    # Timing
    executed_at: datetime = field(default_factory=datetime.now)
    created_at: datetime = field(default_factory=datetime.now)
