"""Unit tests for src.common.client.KrakenClient."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from src.common.client import KrakenClient


@pytest.fixture
def client() -> KrakenClient:
    client = KrakenClient(api_key="key", api_secret="secret")
    client._market = MagicMock()
    return client


class _FakeWsConnection:
    """Minimal stand-in for websockets.connect()'s async context manager."""

    def __init__(self, messages):
        self.sent = []
        self._messages = list(messages)

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        if self._messages:
            return self._messages.pop(0)
        # No more scripted messages - simulate silence so a real timeout in the
        # test can cut this off, instead of raising and masking a timeout bug.
        await asyncio.sleep(3600)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestToKrakenSymbol:
    @pytest.mark.parametrize(
        "internal, expected",
        [
            ("BTCUSDC", "XBT/USDC"),
            ("ETHUSDC", "ETH/USDC"),
            ("ETHBTC", "ETH/XBT"),
        ],
    )
    def test_known_quotes(self, internal, expected):
        assert KrakenClient._to_kraken_symbol(internal) == expected

    def test_unknown_quote_raises(self):
        with pytest.raises(ValueError):
            KrakenClient._to_kraken_symbol("FOOBAR")


class TestFromKrakenSymbol:
    @pytest.mark.parametrize(
        "kraken, expected",
        [
            ("XBT/USDC", "BTCUSDC"),
            ("ETH/USDC", "ETHUSDC"),
            ("ETH/XBT", "ETHBTC"),
        ],
    )
    def test_known_pairs(self, kraken, expected):
        assert KrakenClient._from_kraken_symbol(kraken) == expected


class TestGetAssetPairs:
    async def test_keys_result_by_internal_symbol_name(self, client):
        client._market.get_asset_pairs.return_value = {
            "XXBTZUSDC": {"wsname": "XBT/USDC", "status": "online"},
        }

        pairs = await client.get_asset_pairs()

        assert set(pairs) == {"BTCUSDC"}
        assert pairs["BTCUSDC"] == {"wsname": "XBT/USDC", "status": "online"}

    async def test_skips_pair_without_wsname(self, client, caplog):
        client._market.get_asset_pairs.return_value = {
            "XETHZUSDC.d": {"status": "online"},  # dark-pool pair, no wsname
            "XXBTZUSDC": {"wsname": "XBT/USDC", "status": "online"},
        }

        with caplog.at_level("WARNING"):
            pairs = await client.get_asset_pairs()

        assert set(pairs) == {"BTCUSDC"}
        assert "XETHZUSDC.d" in caplog.text


class TestGetWsToken:
    async def test_calls_get_websockets_token_endpoint(self, client):
        client._trade.request = MagicMock(return_value={"token": "abc", "expires": 900})

        resp = await client.get_ws_token()

        assert resp == {"token": "abc", "expires": 900}
        client._trade.request.assert_called_once_with(
            method="POST", uri="/0/private/GetWebSocketsToken"
        )


class TestNormalizeWsInstrumentSnapshot:
    def test_maps_ws_fields_to_rest_asset_pairs_shape(self, client):
        msg = {
            "data": {
                "pairs": [
                    {
                        "symbol": "XBT/USDC",
                        "status": "online",
                        "qty_precision": 8,
                        "price_precision": 1,
                        "qty_min": 0.0001,
                        "cost_min": 0.5,
                        "tick_size": 0.1,
                    }
                ]
            }
        }

        pairs = client._normalize_ws_instrument_snapshot(msg)

        assert pairs == {
            "BTCUSDC": {
                "status": "online",
                "lot_decimals": 8,
                "pair_decimals": 1,
                "ordermin": 0.0001,
                "costmin": 0.5,
                "tick_size": 0.1,
            }
        }

    def test_skips_malformed_pair_without_crashing(self, client, caplog):
        msg = {
            "data": {
                "pairs": [
                    {"symbol": "ETH/USDC", "status": "online"},  # missing most fields
                    {
                        "symbol": "XBT/USDC",
                        "status": "online",
                        "qty_precision": 8,
                        "price_precision": 1,
                        "qty_min": 0.0001,
                        "cost_min": 0.5,
                        "tick_size": 0.1,
                    },
                ]
            }
        }

        with caplog.at_level("WARNING"):
            pairs = client._normalize_ws_instrument_snapshot(msg)

        assert set(pairs) == {"BTCUSDC"}


class TestGetAssetPairsWs:
    async def test_returns_normalized_pairs_from_snapshot(self, client, monkeypatch):
        heartbeat = json.dumps({"channel": "heartbeat"})
        ack = json.dumps(
            {
                "method": "subscribe",
                "result": {"channel": "instrument"},
                "success": True,
            }
        )
        snapshot = json.dumps(
            {
                "channel": "instrument",
                "type": "snapshot",
                "data": {
                    "pairs": [
                        {
                            "symbol": "XBT/USDC",
                            "status": "online",
                            "qty_precision": 8,
                            "price_precision": 1,
                            "qty_min": 0.0001,
                            "cost_min": 0.5,
                            "tick_size": 0.1,
                        }
                    ]
                },
            }
        )
        fake_ws = _FakeWsConnection([heartbeat, ack, snapshot])
        monkeypatch.setattr(
            "src.common.client.websockets.connect", lambda *a, **k: fake_ws
        )

        pairs = await client.get_asset_pairs_ws()

        assert set(pairs) == {"BTCUSDC"}
        assert json.loads(fake_ws.sent[0]) == {
            "method": "subscribe",
            "params": {"channel": "instrument"},
        }

    async def test_times_out_if_no_snapshot_received(self, client, monkeypatch):
        fake_ws = _FakeWsConnection([json.dumps({"channel": "heartbeat"})])
        monkeypatch.setattr(
            "src.common.client.websockets.connect", lambda *a, **k: fake_ws
        )

        with pytest.raises(TimeoutError):
            await client.get_asset_pairs_ws(timeout=0.05)
