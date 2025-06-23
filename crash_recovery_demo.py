#!/usr/bin/env python3
"""
Demo script showing how crash recovery works with real database.

This script demonstrates:
1. Creating positions in trading.db
2. Simulating system restart
3. Recovering positions using the real recovery system
"""

import asyncio
import logging
from unittest.mock import AsyncMock

from src.common.symbol_info import SymbolInfo
from src.database.models import (
    Position,
    PositionStatus,
    PositionType,
    Strategy,
    TradeType,
)
from src.database.recovery_service import RecoveryService
from src.database.trading_database import TradingDatabase

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("crash_recovery_demo")


async def demo_crash_recovery():
    """Demonstrate the complete crash recovery flow."""
    logger.info("=== CRASH RECOVERY DEMO ===")

    # Step 1: Set up database and create test positions
    logger.info("Step 1: Creating test positions in trading.db")

    db = TradingDatabase("demo_trading.db")  # Use a demo database file

    # Create a test strategy
    strategy = Strategy(
        id="demo_strategy_001",
        name="HPManager",
        description="Demo strategy for crash recovery testing",
    )
    await db.save_strategy(strategy)
    logger.info("Created strategy: %s", strategy.name)

    # Create test positions
    positions = [
        Position(
            hp_id="demo_buy_001",
            strategy_id=strategy.id,
            position_type=PositionType.BUY,
            status=PositionStatus.OPEN,
            symbol="BTCUSDT",
            coin="BTC",
            budget=1000.0,
            price_low=95000.0,
            price_high=105000.0,
            order_trigger=100000.0,
            mode="DCA",
            trade_type=TradeType.DIRECT,
        ),
        Position(
            hp_id="demo_sell_001",
            strategy_id=strategy.id,
            position_type=PositionType.SELL,
            status=PositionStatus.OPEN,
            symbol="BTCUSDT",
            coin="BTC",
            quantity=0.01,
            buy_price=98000.0,
            sell_price=105000.0,
            trade_type=TradeType.DIRECT,
        ),
        Position(
            hp_id="demo_buy_002",
            strategy_id=strategy.id,
            position_type=PositionType.BUY,
            status=PositionStatus.PARTIALLY_FILLED,
            symbol="ETHUSDT",
            coin="ETH",
            budget=500.0,
            price_low=2300.0,
            price_high=2500.0,
            order_trigger=2400.0,
            realized_quantity=0.1,
            mode="DCA",
            trade_type=TradeType.DIRECT,
        ),
    ]

    for position in positions:
        await db.save_position(position)
        logger.info(
            "Created %s position: %s (status: %s)",
            position.position_type.value,
            position.hp_id,
            position.status.value,
        )

    # Step 2: Simulate system restart - close database connection
    logger.info("\nStep 2: Simulating system restart...")
    await db.close()
    logger.info("Database connection closed (simulating system shutdown)")

    # Step 3: Start recovery process (like system startup)
    logger.info("\nStep 3: Starting crash recovery process...")

    # Create new database connection (like app startup)
    recovery_db = TradingDatabase("demo_trading.db")

    # Set up symbols info (normally loaded during app startup)
    symbols_info = {
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": SymbolInfo(symbol="ETHUSDT", precision=5, price_precision=2),
    }

    # Create mock client (normally the real Binance client)
    mock_client = AsyncMock()

    # Create recovery service
    recovery_service = RecoveryService(
        database=recovery_db, client=mock_client, symbols_info=symbols_info
    )

    # Step 4: Recover positions
    logger.info("Recovering positions from database...")

    buy_positions, sell_positions = await recovery_service.recover_all_positions()

    logger.info(
        "Recovery completed: %d buy positions, %d sell positions",
        len(buy_positions),
        len(sell_positions),
    )

    # Step 5: Display recovered positions
    logger.info("\nStep 5: Recovered positions:")

    for i, buy_data in enumerate(buy_positions, 1):
        logger.info(
            "Buy Position %d: %s (symbol: %s, budget: %.2f, status: %s)",
            i,
            buy_data.config.hp_id,
            buy_data.config.symbol_info.symbol,
            buy_data.config.budget,
            buy_data.state_info.state.value,
        )

    for i, sell_data in enumerate(sell_positions, 1):
        logger.info(
            "Sell Position %d: %s (symbol: %s, quantity: %.3f, sell_price: %.2f)",
            i,
            sell_data.config.hp_id,
            sell_data.config.symbol_info.symbol,
            sell_data.config.quantity,
            sell_data.config.sell_price,
        )

    # Step 6: Demonstrate what would happen in StrategyExecutor
    logger.info(
        "\nStep 6: What happens in StrategyExecutor.recover_positions_from_crash():"
    )
    logger.info("- For each buy position: setup_buy_position(buy_data) would be called")
    logger.info(
        "- For each sell position: setup_sell_position_with_new_hp(sell_data) would be called"
    )
    logger.info(
        "- Trading strategies would be fully restored and continue where they left off"
    )

    # Cleanup
    await recovery_db.close()
    logger.info("\n=== DEMO COMPLETED ===")
    logger.info("Demo database: demo_trading.db (you can examine it with sqlite3)")


async def demo_recovery_validation():
    """Demonstrate recovery validation features."""
    logger.info("\n=== RECOVERY VALIDATION DEMO ===")

    db = TradingDatabase("demo_trading.db")

    symbols_info = {
        "BTCUSDT": SymbolInfo(symbol="BTCUSDT", precision=5, price_precision=2),
        "ETHUSDT": SymbolInfo(symbol="ETHUSDT", precision=5, price_precision=2),
    }

    mock_client = AsyncMock()

    recovery_service = RecoveryService(
        database=db, client=mock_client, symbols_info=symbols_info
    )

    # Validate recovery integrity
    logger.info("Running recovery integrity validation...")

    issues = await recovery_service.validate_recovery_integrity()

    logger.info("Validation results:")
    for issue_type, issue_list in issues.items():
        if issue_list:
            logger.warning("%s: %s", issue_type, issue_list)
        else:
            logger.info("%s: No issues found", issue_type)

    await db.close()


if __name__ == "__main__":
    asyncio.run(demo_crash_recovery())
    asyncio.run(demo_recovery_validation())
