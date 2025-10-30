"""Factory for creating appropriate sell strategy based on routing logic.

Uses the existing determine_sell_strategy() helper from src.common.helpers
to determine the trading path, then instantiates the correct strategy.
"""

import logging
import queue
from typing import TYPE_CHECKING, Dict

from src.broker import BrokerSpot
from src.common.client import BinanceClient
from src.common.helpers import determine_sell_strategy
from src.common.identifiers import HPSellConfig
from src.common.symbol import Symbol
from src.database import Database
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.strategies.hp_manager_v2.sell_strategies.base import SellExecutionStrategy
from src.strategies.hp_manager_v2.sell_strategies.convert_sell import (
    ConvertSellStrategy,
)
from src.strategies.hp_manager_v2.sell_strategies.direct_sell import DirectSellStrategy
from src.strategies.hp_manager_v2.sell_strategies.multihop_sell import (
    MultihopSellStrategy,
)

if TYPE_CHECKING:
    from src.strategies.hp_manager_v2.position_buy_v2 import HPPositionBuyV2

logger = logging.getLogger("sell_factory")


class SellStrategyFactory:
    """Factory for creating sell strategies based on routing logic.

    Delegates to existing determine_sell_strategy() helper, then instantiates
    the appropriate strategy class based on the returned symbol path.
    """

    @staticmethod
    def create(
        config: HPSellConfig,
        symbols: Dict[str, Symbol],
        client: BinanceClient,
        db: Database,
        worker_queue: queue.Queue,
        broker: BrokerSpot,
        price_resolver: UsdPriceResolver,
        buy_position: "HPPositionBuyV2",
    ) -> SellExecutionStrategy:
        """Create appropriate sell strategy based on config and available symbols.

        Args:
            config: Sell configuration (coin, quantity, price, etc.)
            symbols: Available trading symbols
            client: Binance API client
            db: Database for persistence
            worker_queue: Queue for portfolio events
            broker: Broker for order execution
            price_resolver: Price resolver for cross-rate calculations
            buy_position: Buy position data (for database updates)

        Returns:
            Appropriate sell strategy instance

        Raises:
            ValueError: If no valid sell path found
        """
        # Use existing routing logic from helpers
        sell_path = determine_sell_strategy(config, symbols)

        if not sell_path:
            raise ValueError(
                f"No sell path found for {config.coin} → {config.end_currency}"
            )

        logger.info(
            f"[{config.hp_id}] Determined sell path: "
            f"{' → '.join(s.name for s in sell_path)}"
        )

        # Determine strategy type based on path length and characteristics
        if len(sell_path) == 1:
            # Single symbol: either direct sell or convert
            symbol = sell_path[0]

            if hasattr(symbol, "is_convert_only") and symbol.is_convert_only:
                # Convert scenario: coin/USDT with conversion flag
                # Need to find USDT → end_currency symbol
                convert_symbol_name = f"USDT{config.end_currency}"
                if convert_symbol_name not in symbols:
                    raise ValueError(
                        f"Convert path requires {convert_symbol_name} but not found"
                    )

                logger.info(f"[{config.hp_id}] Creating ConvertSellStrategy")
                return ConvertSellStrategy(
                    client=client,
                    sell_symbol=symbol,
                    convert_symbol=symbols[convert_symbol_name],
                    coin=config.coin,
                    quantity=config.quantity,
                    target_price=config.sell_price,
                    buy_price=config.buy_price,
                    db=db,
                    hp_id=config.hp_id,
                    worker_queue=worker_queue,
                    broker=broker,
                    buy_position=buy_position,
                )
            else:
                # Direct sell: single symbol, no conversion
                logger.info(f"[{config.hp_id}] Creating DirectSellStrategy")
                return DirectSellStrategy(
                    client=client,
                    symbol=symbol,
                    coin=config.coin,
                    quantity=config.quantity,
                    target_price=config.sell_price,
                    buy_price=config.buy_price,
                    db=db,
                    hp_id=config.hp_id,
                    worker_queue=worker_queue,
                    broker=broker,
                    buy_position=buy_position,
                )

        elif len(sell_path) == 2:
            # Two symbols: multihop routing
            leg1_symbol = sell_path[0]
            leg2_symbol = sell_path[1]

            logger.info(f"[{config.hp_id}] Creating MultihopSellStrategy")
            return MultihopSellStrategy(
                client=client,
                leg1_symbol=leg1_symbol,
                leg2_symbol=leg2_symbol,
                coin=config.coin,
                quantity=config.quantity,
                target_price=config.sell_price,
                buy_price=config.buy_price,
                db=db,
                hp_id=config.hp_id,
                worker_queue=worker_queue,
                broker=broker,
                price_resolver=price_resolver,
                buy_position=buy_position,
            )

        else:
            raise ValueError(
                f"Unexpected sell path length: {len(sell_path)} "
                f"(path: {[s.name for s in sell_path]})"
            )

    @staticmethod
    def create_from_path(
        sell_path: list[Symbol],
        config: HPSellConfig,
        client: BinanceClient,
        db: Database,
        worker_queue: queue.Queue,
        broker: BrokerSpot,
        price_resolver: UsdPriceResolver,
        buy_position: "HPPositionBuyV2",
    ) -> SellExecutionStrategy:
        """Create strategy directly from a pre-determined sell path.

        Useful for testing or when routing has already been calculated.

        Args:
            sell_path: Pre-determined symbol path
            config: Sell configuration
            client: Binance API client
            db: Database
            worker_queue: Queue for portfolio events
            broker: Broker for order execution
            price_resolver: Price resolver
            buy_position: Buy position data

        Returns:
            Appropriate sell strategy instance
        """
        if not sell_path:
            raise ValueError("Empty sell path")

        if len(sell_path) == 1:
            symbol = sell_path[0]

            if hasattr(symbol, "is_convert_only") and symbol.is_convert_only:
                # This shouldn't happen with pre-determined path
                # (convert needs 2 symbols), but handle gracefully
                raise ValueError(
                    "Convert path requires 2 symbols in sell_path "
                    "[sell_symbol, convert_symbol]"
                )

            return DirectSellStrategy(
                client=client,
                symbol=symbol,
                coin=config.coin,
                quantity=config.quantity,
                target_price=config.sell_price,
                buy_price=config.buy_price,
                db=db,
                hp_id=config.hp_id,
                worker_queue=worker_queue,
                broker=broker,
                buy_position=buy_position,
            )

        elif len(sell_path) == 2:
            # Could be convert or multihop - check if first symbol has convert flag
            if (
                hasattr(sell_path[0], "is_convert_only")
                and sell_path[0].is_convert_only
            ):
                return ConvertSellStrategy(
                    client=client,
                    sell_symbol=sell_path[0],
                    convert_symbol=sell_path[1],
                    coin=config.coin,
                    quantity=config.quantity,
                    target_price=config.sell_price,
                    buy_price=config.buy_price,
                    db=db,
                    hp_id=config.hp_id,
                    worker_queue=worker_queue,
                    broker=broker,
                    buy_position=buy_position,
                )
            else:
                return MultihopSellStrategy(
                    client=client,
                    leg1_symbol=sell_path[0],
                    leg2_symbol=sell_path[1],
                    coin=config.coin,
                    quantity=config.quantity,
                    target_price=config.sell_price,
                    buy_price=config.buy_price,
                    db=db,
                    hp_id=config.hp_id,
                    worker_queue=worker_queue,
                    broker=broker,
                    price_resolver=price_resolver,
                    buy_position=buy_position,
                )

        else:
            raise ValueError(f"Unexpected sell path length: {len(sell_path)}")
