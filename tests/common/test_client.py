"""Unit tests for src.common.client.KrakenClient."""

from unittest.mock import MagicMock

import pytest
from src.common.client import KrakenClient


@pytest.fixture
def client() -> KrakenClient:
    client = KrakenClient(api_key="key", api_secret="secret")
    client._market = MagicMock()
    return client


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
