"""
WebSocket configuration for improving connection stability.

This module provides configuration settings to handle WebSocket connection issues,
particularly timeout problems during handshake and keepalive timeouts.
"""

import logging
from dataclasses import dataclass

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

    @classmethod
    def create_ultra_robust_config(cls) -> "WebSocketConfig":
        """Create a configuration for very unstable network conditions"""
        return cls(
            connection_timeout=120,  # 2 minutes for initial connection
            read_timeout=30,  # Longer read timeout
            keepalive_timeout=180,  # 3 minutes before considering connection dead
            initial_reconnect_delay=10,  # Start with 10 second delay
            max_reconnect_delay=1800,  # 30 minutes max delay
            max_reconnect_attempts=50,  # Many more attempts
            health_check_interval=45,  # Check every 45 seconds
            message_timeout_threshold=300,  # 5 minutes before timeout warning
            error_suppression_time=1800,  # 30 minutes suppression
            max_errors_before_resubscribe=5,  # Lower threshold for resubscribe
        )

    def log_config(self):
        """Log the current configuration"""
        logger.debug("WebSocket Configuration:")
        logger.debug("  Connection timeout: %ss", self.connection_timeout)
        logger.debug("  Read timeout: %ss", self.read_timeout)
        logger.debug("  Keepalive timeout: %ss", self.keepalive_timeout)
        logger.debug("  Max reconnect attempts: %s", self.max_reconnect_attempts)
        logger.debug("  Health check interval: %ss", self.health_check_interval)


# Default configuration instance
DEFAULT_CONFIG = WebSocketConfig()

# Robust configuration for production environments with poor connectivity
ROBUST_CONFIG = WebSocketConfig.create_robust_config()

# Ultra-robust configuration for very unstable network conditions
ULTRA_ROBUST_CONFIG = WebSocketConfig.create_ultra_robust_config()
