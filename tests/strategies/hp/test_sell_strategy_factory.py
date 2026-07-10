"""Unit tests for src.strategies.hp_manager.sell_strategies.factory.SellStrategyFactory."""

import pytest
from unittest.mock import MagicMock

from src.common.symbol import Symbol
from src.domain.positions import HPSellConfig, SellPosition
from src.strategies.hp_manager.sell_strategies.factory import SellStrategyFactory
from src.strategies.hp_manager.sell_strategies.direct import DirectSellStrategy
from src.strategies.hp_manager.sell_strategies.multihop import MultihopSellStrategy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_symbol(name: str) -> Symbol:
    return Symbol(
        name=name,
        min_notional=10.0,
        min_qty=0.001,
        price_filter=0.01,
        precision=3,
        price_precision=2,
    )


def make_config(coin: str, end_currency: str) -> HPSellConfig:
    return HPSellConfig(
        coin=coin,
        end_currency=end_currency,
        hp_id="test-hp",
        quantity=1.0,
        buy_price=100.0,
        sell_price=110.0,
    )


@pytest.fixture
def original_position():
    pos = MagicMock(spec=SellPosition)
    pos.config = make_config("ETH", "USDC")
    return pos


@pytest.fixture
def price_resolver():
    return MagicMock()


# ---------------------------------------------------------------------------
# SellStrategyFactory.create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_empty_path_raises(self, original_position, price_resolver):
        with pytest.raises(ValueError, match="empty"):
            SellStrategyFactory.create(original_position, [], price_resolver)

    def test_single_symbol_returns_direct(self, original_position, price_resolver):
        path = [make_symbol("ETHUSDC")]
        result = SellStrategyFactory.create(original_position, path, price_resolver)
        assert isinstance(result, DirectSellStrategy)

    def test_two_symbols_returns_multihop(self, original_position, price_resolver):
        path = [make_symbol("ETHBTC"), make_symbol("BTCUSDC")]
        result = SellStrategyFactory.create(original_position, path, price_resolver)
        assert isinstance(result, MultihopSellStrategy)

    def test_three_symbols_raises(self, original_position, price_resolver):
        path = [make_symbol("ETHBTC"), make_symbol("BTCUSDC"), make_symbol("USDCUSDT")]
        with pytest.raises(ValueError, match="Unsupported sell path length"):
            SellStrategyFactory.create(original_position, path, price_resolver)


# ---------------------------------------------------------------------------
# SellStrategyFactory.create_from_config — USDC end_currency
# ---------------------------------------------------------------------------


class TestCreateFromConfigUSDC:
    def _pos(self, coin: str) -> SellPosition:
        pos = MagicMock(spec=SellPosition)
        pos.config = make_config(coin, "USDC")
        return pos

    def test_priority1_direct_usdc(self, price_resolver):
        symbols = {
            "ETHUSDC": make_symbol("ETHUSDC"),
        }
        config = make_config("ETH", "USDC")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, DirectSellStrategy)

    def test_priority2_btc_usdc_multihop(self, price_resolver):
        symbols = {
            "AXLBTC": make_symbol("AXLBTC"),
            "BTCUSDC": make_symbol("BTCUSDC"),
        }
        config = make_config("AXL", "USDC")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("AXL"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)

    def test_priority3_eth_usdc_multihop(self, price_resolver):
        symbols = {
            "AXLETH": make_symbol("AXLETH"),
            "ETHUSDC": make_symbol("ETHUSDC"),
        }
        config = make_config("AXL", "USDC")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("AXL"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)

    def test_btc_hop_preferred_over_eth_hop(self, price_resolver):
        symbols = {
            "AXLBTC": make_symbol("AXLBTC"),
            "BTCUSDC": make_symbol("BTCUSDC"),
            "AXLETH": make_symbol("AXLETH"),
            "ETHUSDC": make_symbol("ETHUSDC"),
        }
        config = make_config("AXL", "USDC")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("AXL"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)
        assert result.sell_path[0].name == "AXLBTC"

    def test_delisted_coin_skips_btc_and_eth_paths(self, price_resolver):
        """A delisted coin (USDT) must not use the BTC or ETH hop paths."""
        symbols = {
            "USDTBTC": make_symbol("USDTBTC"),
            "BTCUSDC": make_symbol("BTCUSDC"),
            "USDTETH": make_symbol("USDTETH"),
            "ETHUSDC": make_symbol("ETHUSDC"),
        }
        config = make_config("USDT", "USDC")
        with pytest.raises(ValueError):
            SellStrategyFactory.create_from_config(
                config, symbols, self._pos("USDT"), price_resolver
            )

    def test_no_path_raises(self, price_resolver):
        symbols = {}
        config = make_config("XYZ", "USDC")
        with pytest.raises(ValueError, match="Could not determine sell strategy"):
            SellStrategyFactory.create_from_config(
                config, symbols, self._pos("XYZ"), price_resolver
            )


# ---------------------------------------------------------------------------
# Unknown end_currency
# ---------------------------------------------------------------------------


class TestCreateFromConfigUnknownCurrency:
    def test_unknown_end_currency_raises(self, price_resolver):
        config = make_config("ETH", "EUR")
        pos = MagicMock(spec=SellPosition)
        pos.config = config
        with pytest.raises(ValueError):
            SellStrategyFactory.create_from_config(config, {}, pos, price_resolver)
