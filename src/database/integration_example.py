"""
Integration example showing how to use the new database system
with the existing trading system.
"""

import asyncio
import logging
from datetime import datetime

from src.database import TradingDatabase, RecoveryService, PositionManager
from src.database.models import Position, PositionType, PositionStatus, TradeType
from src.identifiers import HPBuyData, HPBuyConfig, StateInfo, State, PositionSide, Mode
from src.common.symbol_info import SymbolInfo

logger = logging.getLogger("database_integration")


class DatabaseIntegrationExample:
    """
    Example showing how to integrate the new database with the existing trading system.
    """

    def __init__(self, db_path: str = "trading_integration_example.db"):
        self.database = TradingDatabase(db_path)
        self.position_manager = PositionManager(self.database)
        # Note: RecoveryService would need a real client and symbols_info
        # self.recovery_service = RecoveryService(self.database, client, symbols_info)

    async def demonstrate_basic_operations(self):
        """Demonstrate basic database operations."""
        logger.info("=== Basic Database Operations ===")

        # 1. Save a buy position
        symbol_info = SymbolInfo(symbol="BTCUSDC", precision=8, price_precision=2)

        buy_config = HPBuyConfig(
            symbol_info=symbol_info,
            coin="BTC",
            hp_id="demo_buy_001",
            price_low=30000.0,
            price_high=35000.0,
            order_trigger=32000.0,
            budget=1000.0,
            mode=Mode.DCA,
        )

        state_info = StateInfo(
            state=State.NEW, side=PositionSide.LONG, completeness=0.0
        )

        buy_data = HPBuyData(config=buy_config, state_info=state_info)

        # Save the buy position
        position_id = await self.position_manager.save_buy_position(buy_data)
        logger.info(f"Saved buy position with ID: {position_id}")

        # 2. Get database statistics
        stats = await self.database.get_database_stats()
        logger.info(f"Database stats: {stats}")

        # 3. Retrieve active positions
        active_positions = await self.database.get_active_positions()
        logger.info(f"Found {len(active_positions)} active positions")

        # 4. Get position status
        status = await self.position_manager.get_position_status("demo_buy_001")
        logger.info(f"Position status: {status}")

    async def demonstrate_multihop_operations(self):
        """Demonstrate multihop trading operations."""
        logger.info("=== Multihop Trading Operations ===")

        # Create a parent position
        parent_position = Position(
            hp_id="multihop_parent",
            position_type=PositionType.SELL,
            status=PositionStatus.OPEN,
            symbol="BTCUSDC",
            coin="BTC",
            quantity=0.1,
            buy_price=32000.0,
            sell_price=35000.0,
            trade_type=TradeType.TWOHOP,
        )

        # Create child positions (hop 1 and hop 2)
        child1 = Position(
            hp_id="multihop_child_1",
            position_type=PositionType.SELL,
            status=PositionStatus.WAITING_CHILD,
            symbol="BTCETH",
            coin="BTC",
            parent_position_id=parent_position.id,
            trade_type=TradeType.TWOHOP,
            hop_sequence=1,
        )

        child2 = Position(
            hp_id="multihop_child_2",
            position_type=PositionType.SELL,
            status=PositionStatus.WAITING_PARENT,
            symbol="ETHUSDC",
            coin="ETH",
            parent_position_id=parent_position.id,
            trade_type=TradeType.TWOHOP,
            hop_sequence=2,
        )

        # Save positions
        await self.database.save_position(parent_position)
        child1_id = await self.database.save_position(child1)
        child2_id = await self.database.save_position(child2)

        # Update parent with child IDs
        parent_position.child_position_ids = [child1_id, child2_id]
        await self.database.save_position(parent_position)

        # Retrieve the complete hierarchy
        hierarchy = await self.database.get_position_hierarchy("multihop_parent")
        logger.info(f"Multihop hierarchy has {len(hierarchy)} positions")

        for pos in hierarchy:
            logger.info(f"  - {pos.hp_id}: {pos.status.value} (hop {pos.hop_sequence})")

    async def demonstrate_recovery_scenario(self):
        """Demonstrate recovery scenario after system restart."""
        logger.info("=== Recovery Scenario ===")

        # Simulate having some positions in the database
        positions = [
            Position(
                hp_id="recovery_001",
                position_type=PositionType.BUY,
                status=PositionStatus.PARTIALLY_FILLED,
                symbol="BTCUSDC",
                coin="BTC",
                completeness=0.6,
            ),
            Position(
                hp_id="recovery_002",
                position_type=PositionType.SELL,
                status=PositionStatus.OPEN,
                symbol="ETHUSDC",
                coin="ETH",
                completeness=0.0,
            ),
        ]

        for pos in positions:
            await self.database.save_position(pos)

        # Simulate recovery process
        logger.info("Simulating system restart...")

        # Get all active positions (this is what recovery would do)
        active_positions = await self.database.get_active_positions()
        logger.info(f"Recovered {len(active_positions)} active positions")

        for pos in active_positions:
            logger.info(
                f"  - {pos.hp_id}: {pos.status.value} ({pos.completeness*100:.1f}% complete)"
            )

    async def demonstrate_position_updates(self):
        """Demonstrate position updates during trading."""
        logger.info("=== Position Updates During Trading ===")

        # Create a position
        position = Position(
            hp_id="update_demo",
            position_type=PositionType.BUY,
            status=PositionStatus.NEW,
            symbol="BTCUSDC",
            coin="BTC",
            quantity=0.001,
            completeness=0.0,
        )

        await self.database.save_position(position)
        logger.info(f"Created position: {position.status.value}")

        # Simulate position updates
        updates = [
            (PositionStatus.OPEN, 0.0, "Order placed"),
            (PositionStatus.PARTIALLY_FILLED, 0.3, "Partially filled"),
            (PositionStatus.PARTIALLY_FILLED, 0.7, "More filled"),
            (PositionStatus.FILLED, 1.0, "Completely filled"),
            (PositionStatus.CLOSED, 1.0, "Position closed"),
        ]

        for status, completeness, description in updates:
            position.status = status
            position.completeness = completeness
            await self.database.save_position(position)
            logger.info(
                f"Updated position: {description} - {status.value} ({completeness*100:.1f}%)"
            )

    async def demonstrate_database_monitoring(self):
        """Demonstrate database monitoring and statistics."""
        logger.info("=== Database Monitoring ===")

        # Get comprehensive statistics
        stats = await self.database.get_database_stats()
        logger.info("Database Statistics:")
        for table, count in stats.items():
            logger.info(f"  {table}: {count}")

        # Create a backup
        backup_path = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        await self.database.backup_database(backup_path)
        logger.info(f"Created backup: {backup_path}")

        # Get active positions summary
        active_positions = await self.database.get_active_positions()

        status_counts = {}
        for pos in active_positions:
            status = pos.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

        logger.info("Active Positions by Status:")
        for status, count in status_counts.items():
            logger.info(f"  {status}: {count}")

    async def run_all_demonstrations(self):
        """Run all demonstration scenarios."""
        try:
            await self.demonstrate_basic_operations()
            await self.demonstrate_multihop_operations()
            await self.demonstrate_recovery_scenario()
            await self.demonstrate_position_updates()
            await self.demonstrate_database_monitoring()

            logger.info("=== All demonstrations completed successfully ===")

        except Exception as e:
            logger.error(f"Demonstration failed: {e}")
            raise
        finally:
            await self.database.close()


async def main():
    """Run the database integration example."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    example = DatabaseIntegrationExample()
    await example.run_all_demonstrations()


if __name__ == "__main__":
    asyncio.run(main())
