"""Unit tests for src.common.symbol.Symbol and fetch_symbols."""

from unittest.mock import AsyncMock

import pytest
from src.common.symbol import Symbol, fetch_symbols


def make_symbol(precision=8, price_precision=2, min_notional=10.0):
    return Symbol(
        name="BTCUSDT",
        min_notional=min_notional,
        min_qty=0.00000001,
        price_filter=0.01,
        precision=precision,
        price_precision=price_precision,
    )


# ---------------------------------------------------------------------------
# adjust_quantity / adjust_price
# ---------------------------------------------------------------------------


class TestAdjustQuantity:
    def test_rounds_to_precision(self):
        s = make_symbol(precision=3)
        assert s.adjust_quantity(1.23456789) == 1.235

    def test_zero_precision(self):
        s = make_symbol(precision=0)
        assert s.adjust_quantity(1.9) == 2.0

    def test_exact_value_unchanged(self):
        s = make_symbol(precision=5)
        assert s.adjust_quantity(0.12345) == 0.12345


class TestAdjustPrice:
    def test_rounds_to_price_precision(self):
        s = make_symbol(price_precision=2)
        assert s.adjust_price(100.005) == 100.0  # standard half-even rounding

    def test_zero_price_precision(self):
        s = make_symbol(price_precision=0)
        assert s.adjust_price(99.9) == 100.0

    def test_exact_value_unchanged(self):
        s = make_symbol(price_precision=4)
        assert s.adjust_price(1.2345) == 1.2345


# ---------------------------------------------------------------------------
# format_price
# ---------------------------------------------------------------------------


class TestFormatPrice:
    def test_zero_returns_zero_string(self):
        s = make_symbol(price_precision=8)
        assert s.format_price(0) == "0.0"

    def test_sub_one_strips_trailing_zeros(self):
        s = make_symbol(price_precision=8)
        result = s.format_price(0.001230)
        assert result == "0.00123"

    def test_sub_one_no_trailing_zeros(self):
        s = make_symbol(price_precision=4)
        assert s.format_price(0.1234) == "0.1234"

    def test_whole_number_returns_one_decimal(self):
        s = make_symbol(price_precision=2)
        assert s.format_price(100.0) == "100.0"

    def test_two_decimal_value(self):
        s = make_symbol(price_precision=2)
        assert s.format_price(100.12) == "100.12"

    def test_one_decimal_value(self):
        s = make_symbol(price_precision=2)
        assert s.format_price(99.10) == "99.1"


# ---------------------------------------------------------------------------
# format_quantity
# ---------------------------------------------------------------------------


class TestFormatQuantity:
    def test_zero_returns_zero_string(self):
        s = make_symbol(precision=8)
        assert s.format_quantity(0) == "0.0"

    def test_sub_one_strips_trailing_zeros(self):
        s = make_symbol(precision=8)
        assert s.format_quantity(0.00500000) == "0.005"

    def test_whole_number_returns_one_decimal(self):
        s = make_symbol(precision=3)
        assert s.format_quantity(5.0) == "5.0"

    def test_two_decimal_value(self):
        s = make_symbol(precision=3)
        assert s.format_quantity(5.25) == "5.25"


# ---------------------------------------------------------------------------
# validate_order
# ---------------------------------------------------------------------------


class TestValidateOrder:
    def test_above_min_notional_no_raise(self):
        s = make_symbol(price_precision=2, precision=8, min_notional=10.0)
        s.validate_order(price=100.0, quantity=0.5)  # notional = 50.0

    def test_equal_min_notional_no_raise(self):
        s = make_symbol(price_precision=2, precision=8, min_notional=10.0)
        s.validate_order(price=10.0, quantity=1.0)  # notional == 10.0

    def test_below_min_notional_raises(self):
        s = make_symbol(price_precision=2, precision=8, min_notional=10.0)
        with pytest.raises(ValueError, match="MIN_NOTIONAL"):
            s.validate_order(price=1.0, quantity=0.001)  # notional = 0.001


