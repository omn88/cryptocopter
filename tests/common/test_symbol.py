"""Unit tests for src.common.symbol.Symbol."""

import pytest
from decimal import Decimal
from src.common.symbol import Symbol


def make_symbol(precision=8, price_precision=2, min_notional=10.0):
    return Symbol(
        name="BTCUSDT",
        min_notional=min_notional,
        lot_size=0.00000001,
        min_qty=0.00000001,
        max_qty=9000.0,
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
        assert s.adjust_quantity(1.23456789) == Decimal("1.235")

    def test_zero_precision(self):
        s = make_symbol(precision=0)
        assert s.adjust_quantity(1.9) == 2.0

    def test_exact_value_unchanged(self):
        s = make_symbol(precision=5)
        assert s.adjust_quantity(0.12345) == Decimal("0.12345")


class TestAdjustPrice:
    def test_rounds_to_price_precision(self):
        s = make_symbol(price_precision=2)
        assert s.adjust_price(100.005) == 100.0  # standard half-even rounding

    def test_zero_price_precision(self):
        s = make_symbol(price_precision=0)
        assert s.adjust_price(99.9) == 100.0

    def test_exact_value_unchanged(self):
        s = make_symbol(price_precision=4)
        assert s.adjust_price(1.2345) == Decimal("1.2345")


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
