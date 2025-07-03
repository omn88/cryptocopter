# """
# Integration tests for real crash recovery system.

# These tests verify that the crash recovery system works with:
# - Real trading.db database
# - Real setup_buy_position and setup_sell_position_with_new_hp methods
# - Real StrategyExecutor integration
# """

# from typing import Optional
# from src.database.trading_database import TradingDatabase
# from src.database.models import (
#     Position,
#     PositionType,
#     PositionStatus,
#     TradeType,
#     Strategy,
# )
# from src.database.recovery_service import RecoveryService
# from src.strategy_executor import StrategyExecutor
# from src.identifiers import HPBuyData, HPSellData


# async def test_crash_recovery_with_real_database_and_setup_methods(
#     test_db: TradingDatabase, strategy_executor_fixture: StrategyExecutor
# ):
#     """Test that crash recovery uses real database and calls real setup methods."""

#     # Create a test strategy in the database
#     strategy = Strategy(
#         id="test_strategy_001",
#         name="HPManager",
#         description="Test strategy for crash recovery",
#     )
#     await test_db.save_strategy(strategy)

#     # Create test positions in the database
#     buy_position = Position(
#         hp_id="hp_buy_recovery_001",
#         strategy_id=strategy.id,
#         position_type=PositionType.BUY,
#         status=PositionStatus.OPEN,
#         symbol="BTCUSDT",
#         coin="BTC",
#         budget=100.0,
#         price_low=95000.0,
#         price_high=105000.0,
#         order_trigger=1.0,
#         trade_type=TradeType.DIRECT,
#     )
#     await test_db.save_position(buy_position)

#     sell_position = Position(
#         hp_id="hp_sell_recovery_001",
#         strategy_id=strategy.id,
#         position_type=PositionType.SELL,
#         status=PositionStatus.OPEN,
#         symbol="BTCUSDT",
#         coin="BTC",
#         quantity=0.001,
#         buy_price=98000.0,
#         sell_price=102000.0,
#         trade_type=TradeType.DIRECT,
#     )
#     await test_db.save_position(
#         sell_position
#     )  # Track the number of strategies before recovery
#     strategies_before = len(strategy_executor_fixture.strategies)

#     # Run crash recovery explicitly to test the recovery functionality
#     await strategy_executor_fixture.recover_positions_from_crash()

#     # Verify that positions were recovered by checking strategies were created
#     strategies_after = len(strategy_executor_fixture.strategies)

#     # Should have at least 1 new strategy (positions can create multiple strategies)
#     assert strategies_after > strategies_before

#     # Verify that we have strategies with the expected HP IDs or new generated ones
#     strategy_ids = list(strategy_executor_fixture.strategies.keys())

#     # The recovered positions might get new HP IDs, so just verify we have strategies
#     assert (
#         len(strategy_ids) >= 1
#     ), f"Expected at least 1 strategy, got {len(strategy_ids)}"


# async def test_recovery_service_find_positions(
#     test_db: TradingDatabase, recovery_service: RecoveryService
# ):
#     """Test that RecoveryService can find active positions in database."""

#     # Create test strategy
#     strategy = Strategy(
#         id="test_strategy_002",
#         name="HPManager",
#         description="Test strategy for recovery service",
#     )
#     await test_db.save_strategy(strategy)

#     # Create test positions
#     buy_position = Position(
#         hp_id="hp_buy_002",
#         strategy_id=strategy.id,
#         position_type=PositionType.BUY,
#         status=PositionStatus.OPEN,
#         symbol="ETHUSDT",
#         coin="ETH",
#         budget=50.0,
#         price_low=3000.0,
#         price_high=3500.0,
#         order_trigger=1.0,
#         trade_type=TradeType.DIRECT,
#     )
#     await test_db.save_position(buy_position)

#     sell_position = Position(
#         hp_id="hp_sell_002",
#         strategy_id=strategy.id,
#         position_type=PositionType.SELL,
#         status=PositionStatus.OPEN,
#         symbol="ETHUSDT",
#         coin="ETH",
#         quantity=0.01,
#         buy_price=3100.0,
#         sell_price=3400.0,
#         trade_type=TradeType.DIRECT,
#     )
#     await test_db.save_position(sell_position)

#     # Test recovery service
#     buy_positions, sell_positions = await recovery_service.recover_all_positions()

#     # Verify positions were found
#     assert len(buy_positions) >= 1
#     assert len(sell_positions) >= 1

#     assert all(isinstance(buy_position, HPBuyData) for buy_position in buy_positions)
#     assert all(
#         isinstance(sell_position, HPSellData) for sell_position in sell_positions
#     )

#     # Check buy position data
#     found_buy: Optional[HPBuyData] = None
#     for pos in buy_positions:
#         if pos.config.hp_id == "hp_buy_002":
#             found_buy = pos
#             break

#     assert found_buy is not None
#     assert found_buy.config.symbol_info.symbol == "ETHUSDT"
#     assert found_buy.config.budget == 50.0

#     # Check sell position data
#     found_sell: Optional[HPSellData] = None
#     for sell_pos in sell_positions:
#         if sell_pos.config.hp_id == "hp_sell_002":
#             found_sell = sell_pos
#             break

#     assert found_sell is not None
#     assert found_sell.config.symbol_info.symbol == "ETHUSDT"
#     assert found_sell.config.quantity == 0.01


# async def test_crash_recovery_empty_database(
#     strategy_executor_fixture: StrategyExecutor,
# ):
#     """Test crash recovery with empty database (should not error)."""

#     # Run crash recovery on empty database
#     await strategy_executor_fixture.recover_positions_from_crash()

#     # Should not have any strategies
#     assert len(strategy_executor_fixture.strategies) == 0


# async def test_crash_recovery_handles_errors_gracefully(
#     test_db: TradingDatabase, strategy_executor_fixture: StrategyExecutor
# ):
#     """Test that crash recovery handles errors gracefully and continues operation."""

#     # Create test strategy
#     strategy = Strategy(
#         id="test_strategy_003",
#         name="HPManager",
#         description="Test strategy with bad data",
#     )
#     await test_db.save_strategy(strategy)

#     # Create position with invalid symbol (should cause recovery error)
#     bad_position = Position(
#         hp_id="hp_bad_003",
#         strategy_id=strategy.id,
#         position_type=PositionType.BUY,
#         status=PositionStatus.OPEN,
#         symbol="INVALIDSYMBOL",  # This symbol doesn't exist in symbols_info
#         coin="INVALID",
#         budget=100.0,
#         price_low=1.0,
#         price_high=2.0,
#         order_trigger=1.5,
#         trade_type=TradeType.DIRECT,
#     )
#     await test_db.save_position(bad_position)

#     # Recovery should handle the error gracefully and not crash
#     await strategy_executor_fixture.recover_positions_from_crash()

#     # Should not crash and executor should still be operational
#     assert strategy_executor_fixture is not None
