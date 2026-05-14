import asyncio
from unittest.mock import MagicMock

import pytest

from src.common.client import BinanceClient
from src.websocket.manager import WebSocketManager


@pytest.fixture
def manager() -> WebSocketManager:
    """Bare WebSocketManager with mocked client and a fresh stop event."""
    return WebSocketManager(
        client=MagicMock(spec=BinanceClient),
        subscriptions={},
        stop_event=asyncio.Event(),
    )
