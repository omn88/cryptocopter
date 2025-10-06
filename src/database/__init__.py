"""
Database module for the RSI-based futures trading system.

This module provides database functionality focused on recovery and position management
for multihop trading strategies. The design prioritizes simplicity, reliability,
and cross-platform compatibility.
"""

from .trading_database import Database
from .models import (
    Position,
    Trade,
    Order,
    PositionType,
    PositionStatus,
    TradeType,
    OrderStatus,
)
from .exceptions import (
    DatabaseError,
    RecoveryError,
    DatabaseConnectionError,
    IntegrityError,
)
from .position_manager import PositionManager

__all__ = [
    "Database",
    "Position",
    "Trade",
    "Order",
    "PositionType",
    "PositionStatus",
    "TradeType",
    "OrderStatus",
    "DatabaseError",
    "RecoveryError",
    "DatabaseConnectionError",
    "IntegrityError",
    "PositionManager",
]
