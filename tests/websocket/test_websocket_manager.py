"""
Unit tests for WebSocketManager (src/websocket/manager.py).

Coverage targets (A2):
- _parse_message: valid JSON string, dict passthrough, list passthrough,
  invalid JSON string, list with non-dict items, unexpected type, None
- Constructor: attributes set correctly
"""

import asyncio
from unittest.mock import MagicMock

from src.common.client import KrakenClient
from src.websocket.manager import WebSocketManager

# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestWebSocketManagerInit:
    def test_attributes_set(self):
        client = MagicMock(spec=KrakenClient)
        stop_event = asyncio.Event()
        mgr = WebSocketManager(client=client, subscriptions={}, stop_event=stop_event)

        assert mgr.client is client
        assert mgr.stop_event is stop_event
        assert mgr.subscriptions == {}
        assert mgr._restart_count == 0
        assert mgr._user_message_handler is None
        assert mgr._ticker_message_handler is None

    def test_set_message_handlers(self, manager):
        user_fn = MagicMock()
        ticker_fn = MagicMock()
        kline_fn = MagicMock()

        manager.set_message_handlers(user_fn, ticker_fn, kline_fn)

        assert manager._user_message_handler is user_fn
        assert manager._ticker_message_handler is ticker_fn
        assert manager._kline_message_handler is kline_fn


# ---------------------------------------------------------------------------
# _parse_message
# ---------------------------------------------------------------------------


class TestParseMessage:
    def test_valid_json_string_returns_dict(self, manager):
        result = manager._parse_message('{"e": "trade", "s": "BTCUSDT"}')
        assert result == {"e": "trade", "s": "BTCUSDT"}

    def test_valid_json_array_string_returns_list(self, manager):
        result = manager._parse_message('[{"a": 1}, {"b": 2}]')
        assert result == [{"a": 1}, {"b": 2}]

    def test_invalid_json_string_returns_none(self, manager):
        result = manager._parse_message("not-valid-json{")
        assert result is None

    def test_empty_string_returns_none(self, manager):
        result = manager._parse_message("")
        assert result is None

    def test_dict_passthrough(self, manager):
        msg = {"type": "ticker", "price": "100"}
        result = manager._parse_message(msg)
        assert result is msg

    def test_list_of_dicts_passthrough(self, manager):
        msg = [{"a": 1}, {"b": 2}]
        result = manager._parse_message(msg)
        assert result is msg

    def test_list_with_non_dict_items_returns_none(self, manager):
        result = manager._parse_message([1, 2, 3])
        assert result is None

    def test_none_returns_none(self, manager):
        result = manager._parse_message(None)
        assert result is None

    def test_integer_returns_none(self, manager):
        result = manager._parse_message(42)
        assert result is None

    def test_bytes_returns_none(self, manager):
        result = manager._parse_message(b"bytes-data")
        assert result is None
