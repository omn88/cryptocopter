"""Factory for creating sell strategy instances."""

import logging
from typing import Dict, List

from src.common.identifiers import HPSellConfig, SellPosition
from src.common.symbol import Symbol
from .base import BaseSellStrategy
from .direct import DirectSellStrategy
from .convert import ConvertSellStrategy
from .multihop import MultihopSellStrategy


logger = logging.getLogger("sell_strategy_factory")


class SellStrategyFactory:
    """Factory for creating appropriate sell strategy based on sell path."""

    @staticmethod
    def create_from_config(
        config: HPSellConfig,
        symbols: Dict[str, Symbol],
        original_position: SellPosition,
        price_resolver,
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
            Appropriate strategy instance (Direct, Convert, or Multihop)

        Raises:
            ValueError: If no valid sell path can be found
        """
        delisted_coins = {
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

        sell_path = []
        coin = config.coin
        end_currency = config.end_currency

        if end_currency == "PLN":
            # Priority 1: Direct pair to PLN
            if f"{coin}PLN" in symbols:
                sell_path.append(symbols[f"{coin}PLN"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 2: coinUSDC + USDCPLN
            if f"{coin}USDC" in symbols and "USDCPLN" in symbols:
                sell_path.append(symbols[f"{coin}USDC"])
                sell_path.append(symbols["USDCPLN"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 3: coinBTC + BTCPLN
            if (
                coin not in delisted_coins
                and f"{coin}BTC" in symbols
                and "BTCPLN" in symbols
            ):
                sell_path.append(symbols[f"{coin}BTC"])
                sell_path.append(symbols["BTCPLN"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 4: coinBNB + BNBPLN
            if (
                coin not in delisted_coins
                and f"{coin}BNB" in symbols
                and "BNBPLN" in symbols
            ):
                sell_path.append(symbols[f"{coin}BNB"])
                sell_path.append(symbols["BNBPLN"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 5: Converting
            # Use USDT symbol for convert operations - ending with USDT indicates conversion
            symbol = symbols[f"{coin}USDT"]
            symbol.is_convert_only = True
            sell_path.append(symbol)
            return SellStrategyFactory.create(
                original_position, sell_path, price_resolver
            )

        if end_currency == "USDC":
            # Priority 1: coinUSDC
            if f"{coin}USDC" in symbols:
                sell_path.append(symbols[f"{coin}USDC"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 2: coinBTC + BTCUSDC
            if (
                coin not in delisted_coins
                and f"{coin}BTC" in symbols
                and "BTCUSDC" in symbols
            ):
                sell_path.append(symbols[f"{coin}BTC"])
                sell_path.append(symbols["BTCUSDC"])
                return SellStrategyFactory.create(
                    original_position, sell_path, price_resolver
                )

            # Priority 3: Exotic coinXYZ + XYZUSDC
            if coin not in delisted_coins:
                for pair in symbols:
                    if pair.startswith(coin):
                        quote = pair.replace(coin, "")
                        if quote in delisted_coins:
                            continue
                        if f"{quote}USDC" in symbols:
                            sell_path.append(symbols[pair])
                            sell_path.append(symbols[f"{quote}USDC"])
                            return SellStrategyFactory.create(
                                original_position, sell_path, price_resolver
                            )

            # Priority 4: Converting
            # Use USDT symbol for convert operations - ending with USDT indicates conversion
            symbol = symbols[f"{coin}USDT"]
            symbol.is_convert_only = True
            sell_path.append(symbol)
            return SellStrategyFactory.create(
                original_position, sell_path, price_resolver
            )

        # No valid sell path found
        raise ValueError(
            f"Could not determine sell strategy for {coin} to {end_currency}"
        )

    @staticmethod
    def create(
        original_position: SellPosition,
        sell_path: List[Symbol],
        price_resolver,
    ) -> BaseSellStrategy:
        """Create appropriate sell strategy based on sell path.

        Args:
            original_position: Original sell position with config
            sell_path: List of symbols representing the sell path
            price_resolver: Price resolver for current market prices

        Returns:
            Appropriate strategy instance (Direct, Convert, or Multihop)

        Raises:
            ValueError: If sell_path is invalid or unsupported
        """
        if not sell_path:
            raise ValueError("Sell path cannot be empty")

        # Convert operation: Single symbol with is_convert_only flag
        if len(sell_path) == 1 and sell_path[0].is_convert_only:
            logger.info(
                "Creating ConvertSellStrategy for %s (convert operation)",
                sell_path[0].name,
            )
            return ConvertSellStrategy(
                original_position=original_position,
                sell_path=sell_path,
                price_resolver=price_resolver,
            )

        # Direct sell: Single symbol, normal limit order
        if len(sell_path) == 1:
            logger.info(
                "Creating DirectSellStrategy for %s",
                sell_path[0].name,
            )
            return DirectSellStrategy(
                original_position=original_position,
                sell_path=sell_path,
                price_resolver=price_resolver,
            )

        # Multihop sell: Two symbols (leg1 → leg2)
        if len(sell_path) == 2:
            logger.info(
                "Creating MultihopSellStrategy for %s → %s",
                sell_path[0].name,
                sell_path[1].name,
            )
            return MultihopSellStrategy(
                original_position=original_position,
                sell_path=sell_path,
                price_resolver=price_resolver,
            )

        # Unsupported: 3+ hops or other edge cases
        raise ValueError(
            f"Unsupported sell path length: {len(sell_path)}. "
            f"Only 1 (direct/convert) or 2 (multihop) symbols supported."
        )
