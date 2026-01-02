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
        """Create a configuration for very unstable network conditions.

        Optimized for production stability after Nov 25 network failure analysis.
        More aggressive timeouts to detect failures faster while maintaining robustness.
        """
        return cls(
            connection_timeout=60,  # 1 minute - reduced from 2 min for faster failure detection
            read_timeout=20,  # Reduced from 30s - detect read issues faster
            keepalive_timeout=120,  # 2 minutes - reduced from 3 min
            initial_reconnect_delay=5,  # Faster initial retry - reduced from 10s
            max_reconnect_delay=900,  # 15 minutes max - reduced from 30 min
            max_reconnect_attempts=50,  # Keep many attempts
            health_check_interval=30,  # More frequent checks - reduced from 45s
            message_timeout_threshold=180,  # 3 minutes - reduced from 5 min
            error_suppression_time=900,  # 15 minutes - reduced from 30 min
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
