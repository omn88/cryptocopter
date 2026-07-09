"""Unit tests for WebSocketManager (src/websocket/manager.py)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

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
        assert mgr._ticker_subscribers == {}
        assert mgr._kline_subscribers == {}
        assert mgr._ws_token is None
        assert mgr._public_ws is None
        assert mgr._private_ws is None
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
# start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    async def test_start_requires_handlers(self, manager):
        with pytest.raises(RuntimeError):
            await manager.start()

    async def test_start_returns_three_tasks(self, manager, monkeypatch):
        manager.set_message_handlers(MagicMock(), MagicMock())
        manager.client.get_ws_token = AsyncMock(return_value={"token": "t"})
        # Avoid real network I/O: connect fails immediately, task goes to its
        # (cancellable) reconnect-delay sleep instead of hitting the network.
        monkeypatch.setattr(
            "src.websocket.manager.websockets.connect",
            MagicMock(side_effect=ConnectionRefusedError("no network in tests")),
        )

        tasks = await manager.start()

        assert len(tasks) == 3
        assert all(isinstance(t, asyncio.Task) for t in tasks)

        await manager.stop()
        assert all(t.done() for t in tasks)

    async def test_stop_is_safe_before_start(self, manager):
        await manager.stop()  # should not raise


# ---------------------------------------------------------------------------
# Ref-counted per-symbol subscriptions
# ---------------------------------------------------------------------------


class TestAdjustSubscription:
    async def test_first_ticker_subscribe_sends_frame(self, manager):
        manager._public_ws = AsyncMock()

        await manager.subscribe_ticker("BTCUSDC")

        assert manager._ticker_subscribers == {"BTCUSDC": 1}
        sent = json.loads(manager._public_ws.send.call_args[0][0])
        assert sent == {
            "method": "subscribe",
            "params": {"channel": "ticker", "symbol": ["BTCUSDC"]},
        }

    async def test_second_ticker_subscribe_does_not_resend(self, manager):
        manager._public_ws = AsyncMock()
        await manager.subscribe_ticker("BTCUSDC")
        manager._public_ws.send.reset_mock()

        await manager.subscribe_ticker("BTCUSDC")

        assert manager._ticker_subscribers == {"BTCUSDC": 2}
        manager._public_ws.send.assert_not_called()

    async def test_unsubscribe_above_zero_does_not_send(self, manager):
        manager._public_ws = AsyncMock()
        await manager.subscribe_ticker("BTCUSDC")
        await manager.subscribe_ticker("BTCUSDC")
        manager._public_ws.send.reset_mock()

        await manager.unsubscribe_ticker("BTCUSDC")

        assert manager._ticker_subscribers == {"BTCUSDC": 1}
        manager._public_ws.send.assert_not_called()

    async def test_unsubscribe_to_zero_sends_frame_and_removes_symbol(self, manager):
        manager._public_ws = AsyncMock()
        await manager.subscribe_ticker("BTCUSDC")
        manager._public_ws.send.reset_mock()

        await manager.unsubscribe_ticker("BTCUSDC")

        assert manager._ticker_subscribers == {}
        sent = json.loads(manager._public_ws.send.call_args[0][0])
        assert sent == {
            "method": "unsubscribe",
            "params": {"channel": "ticker", "symbol": ["BTCUSDC"]},
        }

    async def test_unsubscribe_below_zero_is_a_noop(self, manager):
        manager._public_ws = AsyncMock()

        await manager.unsubscribe_ticker("BTCUSDC")

        assert manager._ticker_subscribers == {}
        manager._public_ws.send.assert_not_called()

    async def test_subscribe_without_connected_socket_updates_registry_only(
        self, manager
    ):
        manager._public_ws = None  # not connected yet

        await manager.subscribe_ticker("BTCUSDC")

        assert manager._ticker_subscribers == {"BTCUSDC": 1}

    async def test_kline_subscribe_sends_interval(self, manager):
        manager._public_ws = AsyncMock()

        await manager.subscribe_kline("BTCUSDC")

        assert manager._kline_subscribers == {"BTCUSDC": 1}
        sent = json.loads(manager._public_ws.send.call_args[0][0])
        assert sent == {
            "method": "subscribe",
            "params": {"channel": "ohlc", "symbol": ["BTCUSDC"], "interval": 15},
        }


class TestResubscribePublicChannels:
    async def test_replays_all_active_subscriptions(self, manager):
        manager._public_ws = AsyncMock()
        manager._ticker_subscribers = {"BTCUSDC": 2}
        manager._kline_subscribers = {"ETHUSDC": 1}

        await manager._resubscribe_public_channels()

        sent_frames = [
            json.loads(call.args[0]) for call in manager._public_ws.send.call_args_list
        ]
        assert {
            "method": "subscribe",
            "params": {"channel": "ticker", "symbol": ["BTCUSDC"]},
        } in sent_frames
        assert {
            "method": "subscribe",
            "params": {"channel": "ohlc", "symbol": ["ETHUSDC"], "interval": 15},
        } in sent_frames


# ---------------------------------------------------------------------------
# Message dispatch
# ---------------------------------------------------------------------------


class TestDispatchPublicMessage:
    def test_heartbeat_is_ignored(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock(), MagicMock())
        manager._dispatch_public_message({"channel": "heartbeat"})
        manager._ticker_message_handler.assert_not_called()

    def test_subscribe_ack_is_not_forwarded_to_handler(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock(), MagicMock())
        manager._dispatch_public_message(
            {"method": "subscribe", "success": True, "result": {}}
        )
        manager._ticker_message_handler.assert_not_called()

    def test_ticker_message_forwarded_to_ticker_handler(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock(), MagicMock())
        msg = {"channel": "ticker", "data": [{"symbol": "BTC/USDC"}]}

        manager._dispatch_public_message(msg)

        manager._ticker_message_handler.assert_called_once_with(msg)
        manager._kline_message_handler.assert_not_called()

    def test_ohlc_message_forwarded_to_kline_handler(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock(), MagicMock())
        msg = {"channel": "ohlc", "data": [{"symbol": "BTC/USDC"}]}

        manager._dispatch_public_message(msg)

        manager._kline_message_handler.assert_called_once_with(msg)
        manager._ticker_message_handler.assert_not_called()

    def test_non_dict_message_is_ignored(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock(), MagicMock())
        manager._dispatch_public_message([{"a": 1}])  # doesn't raise
        manager._ticker_message_handler.assert_not_called()


class TestDispatchPrivateMessage:
    def test_executions_message_forwarded_to_user_handler(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock())
        msg = {"channel": "executions", "data": []}

        manager._dispatch_private_message(msg)

        manager._user_message_handler.assert_called_once_with(msg)

    def test_balances_message_forwarded_to_user_handler(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock())
        msg = {"channel": "balances", "data": []}

        manager._dispatch_private_message(msg)

        manager._user_message_handler.assert_called_once_with(msg)

    def test_heartbeat_is_ignored(self, manager):
        manager.set_message_handlers(MagicMock(), MagicMock())
        manager._dispatch_private_message({"channel": "heartbeat"})
        manager._user_message_handler.assert_not_called()


# ---------------------------------------------------------------------------
# Token auth
# ---------------------------------------------------------------------------


class TestTokenAuth:
    async def test_refresh_ws_token_sets_token(self, manager):
        manager.client.get_ws_token = AsyncMock(return_value={"token": "abc123"})

        await manager._refresh_ws_token()

        assert manager._ws_token == "abc123"

    async def test_refresh_ws_token_failure_leaves_token_unset(self, manager):
        manager.client.get_ws_token = AsyncMock(side_effect=ConnectionError("boom"))

        await manager._refresh_ws_token()

        assert manager._ws_token is None

    async def test_subscribe_private_channels_includes_token(self, manager):
        manager._ws_token = "abc123"
        manager._private_ws = AsyncMock()

        await manager._subscribe_private_channels()

        sent_frames = [
            json.loads(call.args[0]) for call in manager._private_ws.send.call_args_list
        ]
        channels = {frame["params"]["channel"] for frame in sent_frames}
        assert channels == {"executions", "balances"}
        assert all(frame["params"]["token"] == "abc123" for frame in sent_frames)

    async def test_subscribe_private_channels_fetches_token_if_missing(self, manager):
        manager._ws_token = None
        manager._private_ws = AsyncMock()
        manager.client.get_ws_token = AsyncMock(return_value={"token": "fresh"})

        await manager._subscribe_private_channels()

        assert manager._ws_token == "fresh"
        manager.client.get_ws_token.assert_called_once()

    async def test_subscribe_private_channels_noop_without_token(self, manager):
        manager._ws_token = None
        manager._private_ws = AsyncMock()
        manager.client.get_ws_token = AsyncMock(side_effect=ConnectionError("boom"))

        await manager._subscribe_private_channels()  # should not raise

        manager._private_ws.send.assert_not_called()


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
