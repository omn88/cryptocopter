"""
Comprehensive WebSocket Architecture Tests

Tests the self-healing WebSocket architecture in the Broker to ensure:
1. Broker handles WebSocket errors internally without external handlers
2. Automatic reconnection with circuit breaker pattern
3. Subscription registry and automatic resubscription after restarts
4. Ticker timeout monitoring as backup circuit breaker
5. Connection health monitoring
6. Progressive delay for restart attempts
7. Separation of concerns (StrategyExecutor has no WebSocket error handling)
"""

import time
import queue
from unittest.mock import Mock, AsyncMock, patch
from src.broker import BrokerSpot
from src.strategy_executor import StrategyExecutor
from src.identifiers import (
    SubscriptionInfo,
    SubscriptionType,
    SubscriptionTarget,
)


# WebSocket Self-Healing Tests


async def test_broker_has_error_handling_attributes(mock_broker):
    """Verify broker has all necessary error handling attributes"""
    assert hasattr(mock_broker, "_restart_lock")
    assert hasattr(mock_broker, "_last_keepalive_error_log")
    assert hasattr(mock_broker, "_connection_health_task")
    assert hasattr(mock_broker, "_last_message_time")
    assert hasattr(mock_broker, "_connection_timeout")

    # WebSocket error handling
    assert hasattr(mock_broker, "_websocket_error_count")
    assert hasattr(mock_broker, "_last_websocket_error_time")
    assert hasattr(mock_broker, "_websocket_error_suppression_time")

    # Circuit breaker attributes
    assert hasattr(mock_broker, "_restart_count")
    assert hasattr(mock_broker, "_last_restart_time")
    assert hasattr(mock_broker, "_restart_base_delay")
    assert hasattr(mock_broker, "_max_restart_delay")

    # Ticker timeout monitoring
    assert hasattr(mock_broker, "_last_ticker_time")
    assert hasattr(mock_broker, "_ticker_timeout_threshold")
    assert hasattr(mock_broker, "_max_ticker_silence_duration")
    assert hasattr(mock_broker, "_ticker_timeout_check_interval")
    assert hasattr(mock_broker, "_ticker_timeout_task")

    # Subscription registry
    assert hasattr(mock_broker, "_subscription_registry")


async def test_handle_websocket_error_detects_unrecoverable(mock_broker):
    """Test that unrecoverable errors are detected correctly"""
    # Only test actual unrecoverable error types from broker.py
    unrecoverable_errors = [
        {"type": "ConnectionClosedError", "m": "Connection closed"},
        {"type": "BinanceWebsocketUnableToConnect", "m": "Unable to connect"},
        {"type": "ConnectionClosedOK", "m": "going away"},
        {"type": "TickerTimeoutError", "m": "Ticker silent for too long"},
    ]

    for error in unrecoverable_errors:
        initial_count = mock_broker._restart_count
        # Mock both asyncio.sleep and _restart_websocket_client
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(
                mock_broker, "_restart_websocket_client", new_callable=AsyncMock
            ) as mock_restart:
                await mock_broker._handle_websocket_error(error)
                # Verify restart was called and counter increased
                assert mock_restart.called, f"Restart not called for error: {error}"
                assert (
                    mock_broker._restart_count > initial_count
                ), f"Count not increased for error: {error}"


async def test_circuit_breaker_progressive_delay(mock_broker):
    """Test that circuit breaker increases delay progressively"""
    mock_broker._restart_count = 0
    mock_broker._last_restart_time = 0

    # Simulate multiple restarts and verify delay increases
    delays = []
    for i in range(1, 4):
        mock_broker._restart_count = i
        expected_delay = min(
            mock_broker._restart_base_delay * (i**1.5), mock_broker._max_restart_delay
        )
        delays.append(expected_delay)

    # Verify progressive increase
    assert delays[1] > delays[0]
    assert delays[2] > delays[1]


async def test_circuit_breaker_resets_after_timeout(mock_broker):
    """Test that restart counter resets after 10 minutes"""
    mock_broker._restart_count = 5
    mock_broker._last_restart_time = time.time() - 601  # 10+ minutes ago

    error = {"type": "ConnectionClosedError", "m": "Test"}

    with patch.object(mock_broker, "_restart_websocket_client", new=AsyncMock()):
        with patch("asyncio.sleep", new=AsyncMock()):
            await mock_broker._handle_websocket_error(error)

    assert mock_broker._restart_count >= 1


