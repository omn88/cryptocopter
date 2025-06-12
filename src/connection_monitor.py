#!/usr/bin/env python3
"""
Connection monitoring utilities for tracking and improving network resilience.
"""

import asyncio
import logging
import socket
import time
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("connection_monitor")


class ConnectionStatus(Enum):
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


@dataclass
class ConnectionMetrics:
    status: ConnectionStatus
    quality_score: int  # 0-100
    last_message_time: float
    seconds_since_last_message: int
    recent_message_count: int
    websocket_error_count: int
    network_latency_ms: Optional[float] = None
    uptime_percentage: float = 0.0


class ConnectionMonitor:
    """Enhanced connection monitoring and resilience manager"""

    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self.status = ConnectionStatus.CONNECTED
        self.quality_score = 100
        self.last_message_time = time.time()
        self.recent_message_timestamps: List[float] = []
        self.max_recent_messages = 50
        self.websocket_error_count = 0
        self.last_check_time = time.time()
        self.alerts_sent: set[str] = set()

        # Network monitoring
        self.network_check_hosts = [
            "www.binance.com",
            "api.binance.com",
            "stream.binance.com:9443",
        ]
        self.last_network_check = 0.0
        self.network_check_interval = 60  # Check network every minute

        # Connection history for uptime calculation
        self.connection_history: List[tuple] = []  # (timestamp, status)
        self.start_time = time.time()

    def record_message_received(self):
        """Record a successful WebSocket message"""
        current_time = time.time()
        self.last_message_time = current_time
        self.recent_message_timestamps.append(current_time)

        # Keep only recent messages
        if len(self.recent_message_timestamps) > self.max_recent_messages:
            self.recent_message_timestamps.pop(0)

        # Improve status if we were degraded
        if self.status == ConnectionStatus.DEGRADED:
            self.status = ConnectionStatus.CONNECTED
            logger.info("Connection status improved to CONNECTED")
            self.alerts_sent.discard("DEGRADED")
            self._record_status_change()

    def record_error(self):
        """Record a connection error"""
        current_time = time.time()
        time_since_last_message = current_time - self.last_message_time

        # Classify error severity based on time since last message
        if time_since_last_message > 300:  # 5 minutes
            new_status = ConnectionStatus.DISCONNECTED
        elif time_since_last_message > 60:  # 1 minute
            new_status = ConnectionStatus.DEGRADED
        else:
            new_status = self.status  # Keep current status for minor errors

        if new_status != self.status:
            self.status = new_status
            self._record_status_change()

            # Send alerts for new status
            if str(new_status.value) not in self.alerts_sent:
                if new_status == ConnectionStatus.DISCONNECTED:
                    logger.error(
                        "Connection status: DISCONNECTED (no messages for %ds)",
                        int(time_since_last_message),
                    )
                elif new_status == ConnectionStatus.DEGRADED:
                    logger.warning(
                        "Connection status: DEGRADED (no messages for %ds)",
                        int(time_since_last_message),
                    )
                self.alerts_sent.add(new_status.value)

        self.websocket_error_count += 1

    def _record_status_change(self):
        """Record status change for uptime calculation"""
        self.connection_history.append((time.time(), self.status))
        # Keep only last 24 hours of history
        cutoff_time = time.time() - 86400
        self.connection_history = [
            (ts, status) for ts, status in self.connection_history if ts > cutoff_time
        ]

    async def check_network_connectivity(self) -> bool:
        """Check basic network connectivity to key endpoints"""
        current_time = time.time()
        if current_time - self.last_network_check < self.network_check_interval:
            return True  # Skip if checked recently

        self.last_network_check = current_time

        for host in self.network_check_hosts:
            try:
                # Extract hostname from host:port if needed
                hostname = host.split(":")[0]

                # DNS resolution test
                start_time = time.time()
                socket.gethostbyname(hostname)
                latency_ms = (time.time() - start_time) * 1000

                logger.debug("Network check to %s: %.1fms", hostname, latency_ms)
                return True

            except socket.gaierror as e:
                logger.warning("Network check failed for %s: %s", host, e)
                continue
            except Exception as e:
                logger.warning("Unexpected error checking %s: %s", host, e)
                continue

        logger.error("All network connectivity checks failed")
        return False

    def calculate_quality_score(self) -> int:
        """Calculate connection quality score (0-100)"""
        current_time = time.time()

        # Clean old timestamps
        cutoff_time = current_time - 300  # 5 minutes
        self.recent_message_timestamps = [
            ts for ts in self.recent_message_timestamps if ts > cutoff_time
        ]

        if not self.recent_message_timestamps:
            self.quality_score = 0
            return 0

        # Time since last message component (0-50 points)
        time_since_last = current_time - self.last_message_time
        recency_score = max(0, 50 - (time_since_last / 60 * 50))

        # Message frequency component (0-50 points)
        message_count = len(self.recent_message_timestamps)
        frequency_score = min(50, message_count)  # 50 messages = 50 points

        self.quality_score = int(recency_score + frequency_score)

        # Log quality degradation
        if self.quality_score < 50 and "LOW_QUALITY" not in self.alerts_sent:
            logger.warning(
                "Connection quality degraded: %d%% (recent messages: %d, last: %ds ago)",
                self.quality_score,
                message_count,
                int(time_since_last),
            )
            self.alerts_sent.add("LOW_QUALITY")
        elif self.quality_score >= 80:
            self.alerts_sent.discard("LOW_QUALITY")

        return self.quality_score

    def calculate_uptime_percentage(self) -> float:
        """Calculate uptime percentage over the last 24 hours"""
        current_time = time.time()
        time_period = min(current_time - self.start_time, 86400)  # Max 24 hours

        if time_period < 60:  # Less than 1 minute, assume 100%
            return 100.0

        connected_time = 0.0
        last_time = current_time - time_period
        last_status = ConnectionStatus.CONNECTED  # Assume connected at start

        for timestamp, status in self.connection_history:
            if timestamp > last_time:
                # Add time in previous status
                if last_status == ConnectionStatus.CONNECTED:
                    connected_time += timestamp - last_time
                last_time = timestamp
                last_status = status

        # Add remaining time in current status
        if self.status == ConnectionStatus.CONNECTED:
            connected_time += current_time - last_time

        return min(100.0, (connected_time / time_period) * 100)

    def get_metrics(self) -> ConnectionMetrics:
        """Get current connection metrics"""
        current_time = time.time()
        self.calculate_quality_score()
        uptime = self.calculate_uptime_percentage()

        return ConnectionMetrics(
            status=self.status,
            quality_score=self.quality_score,
            last_message_time=self.last_message_time,
            seconds_since_last_message=int(current_time - self.last_message_time),
            recent_message_count=len(self.recent_message_timestamps),
            websocket_error_count=self.websocket_error_count,
            uptime_percentage=uptime,
        )

    async def run_periodic_checks(self):
        """Run periodic connection health checks"""
        while True:
            try:
                await asyncio.sleep(self.check_interval)

                # Update quality score
                self.calculate_quality_score()

                # Check network connectivity if status is poor
                if self.status != ConnectionStatus.CONNECTED:
                    network_ok = await self.check_network_connectivity()
                    if not network_ok and self.status != ConnectionStatus.DISCONNECTED:
                        logger.warning("Network connectivity issues detected")

                # Log periodic status update
                metrics = self.get_metrics()
                if (
                    metrics.quality_score < 80
                    or metrics.status != ConnectionStatus.CONNECTED
                ):
                    logger.info(
                        "Connection health: %s, quality: %d%%, uptime: %.1f%%",
                        metrics.status.value,
                        metrics.quality_score,
                        metrics.uptime_percentage,
                    )

            except Exception as e:
                logger.error("Error in connection monitor periodic check: %s", e)

    def get_status_summary(self) -> str:
        """Get a human-readable status summary"""
        metrics = self.get_metrics()

        status_emoji = {
            ConnectionStatus.CONNECTED: "🟢",
            ConnectionStatus.DEGRADED: "🟡",
            ConnectionStatus.DISCONNECTED: "🔴",
        }

        return (
            f"{status_emoji[metrics.status]} {metrics.status.value} | "
            f"Quality: {metrics.quality_score}% | "
            f"Uptime: {metrics.uptime_percentage:.1f}% | "
            f"Last message: {metrics.seconds_since_last_message}s ago"
        )


# Global instance for easy access
connection_monitor = ConnectionMonitor()


async def start_connection_monitoring():
    """Start the global connection monitor"""
    logger.info("Starting connection monitoring...")
    await connection_monitor.run_periodic_checks()


def get_connection_status() -> ConnectionMetrics:
    """Get current connection status"""
    return connection_monitor.get_metrics()
