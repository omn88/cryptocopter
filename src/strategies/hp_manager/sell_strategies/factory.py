"""Factory for creating sell strategy instances."""

import logging
from typing import Any, Dict, List

from src.domain.positions import HPSellConfig, SellPosition
from src.common.symbol import Symbol
from .base import BaseSellStrategy
from .direct import DirectSellStrategy
from .multihop import MultihopSellStrategy

logger = logging.getLogger(__name__)

# Coins that cannot be used as intermediate hops because they are stable-coin
# end destinations rather than tradeable intermediate assets.
DELISTED_COINS = {
    "USDT",
    "FDUSD",
    "TUSD",
    "USDP",
    "DAI",
    "AEUR",
    "UST",
    "USTC",
    "PAXG",
}


class SellStrategyFactory:
    """Factory for creating appropriate sell strategy based on sell path."""

    @staticmethod
    def create_from_config(
        config: HPSellConfig,
        symbols: Dict[str, Symbol],
        original_position: SellPosition,
        price_resolver: Any,
    ) -> BaseSellStrategy:
        """Create sell strategy by determining path and instantiating appropriate strategy.

        This is the main entry point for creating sell strategies. It determines the
        optimal sell path based on available symbols and target currency, then creates
        the appropriate strategy object.

        Args:
            config: Sell configuration with coin, end_currency, etc.
            symbols: Available trading symbols
            original_position: Original sell position
            price_resolver: Price resolver for current market prices

        Returns:
            Appropriate strategy instance (Direct or Multihop)

        Raises:
            ValueError: If no valid sell path can be found
        """
        sell_path = []
        coin = config.coin
        end_currency = config.end_currency

        logger.info(
            "[FACTORY] === Determining sell path for %s -> %s (qty: %.8f, hp_id: %s) ===",
            coin,
            end_currency,
            config.quantity,
            config.hp_id,
        )

        if end_currency == "USDC":
            # Priority 1: coinUSDC
            if f"{coin}USDC" in symbols:
                logger.info("[FACTORY] > Priority 1: Found direct path %sUSDC", coin)
                sell_path.append(symbols[f"{coin}USDC"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 2: coinBTC + BTCUSDC
            if (
                coin not in DELISTED_COINS
                and f"{coin}BTC" in symbols
                and "BTCUSDC" in symbols
            ):
                logger.info("[FACTORY] > Priority 2: Multihop %sBTC -> BTCUSDC", coin)
                sell_path.append(symbols[f"{coin}BTC"])
                sell_path.append(symbols["BTCUSDC"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 3: coinETH + ETHUSDC
            if (
                coin not in DELISTED_COINS
                and f"{coin}ETH" in symbols
                and "ETHUSDC" in symbols
            ):
                logger.info("[FACTORY] > Priority 3: Multihop %sETH -> ETHUSDC", coin)
                sell_path.append(symbols[f"{coin}ETH"])
                sell_path.append(symbols["ETHUSDC"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # No valid sell path found — no Kraken pair for this coin
            raise ValueError(
                f"Could not determine sell strategy for {coin} to {end_currency}: "
                f"no direct, BTC-hop, or ETH-hop pair available"
            )

        # No valid sell path found
        raise ValueError(
            f"Could not determine sell strategy for {coin} to {end_currency}"
        )

    @staticmethod
    def create(
        original_position: SellPosition,
        sell_path: List[Symbol],
        price_resolver: Any,
    ) -> BaseSellStrategy:
        """Create appropriate sell strategy based on sell path.

        Args:
            original_position: Original sell position with config
            sell_path: List of symbols representing the sell path
            price_resolver: Price resolver for current market prices

        Returns:
            Appropriate strategy instance (Direct or Multihop)

        Raises:
            ValueError: If sell_path is invalid or unsupported
        """
        if not sell_path:
            raise ValueError("Sell path cannot be empty")

        # Direct sell: Single symbol, normal limit order
        if len(sell_path) == 1:
            logger.info(
                "[FACTORY] Creating DirectSellStrategy for %s",
                sell_path[0].name,
            )
            return DirectSellStrategy(
                original_position=original_position,
                sell_path=sell_path,
                price_resolver=price_resolver,
            )

        # Multihop sell: Two symbols
        if len(sell_path) == 2:
            logger.info(
                "[FACTORY] Creating MultihopSellStrategy for %s -> %s",
                sell_path[0].name,
                sell_path[1].name,
            )
            return MultihopSellStrategy(
                original_position=original_position,
                sell_path=sell_path,
                price_resolver=price_resolver,
            )

        raise ValueError(f"Unsupported sell path length: {len(sell_path)}")
