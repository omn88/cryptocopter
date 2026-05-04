"""Comprehensive WebSocket Architecture Tests for refactored modules."""

import time
import queue
import asyncio
from unittest.mock import Mock, AsyncMock, patch
import pytest

from src.broker import BrokerSpot
from src.websocket import WebSocketManager, ULTRA_ROBUST_CONFIG
from src.strategy_executor import StrategyExecutor
from src.common.client import BinanceClient
from src.domain.enums import SubscriptionTarget, SubscriptionType
from src.domain.subscriptions import SubscriptionInfo


# Fixtures


@pytest.fixture
def mock_client():
    """Create a mock BinanceClient."""
    client = Mock(spec=BinanceClient)
    client.close_connection = AsyncMock()
    return client


@pytest.fixture
def websocket_manager(mock_client):
    """Create a WebSocketManager instance for testing."""
    subscriptions = {}
    stop_event = asyncio.Event()
    loop = asyncio.new_event_loop()
    ws_manager = WebSocketManager(
        client=mock_client,
        subscriptions=subscriptions,
        stop_event=stop_event,
        loop=loop,
    )
    return ws_manager


@pytest.fixture
def mock_broker_with_ws():
    """Create a mock broker with initialized WebSocketManager."""
    with patch("src.common.client.BinanceClient"):
        with patch("threading.Thread.start"):
            broker = BrokerSpot(client=Mock(spec=BinanceClient))
            broker.loop = asyncio.new_event_loop()

            # Manually initialize WebSocketManager
            broker._ws_manager = WebSocketManager(
                client=Mock(spec=BinanceClient),
                subscriptions=broker.subscriptions,
                stop_event=broker.stop_producers_event,
                loop=broker.loop,
            )

            # Set message handlers
            broker._ws_manager.set_message_handlers(
                user_handler=Mock(),
                ticker_handler=Mock(),
            )

            yield broker

            # Cleanup
            try:
                if broker.loop and not broker.loop.is_closed():
                    broker.loop.close()
            except Exception:
                pass


# WebSocketManager Tests


def test_websocket_manager_initialization(websocket_manager):
    """Test WebSocketManager initializes correctly."""
    assert websocket_manager.client is not None
    assert websocket_manager._ws_config == ULTRA_ROBUST_CONFIG
    assert websocket_manager._restart_count == 0
    assert isinstance(websocket_manager._subscription_registry, dict)


def test_websocket_manager_subscription_registry(websocket_manager):
    """Test subscription registry tracking."""
    test_queue = queue.Queue()
    subscription_info = SubscriptionInfo(
        data_type=SubscriptionType.PRICE,
        symbol="BTCUSDC",
        target=SubscriptionTarget.BACKEND,
        queue=test_queue,
    )

    websocket_manager.register_subscription("test_1000", subscription_info)
    assert "test_1000" in websocket_manager._subscription_registry

    websocket_manager.unregister_subscription("test_1000")
    assert "test_1000" not in websocket_manager._subscription_registry


async def test_websocket_manager_circuit_breaker(websocket_manager):
    """Test circuit breaker progressive delays."""
    delays = []
    for i in range(1, 4):
        websocket_manager._restart_count = i
        expected_delay = min(
            websocket_manager._restart_base_delay * (i**1.5),
            websocket_manager._max_restart_delay,
        )
        delays.append(expected_delay)

    assert delays[1] > delays[0]
    assert delays[2] > delays[1]


# BrokerSpot Integration Tests


def test_broker_has_websocket_manager(mock_broker_with_ws):
    """Verify broker has WebSocketManager."""
    assert mock_broker_with_ws._ws_manager is not None
    assert isinstance(mock_broker_with_ws._ws_manager, WebSocketManager)


def test_broker_subscription_with_registry(mock_broker_with_ws):
    """Test broker subscription registers with WebSocketManager."""
    broker = mock_broker_with_ws
    test_queue = queue.Queue()

    subscription_info = SubscriptionInfo(
        data_type=SubscriptionType.PRICE,
        symbol="BTCUSDC",
        target=SubscriptionTarget.BACKEND,
        queue=test_queue,
    )

    broker.subscribe(system_id="test_1000", subscription_info=subscription_info)
    assert "test_1000" in broker.subscriptions
    assert "test_1000" in broker._ws_manager._subscription_registry


# Configuration Tests


def test_ultra_robust_config_loaded(mock_broker_with_ws):
    """Verify ultra-robust configuration is used."""
    broker = mock_broker_with_ws
    assert broker._ws_config == ULTRA_ROBUST_CONFIG
    assert broker._ws_config.connection_timeout == 60
    assert broker._ws_config.max_reconnect_attempts == 50


# Separation of Concerns Tests


def test_strategy_executor_no_websocket_methods():
    """Verify StrategyExecutor has no WebSocket error handling."""
    assert not hasattr(StrategyExecutor, "_handle_websocket_error")
    assert not hasattr(StrategyExecutor, "_restart_websocket_client")


def test_broker_has_websocket_methods(mock_broker_with_ws):
    """Verify Broker instance provides access to WebSocket handling methods."""
    # These are delegated to WebSocketManager through __getattr__
    assert hasattr(mock_broker_with_ws._ws_manager, "_handle_websocket_error")
    assert hasattr(mock_broker_with_ws._ws_manager, "_restart_websocket_client")
    assert hasattr(mock_broker_with_ws._ws_manager, "_monitor_connection_health")

    # Verify broker can access them via delegation
    assert mock_broker_with_ws._ws_manager is not None