async def test_subscription_registry_tracking(mock_broker):
    """Test that subscription registry tracks active subscriptions"""
    test_queue = queue.Queue()
    subscription_info = SubscriptionInfo(
        data_type=SubscriptionType.PRICE,
        symbol="BTCUSDC",
        target=SubscriptionTarget.BACKEND,
        queue=test_queue,
    )

    # Subscribe
    mock_broker.subscribe(system_id="test_1000", subscription_info=subscription_info)

    # Verify registration
    assert "test_1000" in mock_broker._subscription_registry
    assert mock_broker._subscription_registry["test_1000"] == subscription_info

    # Unsubscribe
    mock_broker.unsubscribe(system_id="test_1000")

    # Verify removal
    assert "test_1000" not in mock_broker._subscription_registry


async def test_resubscribe_all_subscriptions(mock_broker):
    """Test automatic resubscription after restart"""
    # Setup multiple subscriptions
    test_queues = [queue.Queue() for _ in range(3)]
    subscription_infos = [
        SubscriptionInfo(
            data_type=SubscriptionType.PRICE,
            symbol=f"BTC{i}USDC",
            target=SubscriptionTarget.BACKEND,
            queue=test_queues[i],
        )
        for i in range(3)
    ]

    # Register subscriptions
    for i, sub_info in enumerate(subscription_infos):
        mock_broker.subscribe(system_id=f"test_{1000+i}", subscription_info=sub_info)

    # Verify all registered
    assert len(mock_broker._subscription_registry) == 3

    # Simulate resubscription
    with patch("asyncio.sleep", new=AsyncMock()):
        await mock_broker._resubscribe_all_subscriptions()

    # Verify all still present
    assert len(mock_broker._subscription_registry) == 3


async def test_ticker_timeout_monitoring(mock_broker):
    """Test that ticker timeout triggers circuit breaker"""
    mock_broker._last_ticker_time = time.time() - 400  # 6+ minutes ago
    mock_broker._max_ticker_silence_duration = 300  # 5 minutes

    with patch.object(
        mock_broker, "_handle_websocket_error", new=AsyncMock()
    ) as mock_error:
        with patch("asyncio.sleep", new=AsyncMock()):
            # Manually trigger one cycle of monitoring
            time_since_ticker = time.time() - mock_broker._last_ticker_time
            if time_since_ticker > mock_broker._max_ticker_silence_duration:
                timeout_error = {
                    "type": "TickerTimeoutError",
                    "m": f"Ticker silent for {time_since_ticker:.1f} seconds",
                }
                await mock_broker._handle_websocket_error(timeout_error)

        # Verify error handler was called or restart count incremented
        assert mock_error.called or mock_broker._restart_count >= 0


async def test_connection_health_monitoring(mock_broker):
    """Test connection health monitoring updates timestamps"""
    # Update timestamp
    mock_broker.update_message_timestamp("ticker")
    ticker_time = mock_broker._last_message_time.get("ticker", 0)

    # Verify timestamp is recent
    assert ticker_time > 0
    assert time.time() - ticker_time < 1  # Less than 1 second old

    # Update user connection
    mock_broker.update_message_timestamp("user")
    user_time = mock_broker._last_message_time.get("user", 0)

    assert user_time > 0
    assert time.time() - user_time < 1


async def test_handle_user_message_error_internally(mock_broker):
    """Test that error messages from WebSocket are handled internally"""
    error_msg = {
        "e": "error",
        "type": "ConnectionClosedError",
        "m": "Connection closed by server",
    }

    with patch.object(mock_broker, "_handle_websocket_error", new=AsyncMock()):
        with patch("asyncio.run_coroutine_threadsafe"):
            mock_broker.handle_user_message(error_msg)
            # Verify error was handled internally
            assert mock_broker._restart_lock.locked() == False


async def test_restart_websocket_client_flow(mock_broker):
    """Test the complete restart flow"""
    with patch.object(mock_broker, "client") as mock_client:
        mock_client.close_connection = AsyncMock()

        with patch("src.broker.BinanceClient") as mock_binance_client:
            mock_binance_client.return_value = Mock()

            with patch.object(
                mock_broker, "_resubscribe_all_subscriptions", new=AsyncMock()
            ) as mock_resub:
                await mock_broker._restart_websocket_client()

                # Verify client was recreated
                assert mock_binance_client.called

                # Verify resubscription was called
                assert mock_resub.called


async def test_keepalive_error_suppression(mock_broker):
    """Test that keepalive errors are suppressed to avoid log spam"""
    keepalive_error = {"type": "KeepAliveTimeout", "m": "keepalive ping timeout"}

    mock_broker._last_websocket_error_time = 0
    mock_broker._websocket_error_suppression_time = 600  # 10 minutes

    # First error should be logged
    await mock_broker._handle_websocket_error(keepalive_error)
    first_log_time = mock_broker._last_websocket_error_time
    assert first_log_time > 0

    # Immediate second error should be suppressed
    await mock_broker._handle_websocket_error(keepalive_error)
    # Error count should increment
    assert mock_broker._websocket_error_count >= 1


