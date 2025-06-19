"""
Quick Start Guide for New Database System

This guide shows how to integrate the new database system into your existing trading application.
"""

import asyncio
import logging
from datetime import datetime

# New database imports
from src.database import (
    TradingDatabase,
    Position,
    PositionType,
    PositionStatus,
    TradeType,
)

# Existing system imports (examples)
from src.identifiers import HPBuyData, HPBuyConfig, StateInfo, State, PositionSide, Mode
from src.common.symbol_info import SymbolInfo

logger = logging.getLogger("database_quickstart")


class QuickStartExample:
    """Quick start example showing basic integration patterns."""

    def __init__(self, db_path: str = "trading.db"):
        self.db = TradingDatabase(db_path)

    async def save_buy_position_example(self):
        """Example: Save a buy position to the new database."""

        # Create a position using the new database model
        position = Position(
            hp_id="buy_001",
            position_type=PositionType.BUY,
            status=PositionStatus.NEW,
            symbol="BTCUSDC",
            coin="BTC",
            price_low=30000.0,
            price_high=35000.0,
            order_trigger=32000.0,
            budget=1000.0,
            mode="DCA",
            completeness=0.0,
        )

        # Save to database
        position_id = await self.db.save_position(position)
        print(f"Saved buy position: {position_id}")

        return position_id

    async def save_sell_position_example(self):
        """Example: Save a sell position to the new database."""

        position = Position(
            hp_id="sell_001",
            position_type=PositionType.SELL,
            status=PositionStatus.OPEN,
            symbol="BTCUSDC",
            coin="BTC",
            quantity=0.001,
            buy_price=32000.0,
            sell_price=35000.0,
            end_currency="USDC",
            trade_type=TradeType.DIRECT,
            completeness=0.0,
        )

        position_id = await self.db.save_position(position)
        print(f"Saved sell position: {position_id}")

        return position_id

    async def save_multihop_example(self):
        """Example: Save a multihop trading chain."""

        # Parent position
        parent = Position(
            hp_id="multihop_parent",
            position_type=PositionType.SELL,
            status=PositionStatus.OPEN,
            symbol="BTCUSDC",
            coin="BTC",
            trade_type=TradeType.TWOHOP,
            hop_sequence=0,
        )

        parent_id = await self.db.save_position(parent)

        # Child positions
        child1 = Position(
            hp_id="multihop_child_1",
            position_type=PositionType.SELL,
            status=PositionStatus.WAITING_CHILD,
            symbol="BTCETH",
            coin="BTC",
            parent_position_id=parent_id,
            trade_type=TradeType.TWOHOPS,
            hop_sequence=1,
        )

        child2 = Position(
            hp_id="multihop_child_2",
            position_type=PositionType.SELL,
            status=PositionStatus.WAITING_PARENT,
            symbol="ETHUSDC",
            coin="ETH",
            parent_position_id=parent_id,
            trade_type=TradeType.TWOHOPS,
            hop_sequence=2,
        )

        child1_id = await self.db.save_position(child1)
        child2_id = await self.db.save_position(child2)

        # Update parent with child references
        parent.child_position_ids = [child1_id, child2_id]
        await self.db.save_position(parent)

        print(
            f"Saved multihop chain: parent={parent_id}, children=[{child1_id}, {child2_id}]"
        )

        return parent_id, [child1_id, child2_id]

    async def recovery_example(self):
        """Example: Recovery process after system restart."""

        print("=== Recovery Process ===")

        # Get all active positions (this is what you'd do on system startup)
        active_positions = await self.db.get_active_positions()
        print(f"Found {len(active_positions)} active positions to recover")

        for position in active_positions:
            print(
                f"  - {position.hp_id}: {position.status.value} ({position.position_type.value})"
            )

            # Here you would reconstruct your trading system objects
            # For example:
            # if position.position_type == PositionType.BUY:
            #     buy_data = self.convert_to_buy_data(position)
            #     # Restore buy position in trading system
            # elif position.position_type == PositionType.SELL:
            #     sell_data = self.convert_to_sell_data(position)
            #     # Restore sell position in trading system

        return active_positions

    async def monitoring_example(self):
        """Example: Monitor database state."""

        # Get database statistics
        stats = await self.db.get_database_stats()
        print(f"Database Statistics: {stats}")

        # Create backup
        backup_path = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        await self.db.backup_database(backup_path)
        print(f"Backup created: {backup_path}")

        return stats

    async def run_examples(self):
        """Run all examples."""
        try:
            print("=== Database Quick Start Examples ===\n")

            # Basic operations
            await self.save_buy_position_example()
            await self.save_sell_position_example()

            # Multihop trading
            await self.save_multihop_example()

            # Recovery process
            await self.recovery_example()

            # Monitoring
            await self.monitoring_example()

            print("\n✅ All examples completed successfully!")

        except Exception as e:
            print(f"❌ Example failed: {e}")
            raise
        finally:
            await self.db.close()


# Integration points for existing system
class DatabaseIntegration:
    """Integration helpers for existing trading system."""

    def __init__(self, db: TradingDatabase):
        self.db = db

    async def convert_buy_data_to_position(self, buy_data: HPBuyData) -> Position:
        """Convert existing HPBuyData to new Position model."""

        return Position(
            hp_id=buy_data.config.hp_id,
            position_type=PositionType.BUY,
            status=self._convert_state(buy_data.state_info.state),
            symbol=buy_data.config.symbol_info.symbol,
            coin=buy_data.config.coin,
            price_low=buy_data.config.price_low,
            price_high=buy_data.config.price_high,
            order_trigger=buy_data.config.order_trigger,
            budget=buy_data.config.budget,
            mode=buy_data.config.mode.value,
            completeness=buy_data.state_info.completeness,
            created_at=(
                datetime.strptime(buy_data.state_info.open_time, "%Y-%m-%d %H:%M:%S")
                if buy_data.state_info.open_time
                else datetime.now()
            ),
        )

    def _convert_state(self, old_state: State) -> PositionStatus:
        """Convert old State enum to new PositionStatus."""

        mapping = {
            State.NEW: PositionStatus.NEW,
            State.BUYING: PositionStatus.OPEN,
            State.SELLING: PositionStatus.OPEN,
            State.PARTIALLY_BOUGHT: PositionStatus.PARTIALLY_FILLED,
            State.PARTIALLY_SOLD: PositionStatus.PARTIALLY_FILLED,
            State.BOUGHT: PositionStatus.FILLED,
            State.SOLD: PositionStatus.FILLED,
            State.CLOSED: PositionStatus.CLOSED,
        }

        return mapping.get(old_state, PositionStatus.NEW)


async def main():
    """Run the quick start examples."""
    logging.basicConfig(level=logging.INFO)

    example = QuickStartExample("quickstart_example.db")
    await example.run_examples()


if __name__ == "__main__":
    asyncio.run(main())