# ---------------------------------------------------------------------------
# extract_coin_from_symbol
# ---------------------------------------------------------------------------


class TestExtractCoinFromSymbol:
    @pytest.mark.parametrize(
        "symbol, expected",
        [
            ("BTCUSDT", "BTC"),
            ("ETHUSDC", "ETH"),
            ("SOLUSDC", "SOL"),
            ("ETHBTC", "ETH"),
            ("ETHPLN", "ETH"),
            ("ETHBNB", "ETH"),
        ],
    )
    def test_known_quotes(self, symbol, expected):
        s = make_symbol()
        assert s.extract_coin_from_symbol(symbol) == expected

    def test_unknown_quote_raises(self):
        s = make_symbol()
        with pytest.raises(ValueError, match="known quote currency"):
            s.extract_coin_from_symbol("ETHEUR")


# ---------------------------------------------------------------------------
# calculate_precision (static)
# ---------------------------------------------------------------------------


class TestCalculatePrecision:
    @pytest.mark.parametrize(
        "step_size, expected",
        [
            ("0.001", 3),
            ("0.01", 2),
            ("0.1", 1),
            ("1.0", 0),
            ("1", 0),
            ("0.00000001", 8),
        ],
    )
    def test_various_step_sizes(self, step_size, expected):
        assert Symbol.calculate_precision(step_size) == expected


# ---------------------------------------------------------------------------
# fetch_symbols
# ---------------------------------------------------------------------------


def make_kraken_client(asset_pairs):
    """Build a client whose get_asset_pairs() already returns Kraken-normalized
    entries keyed by internal symbol name, matching KrakenClient.get_asset_pairs()'s
    contract (normalization is that class's job, not fetch_symbols')."""
    client = AsyncMock()
    client.get_asset_pairs.return_value = asset_pairs
    return client


class TestFetchSymbols:
    @pytest.mark.asyncio
    async def test_builds_symbol_per_online_pair(self):
        client = make_kraken_client(
            {
                "BTCUSDC": {
                    "pair_decimals": 1,
                    "lot_decimals": 8,
                    "ordermin": "0.0001",
                    "costmin": "0.5",
                    "tick_size": "0.1",
                    "status": "online",
                }
            }
        )
        symbols = await fetch_symbols(client)

        assert set(symbols) == {"BTCUSDC"}
        s = symbols["BTCUSDC"]
        assert s.name == "BTCUSDC"
        assert s.precision == 8
        assert s.price_precision == 1
        assert s.min_qty == 0.0001
        assert s.min_notional == 0.5
        assert s.price_filter == 0.1

    @pytest.mark.asyncio
    async def test_skips_non_online_pairs(self):
        client = make_kraken_client(
            {
                "BTCUSDC": {
                    "pair_decimals": 1,
                    "lot_decimals": 8,
                    "ordermin": "0.0001",
                    "costmin": "0.5",
                    "tick_size": "0.1",
                    "status": "cancel_only",
                }
            }
        )
        symbols = await fetch_symbols(client)

        assert symbols == {}

    @pytest.mark.asyncio
    async def test_skips_malformed_pair_without_crashing(self):
        client = make_kraken_client(
            {
                "ETHUSDC": {
                    # Missing "costmin" - some field Kraken didn't return for this pair.
                    "pair_decimals": 2,
                    "lot_decimals": 8,
                    "ordermin": "0.001",
                    "tick_size": "0.01",
                    "status": "online",
                },
                "BTCUSDC": {
                    "pair_decimals": 1,
                    "lot_decimals": 8,
                    "ordermin": "0.0001",
                    "costmin": "0.5",
                    "tick_size": "0.1",
                    "status": "online",
                },
            }
        )
        symbols = await fetch_symbols(client)

        assert set(symbols) == {"BTCUSDC"}
