#!/usr/bin/env python3
"""
Test script to verify WebSocket error handling for keepalive timeout issues.
This script simulates the error messages that appear with python-binance + Python 3.12.
"""

import asyncio
import logging

logger = logging.getLogger("test_websocket_fix")


class MockBroker:
    """Mock broker to test error handler functionality"""

    def __init__(self):
        self._error_handler = None

    def set_error_handler(self, handler):
        self._error_handler = handler
        logger.info("Error handler set successfully")

    async def simulate_keepalive_error(self):
        if self._error_handler:
            error_msg = {
                "e": "error",
                "type": "ConnectionClosedError",
                "m": "sent 1011 (internal error) keepalive ping timeout; no close frame received",
            }
            logger.info("Simulating keepalive timeout error...")
            await self._error_handler(error_msg)
        else:
            logger.warning("No error handler set")


async def test_websocket_error_handling(strategy_executor_fixture):
    """Test the WebSocket error handling functionality using the fixture."""
    logger.info("Starting WebSocket error handling test...")

    # Assign mock broker
    mock_broker = MockBroker()
    strategy_executor = strategy_executor_fixture
    strategy_executor.broker = mock_broker
    mock_broker.set_error_handler(strategy_executor._handle_websocket_error)

    # Give the strategy executor time to initialize
    await asyncio.sleep(1)

    # Test 1: Simulate a keepalive timeout error
    logger.info("Test 1: Simulating keepalive timeout error...")
    await mock_broker.simulate_keepalive_error()

    # Test 2: Simulate multiple errors to test suppression
    logger.info("Test 2: Simulating multiple errors (should be suppressed)...")
    for i in range(5):
        await mock_broker.simulate_keepalive_error()
        await asyncio.sleep(0.1)

    logger.info("WebSocket error handling test completed successfully!")
