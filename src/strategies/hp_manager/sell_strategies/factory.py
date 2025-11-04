"""Sell strategy factory for creating appropriate strategy based on sell path."""

import logging
from typing import List

from src.common.identifiers import SellPosition
from src.common.symbol import Symbol
from .base import BaseSellStrategy
from .direct import DirectSellStrategy
from .convert import ConvertSellStrategy
from .multihop import MultihopSellStrategy


logger = logging.getLogger("sell_strategy_factory")


class SellStrategyFactory:
    """Factory for creating sell strategies based on sell path.
    
    Decision logic:
    - 1 symbol + ends with USDT → ConvertSellStrategy
    - 1 symbol + doesn't end with USDT → DirectSellStrategy  
    - 2 symbols → MultihopSellStrategy
    """

    @staticmethod
    def create(
        original_position: SellPosition,
        sell_strategy: List[Symbol],
        price_resolver,
    ) -> BaseSellStrategy:
        """Create appropriate sell strategy based on sell path.
        
        Args:
            original_position: Original sell position with config
            sell_strategy: List of symbols representing the sell path
            price_resolver: Price resolver for getting current market prices
            
        Returns:
            Appropriate sell strategy instance
            
        Raises:
            ValueError: If sell strategy is empty or has more than 2 hops
        """
        if not sell_strategy:
            raise ValueError("Sell strategy cannot be empty")
            
        if len(sell_strategy) > 2:
            raise ValueError(
                f"Only 1 or 2-hop strategies are supported. Got {len(sell_strategy)} hops."
            )

        # Determine strategy type
        if len(sell_strategy) == 1:
            symbol = sell_strategy[0]
            if symbol.name.endswith("USDT"):
                logger.info(
                    "Creating ConvertSellStrategy for %s (convert-only operation)",
                    symbol.name,
                )
                return ConvertSellStrategy(
                    original_position, sell_strategy, price_resolver
                )
            else:
                logger.info(
                    "Creating DirectSellStrategy for %s (direct sell)",
                    symbol.name,
                )
                return DirectSellStrategy(
                    original_position, sell_strategy, price_resolver
                )
        else:  # len == 2
            logger.info(
                "Creating MultihopSellStrategy for %s → %s",
                sell_strategy[0].name,
                sell_strategy[1].name,
            )
            return MultihopSellStrategy(
                original_position, sell_strategy, price_resolver
            )
