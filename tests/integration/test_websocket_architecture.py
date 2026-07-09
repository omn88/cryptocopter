"""Integration-style tests for the Kraken WS v2 WebSocket architecture."""

import asyncio
import queue
from unittest.mock import AsyncMock, Mock

import pytest

from src.broker import BrokerSpot
from src.websocket import WebSocketManager, ULTRA_ROBUST_CONFIG
from src.strategy_executor import StrategyExecutor
from src.common.client import KrakenClient
from src.domain.enums import SubscriptionTarget, SubscriptionType
from src.domain.subscriptions import SubscriptionInfo

# Fixtures


@pytest.fixture
def mock_client():
    """Create a mock KrakenClient."""
    client = Mock(spec=KrakenClient)
    client.get_ws_token = AsyncMock(return_value={"token": "test-token"})
    return client


@pytest.fixture
def websocket_manager(mock_client):
    """Create a WebSocketManager instance for testing."""
    subscriptions = {}
    stop_event = asyncio.Event()
    ws_manager = WebSocketManager(
        client=mock_client,
        subscriptions=subscriptions,
        stop_event=stop_event,
    )
    return ws_manager


@pytest.fixture
def mock_broker_with_ws(mock_client):
    """Create a mock broker with initialized WebSocketManager."""
    broker = BrokerSpot(client=Mock(spec=KrakenClient))

    # Manually initialize WebSocketManager (bypassing run())
    broker._ws_manager = WebSocketManager(
        client=mock_client,
        subscriptions=broker.subscriptions,
        stop_event=broker.stop_producers_event,
    )

    # Set message handlers
    broker._ws_manager.set_message_handlers(
        user_handler=Mock(),
        ticker_handler=Mock(),
    )

    yield broker


# WebSocketManager Tests


def test_websocket_manager_initialization(websocket_manager):
    """Test WebSocketManager initializes correctly."""
    assert websocket_manager.client is not None
    assert websocket_manager._ws_config == ULTRA_ROBUST_CONFIG
    assert websocket_manager._ticker_subscribers == {}
    assert websocket_manager._kline_subscribers == {}


def test_websocket_manager_exposes_per_symbol_subscription_api(websocket_manager):
    """Test WebSocketManager exposes the ref-counted per-symbol subscribe API."""
    assert hasattr(websocket_manager, "subscribe_ticker")
    assert hasattr(websocket_manager, "unsubscribe_ticker")
    assert hasattr(websocket_manager, "subscribe_kline")
    assert hasattr(websocket_manager, "unsubscribe_kline")
    assert hasattr(websocket_manager, "_refresh_ws_token")


async def test_websocket_manager_ticker_ref_counting(websocket_manager):
    """Test ticker subscriptions are reference-counted, not booleans."""
    websocket_manager._public_ws = AsyncMock()

    await websocket_manager.subscribe_ticker("BTCUSDC")
    await websocket_manager.subscribe_ticker("BTCUSDC")
    assert websocket_manager._ticker_subscribers["BTCUSDC"] == 2

    await websocket_manager.unsubscribe_ticker("BTCUSDC")
    assert websocket_manager._ticker_subscribers["BTCUSDC"] == 1

    await websocket_manager.unsubscribe_ticker("BTCUSDC")
    assert "BTCUSDC" not in websocket_manager._ticker_subscribers


# BrokerSpot Integration Tests


def test_broker_has_websocket_manager(mock_broker_with_ws):
    """Verify broker has WebSocketManager."""
    assert mock_broker_with_ws._ws_manager is not None
    assert isinstance(mock_broker_with_ws._ws_manager, WebSocketManager)


async def test_broker_subscribe_signals_ticker_subscription(mock_broker_with_ws):
    """Test broker subscribe() signals WebSocketManager to add a ticker subscription."""
    broker = mock_broker_with_ws
    broker._ws_manager._public_ws = AsyncMock()
    test_queue = queue.Queue()

    subscription_info = SubscriptionInfo(
        data_type=SubscriptionType.PRICE,
        symbol="BTCUSDC",
        target=SubscriptionTarget.BACKEND,
        queue=test_queue,
    )

    broker.subscribe(system_id="test_1000", subscription_info=subscription_info)
    await asyncio.sleep(0)  # let the scheduled subscribe_ticker() task run

    assert "test_1000" in broker.subscriptions
    assert broker._ws_manager._ticker_subscribers.get("BTCUSDC") == 1


async def test_broker_unsubscribe_signals_ticker_unsubscription(mock_broker_with_ws):
    """Test broker unsubscribe() signals WebSocketManager to remove the subscription."""
    broker = mock_broker_with_ws
    broker._ws_manager._public_ws = AsyncMock()
    test_queue = queue.Queue()

    subscription_info = SubscriptionInfo(
        data_type=SubscriptionType.PRICE,
        symbol="BTCUSDC",
        target=SubscriptionTarget.BACKEND,
        queue=test_queue,
    )
    broker.subscribe(system_id="test_1000", subscription_info=subscription_info)
    await asyncio.sleep(0)

    broker.unsubscribe(system_id="test_1000")
    await asyncio.sleep(0)

    assert "test_1000" not in broker.subscriptions
    assert "BTCUSDC" not in broker._ws_manager._ticker_subscribers


async def test_broker_user_subscription_does_not_touch_ticker_registry(
    mock_broker_with_ws,
):
    """USER subscriptions are account-wide (executions/balances) - no per-symbol signal."""
    broker = mock_broker_with_ws
    broker._ws_manager._private_ws = AsyncMock()
    test_queue = queue.Queue()

    subscription_info = SubscriptionInfo(
        data_type=SubscriptionType.USER,
        symbol="BTCUSDC",
        target=SubscriptionTarget.BACKEND,
        queue=test_queue,
    )

    broker.subscribe(system_id="test_1000", subscription_info=subscription_info)
    await asyncio.sleep(0)

    assert broker._ws_manager._ticker_subscribers == {}


# Configuration Tests


def test_ultra_robust_config_loaded(mock_broker_with_ws):
    """Verify ultra-robust configuration is used."""
    broker = mock_broker_with_ws
    assert broker._ws_config == ULTRA_ROBUST_CONFIG
    assert broker._ws_config.connection_timeout == 60
    assert broker._ws_config.connection_silence_timeout == 60
    assert broker._ws_config.token_refresh_interval == 780


# Separation of Concerns Tests


def test_strategy_executor_no_websocket_methods():
    """Verify StrategyExecutor has no WebSocket error handling."""
    assert not hasattr(StrategyExecutor, "_handle_websocket_error")
    assert not hasattr(StrategyExecutor, "_restart_websocket_client")
