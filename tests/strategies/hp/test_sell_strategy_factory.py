"""Unit tests for src.strategies.hp_manager.sell_strategies.factory.SellStrategyFactory."""

import pytest
from unittest.mock import MagicMock

from src.common.symbol import Symbol
from src.common.identifiers import HPSellConfig, SellPosition
from src.strategies.hp_manager.sell_strategies.factory import SellStrategyFactory
from src.strategies.hp_manager.sell_strategies.direct import DirectSellStrategy
from src.strategies.hp_manager.sell_strategies.convert import ConvertSellStrategy
from src.strategies.hp_manager.sell_strategies.multihop import MultihopSellStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_symbol(name: str, is_convert_only: bool = False) -> Symbol:
    return Symbol(
        name=name,
        min_notional=10.0,
        lot_size=0.001,
        min_qty=0.001,
        max_qty=9000.0,
        price_filter=0.01,
        precision=3,
        price_precision=2,
        is_convert_only=is_convert_only,
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

    def test_single_normal_symbol_returns_direct(
        self, original_position, price_resolver
    ):
        path = [make_symbol("ETHUSDC")]
        result = SellStrategyFactory.create(original_position, path, price_resolver)
        assert isinstance(result, DirectSellStrategy)

    def test_single_convert_only_symbol_returns_convert(
        self, original_position, price_resolver
    ):
        path = [make_symbol("ETHUSDT", is_convert_only=True)]
        result = SellStrategyFactory.create(original_position, path, price_resolver)
        assert isinstance(result, ConvertSellStrategy)

    def test_two_symbols_returns_multihop(self, original_position, price_resolver):
        path = [make_symbol("ETHBTC"), make_symbol("BTCUSDC")]
        result = SellStrategyFactory.create(original_position, path, price_resolver)
        assert isinstance(result, MultihopSellStrategy)


# ---------------------------------------------------------------------------
# SellStrategyFactory.create_from_config — PLN end_currency
# ---------------------------------------------------------------------------


class TestCreateFromConfigPLN:
    def _pos(self, coin: str) -> SellPosition:
        pos = MagicMock(spec=SellPosition)
        pos.config = make_config(coin, "PLN")
        return pos

    def test_priority1_direct_pln(self, price_resolver):
        symbols = {
            "ETHPLN": make_symbol("ETHPLN"),
            "ETHUSDT": make_symbol("ETHUSDT"),
        }
        config = make_config("ETH", "PLN")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, DirectSellStrategy)

    def test_priority2_usdc_pln_multihop(self, price_resolver):
        symbols = {
            "ETHUSDC": make_symbol("ETHUSDC"),
            "USDCPLN": make_symbol("USDCPLN"),
            "ETHUSDT": make_symbol("ETHUSDT"),
        }
        config = make_config("ETH", "PLN")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)

    def test_priority3_btc_pln_multihop(self, price_resolver):
        symbols = {
            "ETHBTC": make_symbol("ETHBTC"),
            "BTCPLN": make_symbol("BTCPLN"),
            "ETHUSDT": make_symbol("ETHUSDT"),
        }
        config = make_config("ETH", "PLN")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)

    def test_priority4_bnb_pln_multihop(self, price_resolver):
        symbols = {
            "ETHBNB": make_symbol("ETHBNB"),
            "BNBPLN": make_symbol("BNBPLN"),
            "ETHUSDT": make_symbol("ETHUSDT"),
        }
        config = make_config("ETH", "PLN")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)

    def test_priority5_convert_fallback(self, price_resolver):
        symbols = {
            "ETHUSDT": make_symbol("ETHUSDT"),
        }
        config = make_config("ETH", "PLN")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, ConvertSellStrategy)

    def test_delisted_coin_skips_btc_path(self, price_resolver):
        """A delisted coin (USDT) must not use the BTC priority path."""
        symbols = {
            "USDTBTC": make_symbol("USDTBTC"),
            "BTCPLN": make_symbol("BTCPLN"),
            "USDTUSDT": make_symbol("USDTUSDT"),
        }
        config = make_config("USDT", "PLN")
        # USDT is delisted so BTC path is skipped; falls to convert via coinUSDT
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("USDT"), price_resolver
        )
        assert isinstance(result, ConvertSellStrategy)


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
            "ETHBTC": make_symbol("ETHBTC"),
            "BTCUSDC": make_symbol("BTCUSDC"),
            "ETHUSDT": make_symbol("ETHUSDT"),
        }
        config = make_config("ETH", "USDC")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)

    def test_priority3_exotic_multihop(self, price_resolver):
        # AXLBTC doesn't exist; AXLETH + ETHUSDC forms the exotic path
        symbols = {
            "AXLETH": make_symbol("AXLETH"),
            "ETHUSDC": make_symbol("ETHUSDC"),
            "AXLUSDT": make_symbol("AXLUSDT"),
        }
        config = make_config("AXL", "USDC")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("AXL"), price_resolver
        )
        assert isinstance(result, MultihopSellStrategy)

    def test_priority4_convert_fallback(self, price_resolver):
        symbols = {
            "ETHUSDT": make_symbol("ETHUSDT"),
        }
        config = make_config("ETH", "USDC")
        result = SellStrategyFactory.create_from_config(
            config, symbols, self._pos("ETH"), price_resolver
        )
        assert isinstance(result, ConvertSellStrategy)


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
