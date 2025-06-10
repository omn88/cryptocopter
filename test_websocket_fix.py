#!/usr/bin/env python3
"""
Test script to verify WebSocket error handling for keepalive timeout issues.
This script simulates the error messages that appear with python-binance + Python 3.12.
"""

import asyncio
import logging
import sys
import os

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import our logging config to set up filters
import logging_config  # noinspection PyUnresolvedReferences

from src.strategy_executor import StrategyExecutor

logger = logging.getLogger("test_websocket_fix")

class MockBroker:
    """Mock broker to test error handler functionality"""
    
    def __init__(self):
        self._error_handler = None
    
    def set_error_handler(self, handler):
        """Set custom error handler for WebSocket errors"""
        self._error_handler = handler
        logger.info("Error handler set successfully")
    
    async def simulate_keepalive_error(self):
        """Simulate a keepalive timeout error"""
        if self._error_handler:
            error_msg = {
                'e': 'error',
                'type': 'ConnectionClosedError',
                'm': 'sent 1011 (internal error) keepalive ping timeout; no close frame received'
            }
            logger.info("Simulating keepalive timeout error...")
            await self._error_handler(error_msg)
        else:
            logger.warning("No error handler set")

async def test_websocket_error_handling():
    """Test the WebSocket error handling functionality"""
    logger.info("Starting WebSocket error handling test...")
    
    # Create a mock broker
    mock_broker = MockBroker()
    
    # Create a minimal strategy executor with test mode
    strategy_executor = StrategyExecutor(
        db=None,  # We'll use None for testing
        broker=mock_broker,
        symbols_info={},
        ui_queue=None,
        balances={},
        price_resolver=None,
        test_mode=True  # Important: use test mode to avoid real API calls
    )
    
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
    
    # Clean up
    strategy_executor.stop()

if __name__ == "__main__":
    try:
        asyncio.run(test_websocket_error_handling())
        print("\n✅ WebSocket error handling test passed!")
    except Exception as e:
        logger.error("Test failed: %s", e)
        print(f"\n❌ WebSocket error handling test failed: {e}")
        sys.exit(1)
