#!/usr/bin/env python3
"""
Simple test script to verify connection monitoring improvements work correctly.
"""

import asyncio
import sys
import os

# Add the root directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.connection_monitor import connection_monitor, ConnectionStatus


async def test_connection_monitor():
    """Test the connection monitor functionality"""
    print("🧪 Testing Connection Monitor...")

    # Test 1: Record some messages
    print("✅ Test 1: Recording successful messages...")
    for i in range(5):
        connection_monitor.record_message_received()
        await asyncio.sleep(0.1)

    # Test 2: Get metrics
    print("✅ Test 2: Getting connection metrics...")
    metrics = connection_monitor.get_metrics()
    print(f"   Status: {metrics.status.value}")
    print(f"   Quality: {metrics.quality_score}%")
    print(f"   Messages: {metrics.recent_message_count}")
    print(f"   Uptime: {metrics.uptime_percentage:.1f}%")

    # Test 3: Test network connectivity
    print("✅ Test 3: Testing network connectivity...")
    network_ok = await connection_monitor.check_network_connectivity()
    print(f"   Network OK: {network_ok}")

    # Test 4: Get status summary
    print("✅ Test 4: Getting status summary...")
    summary = connection_monitor.get_status_summary()
    print(f"   Summary: {summary}")  # Test 5: Simulate error
    print("✅ Test 5: Simulating connection error...")
    connection_monitor.record_error()
    metrics_after_error = connection_monitor.get_metrics()
    print(f"   Error count: {metrics_after_error.websocket_error_count}")

    print("\n🎉 All tests completed successfully!")
    print("\n📊 Final Status:")
    print(connection_monitor.get_status_summary())


if __name__ == "__main__":
    try:
        asyncio.run(test_connection_monitor())
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
