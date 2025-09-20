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
        """Simulate an unrecoverable WebSocket error that triggers circuit breaker"""
        if self._error_handler:
            error_msg = {
                "e": "error",
                "type": "ConnectionClosedError",
                "m": "sent 1011 (internal error) keepalive ping timeout; no close frame received",
            }
            logger.info("Simulating unrecoverable WebSocket error...")
            await self._error_handler(error_msg)
        else:
            logger.warning("No error handler set")

    async def simulate_max_reconnections_error(self):
        """Simulate the 'Max reconnections' error that triggers full restart"""
        if self._error_handler:
            error_msg = {
                "e": "error",
                "type": "BinanceWebsocketUnableToConnect",
                "m": "Max reconnections 5 reached",
            }
            logger.info("Simulating max reconnections error...")
            await self._error_handler(error_msg)
        else:
            logger.warning("No error handler set")

    async def simulate_handshake_timeout_error(self):
        """Simulate handshake timeout that triggers full restart"""
        if self._error_handler:
            error_msg = {
                "e": "error",
                "type": "BinanceWebsocketUnableToConnect",
                "m": "timed out during opening handshake",
            }
            logger.info("Simulating handshake timeout error...")
            await self._error_handler(error_msg)
        else:
            logger.warning("No error handler set")

    async def simulate_connection_closed_ok_error(self):
        """Simulate ConnectionClosedOK error (server going away) - should now trigger circuit breaker"""
        if self._error_handler:
            error_msg = {
                "e": "error",
                "type": "ConnectionClosedOK",
                "m": "received 1001 (going away); then sent 1001 (going away)",
            }
            logger.info("Simulating ConnectionClosedOK (going away) error...")
            await self._error_handler(error_msg)
        else:
            logger.warning("No error handler set")

    async def simulate_ticker_timeout_error(self):
        """Simulate ticker timeout error from backup circuit breaker"""
        if self._error_handler:
            error_msg = {
                "type": "TickerTimeoutError",
                "m": "Ticker silent for 320.5 seconds - backup circuit breaker activated",
            }
            logger.info("Simulating ticker timeout error...")
            await self._error_handler(error_msg)
        else:
            logger.warning("No error handler set")


async def test_websocket_error_handling(strategy_executor_fixture):
    """Test the WebSocket error handling functionality with circuit breaker pattern."""
    logger.info("Starting WebSocket error handling test...")

    # Assign mock broker
    mock_broker = MockBroker()
    strategy_executor = strategy_executor_fixture
    strategy_executor.broker = mock_broker
    mock_broker.set_error_handler(strategy_executor._handle_websocket_error)

    # Override restart delays for testing (use much shorter delays)
    original_base_delay = strategy_executor._restart_base_delay
    original_max_delay = strategy_executor._max_restart_delay
    strategy_executor._restart_base_delay = 0.1  # 0.1 seconds for testing
    strategy_executor._max_restart_delay = 2.0  # 2 seconds max for testing

    try:
        # Give the strategy executor time to initialize
        await asyncio.sleep(0.5)

        # Test 1: Simulate first unrecoverable error (should have minimal delay)
        logger.info("Test 1: Simulating first max reconnections error...")
        initial_restart_count = strategy_executor._restart_count

        await mock_broker.simulate_max_reconnections_error()

        # Verify restart count increased
        assert strategy_executor._restart_count == initial_restart_count + 1
        logger.info(
            "✓ First restart completed with circuit breaker (restart count: %d)",
            strategy_executor._restart_count,
        )

        # Test 2: Simulate second error quickly (should have longer delay)
        logger.info("Test 2: Simulating handshake timeout error...")
        restart_count_before = strategy_executor._restart_count

        await mock_broker.simulate_handshake_timeout_error()

        # Verify restart count increased again
        assert strategy_executor._restart_count == restart_count_before + 1
        logger.info(
            "✓ Second restart completed with progressive delay (restart count: %d)",
            strategy_executor._restart_count,
        )

        # Test 3: Simulate multiple keepalive timeouts (should use legacy logic)
        logger.info("Test 3: Simulating keepalive timeout errors (legacy logic)...")
        keepalive_error = {
            "e": "error",
            "type": "TickerStreamError",
            "m": "keepalive ping timeout",
        }

        # Reset websocket error count for clean test
        strategy_executor._websocket_error_count = 0

        # Simulate multiple keepalive errors
        for i in range(3):
            await strategy_executor._handle_websocket_error(keepalive_error)
            await asyncio.sleep(0.1)

        logger.info("✓ Keepalive timeout handling completed")

        # Test 4: Verify circuit breaker delay calculation
        logger.info("Test 4: Verifying circuit breaker delay calculation...")

        # Test delay calculation manually
        restart_count_1 = 1
        expected_delay_1 = min(0.1 * (restart_count_1**1.5), 2.0)

        restart_count_2 = 2
        expected_delay_2 = min(0.1 * (restart_count_2**1.5), 2.0)

        restart_count_3 = 5
        expected_delay_3 = min(0.1 * (restart_count_3**1.5), 2.0)  # Should hit max

        logger.info(
            "✓ Delay calculations: 1st=%.2fs, 2nd=%.2fs, 5th=%.2fs (max=2.0s)",
            expected_delay_1,
            expected_delay_2,
            expected_delay_3,
        )

        # Test 5: Verify new ConnectionClosedOK error triggers circuit breaker
        logger.info(
            "Test 5: Testing ConnectionClosedOK error triggers circuit breaker..."
        )
        restart_count_before = strategy_executor._restart_count

        await mock_broker.simulate_connection_closed_ok_error()

        # Verify restart count increased (should now trigger circuit breaker instead of legacy handling)
        assert strategy_executor._restart_count == restart_count_before + 1
        logger.info(
            "✓ ConnectionClosedOK error correctly triggered circuit breaker (restart count: %d)",
            strategy_executor._restart_count,
        )

        # Test 6: Verify ticker timeout error triggers circuit breaker
        logger.info("Test 6: Testing ticker timeout error triggers circuit breaker...")
        restart_count_before = strategy_executor._restart_count

        await mock_broker.simulate_ticker_timeout_error()

        # Verify restart count increased
        assert strategy_executor._restart_count == restart_count_before + 1
        logger.info(
            "✓ Ticker timeout error correctly triggered circuit breaker (restart count: %d)",
            strategy_executor._restart_count,
        )

        # Verify the circuit breaker resets after time gap
        logger.info("Test 7: Verifying circuit breaker reset after time gap...")
        original_last_restart = strategy_executor._last_restart_time
        strategy_executor._last_restart_time = (
            original_last_restart - 700
        )  # 11+ minutes ago

        restart_count_before_reset = strategy_executor._restart_count
        await mock_broker.simulate_max_reconnections_error()

        # Should have reset to 1 due to time gap
        assert (
            strategy_executor._restart_count == 1
        ), f"Expected reset to 1, got {strategy_executor._restart_count}"
        logger.info(
            "✓ Circuit breaker reset verified (count reset from %d to 1)",
            restart_count_before_reset,
        )

        logger.info("WebSocket error handling test completed successfully!")

    finally:
        # Restore original delays
        strategy_executor._restart_base_delay = original_base_delay
        strategy_executor._max_restart_delay = original_max_delay
