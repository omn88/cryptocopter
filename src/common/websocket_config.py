"""
WebSocket configuration for improving connection stability.

This module provides configuration settings to handle WebSocket connection issues,
particularly timeout problems during handshake and keepalive timeouts.
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WebSocketConfig:
    """Configuration for WebSocket connections"""

    # Connection timeouts
    connection_timeout: int = 30  # seconds for initial connection
    read_timeout: int = 10  # seconds for reading messages
    keepalive_timeout: int = 60  # seconds before considering connection dead

    # Reconnection settings
    initial_reconnect_delay: int = 2  # seconds
    max_reconnect_delay: int = 300  # seconds (5 minutes)
    max_reconnect_attempts: int = 10

    # Health monitoring
    health_check_interval: int = 30  # seconds
    message_timeout_threshold: int = 60  # seconds

    # Error handling
    error_suppression_time: int = 300  # seconds (5 minutes)
    max_errors_before_resubscribe: int = 20

    @classmethod
    def create_robust_config(cls) -> "WebSocketConfig":
        """Create a configuration optimized for stability over speed"""
        return cls(
            connection_timeout=60,  # Longer timeout for slow connections
            read_timeout=15,
            keepalive_timeout=90,
            initial_reconnect_delay=5,
            max_reconnect_delay=600,  # 10 minutes
            max_reconnect_attempts=15,
            health_check_interval=60,
            message_timeout_threshold=120,
            error_suppression_time=600,  # 10 minutes
            max_errors_before_resubscribe=10,
        )

    def log_config(self):
        """Log the current configuration"""
        logger.info("WebSocket Configuration:")
        logger.info("  Connection timeout: %ss", self.connection_timeout)
        logger.info("  Read timeout: %ss", self.read_timeout)
        logger.info("  Keepalive timeout: %ss", self.keepalive_timeout)
        logger.info("  Max reconnect attempts: %s", self.max_reconnect_attempts)
        logger.info("  Health check interval: %ss", self.health_check_interval)


# Default configuration instance
DEFAULT_CONFIG = WebSocketConfig()

# Robust configuration for production environments with poor connectivity
ROBUST_CONFIG = WebSocketConfig.create_robust_config()
