"""
Database module for the RSI-based futures trading system.

This module provides database functionality focused on recovery and position management
for multihop trading strategies. The design prioritizes simplicity, reliability,
and cross-platform compatibility.
"""

from .trading_database import TradingDatabase
from .models import (
    Position,
    Trade,
    Order,
    Strategy,
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
from .recovery_service import RecoveryService
from .position_manager import PositionManager

# For backwards compatibility, alias TradingDatabase as Database
Database = TradingDatabase

__all__ = [
    "TradingDatabase",
    "Database",  # Backwards compatibility alias
    "Position",
    "Trade",
    "Order",
    "Strategy",
    "PositionType",
    "PositionStatus",
    "TradeType",
    "OrderStatus",
    "DatabaseError",
    "RecoveryError",
    "DatabaseConnectionError",
    "IntegrityError",
    "RecoveryService",
    "PositionManager",
]