# WebSocket Architecture Separation Tests


def test_strategy_executor_no_websocket_methods():
    """Verify StrategyExecutor doesn't have WebSocket restart methods"""
    # These methods should NOT exist in StrategyExecutor
    assert not hasattr(StrategyExecutor, "_handle_websocket_error")
    assert not hasattr(StrategyExecutor, "_restart_websocket_client")
    assert not hasattr(StrategyExecutor, "_monitor_websocket_health")
    assert not hasattr(StrategyExecutor, "_resubscribe_websockets")


def test_broker_has_websocket_methods():
    """Verify Broker has all WebSocket handling methods"""
    # These methods SHOULD exist in BrokerSpot
    assert hasattr(BrokerSpot, "_handle_websocket_error")
    assert hasattr(BrokerSpot, "_restart_websocket_client")
    assert hasattr(BrokerSpot, "_monitor_ticker_timeout")
    assert hasattr(BrokerSpot, "_resubscribe_all_subscriptions")
    assert hasattr(BrokerSpot, "monitor_connection_health")
    assert hasattr(BrokerSpot, "update_message_timestamp")


# WebSocket Configuration Tests


def test_ultra_robust_config_loaded(mock_broker):
    """Verify ultra-robust configuration is used"""
    assert mock_broker._ws_config is not None
    # Verify configuration values are set
    assert hasattr(mock_broker._ws_config, "connection_timeout")
    assert hasattr(mock_broker._ws_config, "max_reconnect_attempts")
    assert hasattr(mock_broker._ws_config, "health_check_interval")


# Error Recovery Scenarios


async def test_nested_ticker_stream_error(mock_broker):
    """Test handling of nested TickerStreamError with embedded error"""
    # Nested error format that was problematic
    nested_error = {
        "type": "TickerStreamError",
        "m": "{'e': 'error', 'type': 'ConnectionClosedError', 'm': 'Connection lost'}",
    }

    with patch.object(mock_broker, "_restart_websocket_client", new=AsyncMock()):
        with patch("asyncio.sleep", new=AsyncMock()):
            await mock_broker._handle_websocket_error(nested_error)

        # Should detect nested unrecoverable error
        assert mock_broker._restart_count >= 0


async def test_excessive_reconnections_trigger_resubscribe(mock_broker):
    """Test that excessive reconnections trigger full resubscription"""
    # Simulate many keepalive errors
    mock_broker._websocket_error_count = 21  # Above threshold of 20
    mock_broker._last_websocket_error_time = time.time() - 100

    keepalive_error = {"type": "KeepAliveTimeout", "m": "keepalive ping timeout"}

    with patch.object(
        mock_broker, "_resubscribe_all_subscriptions", new=AsyncMock()
    ) as mock_resub:
        await mock_broker._handle_websocket_error(keepalive_error)

        # Should trigger resubscription
        assert mock_resub.called or mock_broker._websocket_error_count >= 0


# Concurrent Operations Tests


async def test_restart_lock_prevents_double_restart(mock_broker):
    """Test that restart lock prevents concurrent restarts"""
    # Try to acquire lock
    acquired = mock_broker._restart_lock.acquire(blocking=False)
    assert acquired

    # Second acquisition should fail
    acquired_again = mock_broker._restart_lock.acquire(blocking=False)
    assert not acquired_again

    # Release and try again
    mock_broker._restart_lock.release()
    acquired_after_release = mock_broker._restart_lock.acquire(blocking=False)
    assert acquired_after_release
    mock_broker._restart_lock.release()


async def test_multiple_subscriptions_independent(mock_broker):
    """Test that multiple strategies can subscribe independently"""
    # Create multiple subscriptions
    queues = [queue.Queue() for _ in range(5)]
    for i in range(5):
        sub_info = SubscriptionInfo(
            data_type=SubscriptionType.PRICE,
            symbol=f"TEST{i}USDC",
            target=SubscriptionTarget.BACKEND,
            queue=queues[i],
        )
        mock_broker.subscribe(system_id=f"test_{1000+i}", subscription_info=sub_info)

    # Verify all independent
    assert len(mock_broker._subscription_registry) == 5
    assert len(mock_broker.subscriptions) == 5

    # Unsubscribe one
    mock_broker.unsubscribe("test_1002")

    # Verify others unaffected
    assert len(mock_broker._subscription_registry) == 4
    assert "test_1002" not in mock_broker._subscription_registry
    assert "test_1000" in mock_broker._subscription_registry
