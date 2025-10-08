"""WebSocket components for Binance real-time data streams.

This module provides WebSocket management, configuration, and utilities
for handling real-time data streams from Binance.

Components:
- WebSocketManager: Manages connections, health monitoring, and recovery
- WebSocketConfig: Configuration presets for different network conditions
"""

from src.websocket.manager import WebSocketManager
from src.websocket.config import (
    WebSocketConfig,
    DEFAULT_CONFIG,
    ROBUST_CONFIG,
    ULTRA_ROBUST_CONFIG,
)

__all__ = [
    "WebSocketManager",
    "WebSocketConfig",
    "DEFAULT_CONFIG",
    "ROBUST_CONFIG",
    "ULTRA_ROBUST_CONFIG",
]
