"""
Example integration of the new database system with the trading application.

This example shows how to:
1. Initialize the new database
2. Save positions during trading
3. Recover positions after restart
4. Handle multihop trades
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from src.database import (
    TradingDatabase,
    RecoveryService,
    PositionManager,
    Position,
    PositionType,
    PositionStatus,
    TradeType,
)
from src.identifiers import (
    BinanceClient,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    StateInfo,
    State,
    PositionSide,
    Mode,
)
from src.common.symbol_info import SymbolInfo

logger = logging.getLogger("database_example")


class TradingSystemWithNewDatabase:
    """
    Example of how to integrate the new database with the trading system.
    """

    def __init__(self, client: BinanceClient, symbols_info: Dict[str, SymbolInfo]):
        # Initialize the new database components
        self.database = TradingDatabase("trading_positions.db")
        self.position_manager = PositionManager(self.database)
        self.recovery_service = RecoveryService(self.database, client, symbols_info)

        self.client = client
        self.symbols_info = symbols_info

        # Storage for active positions
        self.active_buy_positions: Dict[str, HPBuyData] = {}
        self.active_sell_positions: Dict[str, HPSellData] = {}

    async def initialize(self):
        """Initialize the trading system with database recovery."""
        logger.info("Initializing trading system with new database...")

        # Attempt to recover existing positions
        try:
            buy_positions, sell_positions = (
                await self.recovery_service.recover_all_positions()
            )

            # Store recovered positions
            for buy_pos in buy_positions:
                self.active_buy_positions[buy_pos.config.hp_id] = buy_pos
                logger.info(f"Recovered buy position: {buy_pos.config.hp_id}")

            for sell_pos in sell_positions:
                self.active_sell_positions[sell_pos.config.hp_id] = sell_pos
                logger.info(f"Recovered sell position: {sell_pos.config.hp_id}")

            logger.info(
                f"Recovery completed: {len(buy_positions)} buy, {len(sell_positions)} sell positions"
            )

        except Exception as e:
            logger.error(f"Recovery failed: {e}")
            # Continue with empty state

    async def create_buy_position(
        self, symbol: str, coin: str, budget: float, price_low: float, price_high: float
    ) -> str:
        """
        Create a new buy position and save it to database.

        Returns:
            HP ID of the created position
        """
        try:
            # Generate unique HP ID
            hp_id = f"HP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            # Create position configuration
            symbol_info = self.symbols_info.get(symbol)
            if not symbol_info:
                raise ValueError(f"Symbol {symbol} not found")

            config = HPBuyConfig(
                symbol_info=symbol_info,
                coin=coin,
                hp_id=hp_id,
                price_low=price_low,
                price_high=price_high,
                order_trigger=(price_low + price_high) / 2,
                budget=budget,
                mode=Mode.DCA,
            )

            state_info = StateInfo(state=State.NEW, side=PositionSide.LONG)

            buy_data = HPBuyData(config=config, state_info=state_info)

            # Save to database
            await self.position_manager.save_buy_position(buy_data)

            # Store in memory
            self.active_buy_positions[hp_id] = buy_data

            logger.info(f"Created buy position {hp_id} for {symbol}")
            return hp_id

        except Exception as e:
            logger.error(f"Failed to create buy position: {e}")
            raise

    async def create_sell_position(
        self,
        coin: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        parent_hp_id: Optional[str] = None,
    ) -> str:
        """
        Create a new sell position and save it to database.

        Returns:
            HP ID of the created position
        """
        try:
            # Generate unique HP ID
            if parent_hp_id:
                hp_id = f"{parent_hp_id}_sell"
            else:
                hp_id = f"HP_SELL_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            # Determine symbol (assume USDC pair for now)
            symbol = f"{coin}USDC"
            symbol_info = self.symbols_info.get(symbol)
            if not symbol_info:
                raise ValueError(f"Symbol {symbol} not found")

            config = HPSellConfig(
                symbol_info=symbol_info,
                hp_id=hp_id,
                coin=coin,
                quantity=quantity,
                buy_price=buy_price,
                sell_price=sell_price,
                end_currency="USDC",
                is_child=parent_hp_id is not None,
                parent_hp_id=parent_hp_id,
            )

            state_info = StateInfo(state=State.NEW, side=PositionSide.SHORT)

            sell_data = HPSellData(config=config, state_info=state_info)

            # Save to database
            await self.position_manager.save_sell_position(sell_data, parent_hp_id)

            # Store in memory
            self.active_sell_positions[hp_id] = sell_data

            logger.info(f"Created sell position {hp_id} for {coin}")
            return hp_id

        except Exception as e:
            logger.error(f"Failed to create sell position: {e}")
            raise

    async def update_position_status(
        self, hp_id: str, new_state: State, realized_quantity: float = 0.0
    ):
        """
        Update position status and save to database.
        """
        try:
            # Update buy position
            if hp_id in self.active_buy_positions:
                buy_data = self.active_buy_positions[hp_id]
                buy_data.state_info.state = new_state
                if realized_quantity > 0:
                    buy_data.state_info.completeness = (
                        realized_quantity / buy_data.config.budget
                    )

                await self.position_manager.save_buy_position(buy_data)
                logger.info(f"Updated buy position {hp_id} to state {new_state.value}")

            # Update sell position
            elif hp_id in self.active_sell_positions:
                sell_data = self.active_sell_positions[hp_id]
                sell_data.state_info.state = new_state
                if realized_quantity > 0:
                    sell_data.state_info.completeness = (
                        realized_quantity / sell_data.config.quantity
                    )

                await self.position_manager.save_sell_position(sell_data)
                logger.info(f"Updated sell position {hp_id} to state {new_state.value}")

            else:
                logger.warning(f"Position {hp_id} not found in active positions")

        except Exception as e:
            logger.error(f"Failed to update position {hp_id}: {e}")

    async def close_position(self, hp_id: str):
        """
        Close a position and remove from active tracking.
        """
        try:
            # Mark as closed in database
            await self.position_manager.close_position(hp_id)

            # Remove from active positions
            if hp_id in self.active_buy_positions:
                del self.active_buy_positions[hp_id]
                logger.info(f"Closed buy position {hp_id}")
            elif hp_id in self.active_sell_positions:
                del self.active_sell_positions[hp_id]
                logger.info(f"Closed sell position {hp_id}")
            else:
                logger.warning(f"Position {hp_id} not found in active positions")

        except Exception as e:
            logger.error(f"Failed to close position {hp_id}: {e}")

    async def get_position_summary(self) -> Dict:
        """
        Get summary of all positions.
        """
        try:
            # Get database statistics
            db_stats = await self.database.get_database_stats()

            # Get active positions count
            active_buy_count = len(self.active_buy_positions)
            active_sell_count = len(self.active_sell_positions)

            return {
                "database_stats": db_stats,
                "active_positions": {
                    "buy": active_buy_count,
                    "sell": active_sell_count,
                    "total": active_buy_count + active_sell_count,
                },
                "buy_positions": list(self.active_buy_positions.keys()),
                "sell_positions": list(self.active_sell_positions.keys()),
            }

        except Exception as e:
            logger.error(f"Failed to get position summary: {e}")
            return {"error": str(e)}

    async def shutdown(self):
        """
        Gracefully shutdown the database system.
        """
        try:
            # Create backup before shutdown
            backup_path = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            await self.database.backup_database(backup_path)
            logger.info(f"Database backed up to {backup_path}")

            # Close database connections
            await self.database.close()
            logger.info("Database system shutdown completed")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


# Example usage
async def example_usage():
    """
    Example of how to use the new database system.
    """
    # This would be your actual client and symbols_info
    client = None  # BinanceClient(api_key="...", api_secret="...")
    symbols_info = {}  # Your symbol info dictionary

    # Initialize trading system
    trading_system = TradingSystemWithNewDatabase(client, symbols_info)
    await trading_system.initialize()

    # Create some example positions
    if symbols_info:  # Only if we have real symbol info
        # Create a buy position
        buy_hp_id = await trading_system.create_buy_position(
            symbol="BTCUSDC",
            coin="BTC",
            budget=1000.0,
            price_low=40000.0,
            price_high=42000.0,
        )

        # Update position status
        await trading_system.update_position_status(
            buy_hp_id, State.PARTIALLY_BOUGHT, realized_quantity=500.0
        )

        # Create a sell position
        sell_hp_id = await trading_system.create_sell_position(
            coin="BTC",
            quantity=0.01,
            buy_price=41000.0,
            sell_price=43000.0,
            parent_hp_id=buy_hp_id,
        )

    # Get summary
    summary = await trading_system.get_position_summary()
    print(f"Position summary: {summary}")

    # Shutdown
    await trading_system.shutdown()


if __name__ == "__main__":
    # Run the example
    asyncio.run(example_usage())
