#!/usr/bin/env python3
"""
Connection Status Display Utility

This script provides a simple way to monitor your application's connection health
during internet outages or connectivity issues. Run this script to see real-time
connection status, quality metrics, and recommendations.

Usage:
    python src/connection_status_display.py

Features:
- Real-time connection status monitoring
- Quality score tracking
- Uptime percentage calculation
- Network connectivity checks
- Recommendations for improving connectivity

Example output:
🟢 CONNECTED | Quality: 95% | Uptime: 99.2% | Last message: 3s ago
"""

import asyncio
import logging
import time
import sys
import os
from datetime import datetime

# Add the root directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from src.connection_monitor import connection_monitor, ConnectionStatus
except ImportError as e:
    print(f"Error importing connection monitor: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)

# Configure logging for this utility
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("connection_status_display")


class ConnectionStatusDisplay:
    """Display connection status in a user-friendly format"""

    def __init__(self):
        self.start_time = time.time()
        self.last_quality_alert = 0
        self.last_status_change = time.time()

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def get_status_color(self, status: ConnectionStatus) -> str:
        """Get color code for status"""
        colors = {
            ConnectionStatus.CONNECTED: "\033[92m",  # Green
            ConnectionStatus.DEGRADED: "\033[93m",  # Yellow
            ConnectionStatus.DISCONNECTED: "\033[91m",  # Red
        }
        return colors.get(status, "\033[0m")  # Default

    def get_quality_color(self, quality: int) -> str:
        """Get color code for quality score"""
        if quality >= 80:
            return "\033[92m"  # Green
        elif quality >= 50:
            return "\033[93m"  # Yellow
        else:
            return "\033[91m"  # Red

    def print_status_line(self, metrics):
        """Print a single status line"""
        reset_color = "\033[0m"

        # Status with color
        status_color = self.get_status_color(metrics.status)
        status_emoji = {
            ConnectionStatus.CONNECTED: "🟢",
            ConnectionStatus.DEGRADED: "🟡",
            ConnectionStatus.DISCONNECTED: "🔴",
        }

        # Quality with color
        quality_color = self.get_quality_color(metrics.quality_score)

        # Build status line
        timestamp = datetime.now().strftime("%H:%M:%S")
        uptime_str = f"{metrics.uptime_percentage:.1f}%"
        last_msg_str = self.format_duration(metrics.seconds_since_last_message)

        status_line = (
            f"[{timestamp}] "
            f"{status_emoji[metrics.status]} "
            f"{status_color}{metrics.status.value}{reset_color} | "
            f"Quality: {quality_color}{metrics.quality_score}%{reset_color} | "
            f"Uptime: {uptime_str} | "
            f"Last message: {last_msg_str} ago | "
            f"Messages: {metrics.recent_message_count}"
        )

        print(f"\r{status_line:<100}", end="", flush=True)

    def print_detailed_status(self, metrics):
        """Print detailed status information"""
        print("\n" + "=" * 80)
        print(
            f"📊 CONNECTION STATUS REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print("=" * 80)

        # Current status
        status_color = self.get_status_color(metrics.status)
        quality_color = self.get_quality_color(metrics.quality_score)
        reset_color = "\033[0m"

        print(f"Status: {status_color}{metrics.status.value}{reset_color}")
        print(f"Quality Score: {quality_color}{metrics.quality_score}/100{reset_color}")
        print(f"Uptime (24h): {metrics.uptime_percentage:.2f}%")
        print(f"WebSocket Errors: {metrics.websocket_error_count}")
        print(f"Recent Messages: {metrics.recent_message_count} (last 5 min)")
        print(
            f"Last Message: {self.format_duration(metrics.seconds_since_last_message)} ago"
        )

        if metrics.network_latency_ms:
            print(f"Network Latency: {metrics.network_latency_ms:.1f}ms")

        # Recommendations
        print("\n📋 RECOMMENDATIONS:")
        if metrics.status == ConnectionStatus.DISCONNECTED:
            print("• Check your internet connection")
            print("• Verify router/modem status")
            print("• Consider using mobile hotspot as backup")
            print("• Check if Binance services are accessible")
        elif metrics.status == ConnectionStatus.DEGRADED:
            print("• Monitor connection stability")
            print("• Consider restarting router if issues persist")
            print("• Check for background applications using bandwidth")
        elif metrics.quality_score < 50:
            print("• Connection quality is poor")
            print("• Consider upgrading internet plan")
            print("• Check for network interference")
        else:
            print("• Connection is healthy ✅")
            print("• No action required")

        # Troubleshooting tips
        print("\n🔧 TROUBLESHOOTING:")
        print("• If disconnected: ping www.binance.com")
        print("• Check DNS: nslookup api.binance.com")
        print("• Test different networks (mobile vs WiFi)")
        print("• Restart application if connection doesn't recover")

        print("\n" + "=" * 80)

    async def run_continuous_monitoring(self):
        """Run continuous monitoring with periodic detailed reports"""
        print("🚀 Starting Connection Status Monitor...")
        print("Press Ctrl+C to stop")
        print("\nLegend: 🟢 Connected | 🟡 Degraded | 🔴 Disconnected")
        print("-" * 80)

        last_detailed_report = 0
        detailed_report_interval = 300  # 5 minutes

        try:
            while True:
                metrics = connection_monitor.get_metrics()
                current_time = time.time()

                # Print status line
                self.print_status_line(metrics)

                # Print detailed report periodically or on status changes
                if (
                    current_time - last_detailed_report > detailed_report_interval
                    or metrics.quality_score < 30
                ):
                    self.print_detailed_status(metrics)
                    last_detailed_report = current_time

                # Alert on quality degradation
                if (
                    metrics.quality_score < 50
                    and current_time - self.last_quality_alert > 60
                ):  # Max once per minute
                    print(
                        f"\n⚠️  WARNING: Connection quality degraded to {metrics.quality_score}%"
                    )
                    self.last_quality_alert = current_time

                await asyncio.sleep(1)  # Update every second

        except KeyboardInterrupt:
            print("\n\n👋 Connection monitoring stopped by user")
        except Exception as e:
            print(f"\n❌ Error in monitoring: {e}")

    async def run_single_check(self):
        """Run a single connection check and display results"""
        print("🔍 Running connection health check...")

        # Perform network connectivity test
        network_ok = await connection_monitor.check_network_connectivity()
        metrics = connection_monitor.get_metrics()

        self.print_detailed_status(metrics)

        if not network_ok:
            print("\n🚨 NETWORK CONNECTIVITY ISSUES DETECTED!")
            print("• Unable to reach Binance endpoints")
            print("• Check your internet connection")


async def main():
    """Main entry point"""
    display = ConnectionStatusDisplay()

    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # Single check mode
        await display.run_single_check()
    else:
        # Continuous monitoring mode
        await display.run_continuous_monitoring()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        logger.error("Error running connection status display: %s", e)
        sys.exit(1)
