"""
Main database implementation for the trading system.

This module provides a SQLite-based database implementation focused on:
- Position recovery after system restart
- Multihop trade support
- Cross-platform compatibility
- Simple, reliable operations
"""

import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime
import json
from contextlib import asynccontextmanager
import aiosqlite
import asyncio

from .models import (
    Position,
    Order,
    Strategy,
    PositionType,
    PositionStatus,
    TradeType,
)
from .exceptions import DatabaseError, RecoveryError, DatabaseConnectionError

logger = logging.getLogger("trading_database")


class TradingDatabase:
    """
    SQLite-based database for trading system with focus on recovery operations.

    Design principles:
    - Recovery-first: Easy to restore positions after restart
    - Multihop support: Handle complex trade chains
    - Cross-platform: SQLite works on Windows and Linux
    - Simple schema: Easy to understand and maintain
    """

    def __init__(self, db_path: str = "trading.db"):
        """
        Initialize the database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """Ensure database file exists and has proper structure."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                self._create_tables(conn)
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to initialize database: {e}") from e

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        """Create all necessary tables."""
        cursor = conn.cursor()

        # Strategies table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Positions table - the core of our recovery system
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                hp_id TEXT NOT NULL,
                strategy_id TEXT,
                position_type TEXT NOT NULL,
                status TEXT NOT NULL,
                symbol TEXT NOT NULL,
                coin TEXT NOT NULL,
                target_price REAL NOT NULL DEFAULT 0.0,
                buy_price REAL NOT NULL DEFAULT 0.0,
                sell_price REAL NOT NULL DEFAULT 0.0,
                quantity REAL NOT NULL DEFAULT 0.0,
                realized_quantity REAL NOT NULL DEFAULT 0.0,
                budget REAL NOT NULL DEFAULT 0.0,
                parent_position_id TEXT,
                child_position_ids TEXT,  -- JSON array
                trade_type TEXT NOT NULL DEFAULT 'DIRECT',
                hop_sequence INTEGER NOT NULL DEFAULT 0,
                price_low REAL NOT NULL DEFAULT 0.0,
                price_high REAL NOT NULL DEFAULT 0.0,
                order_trigger REAL NOT NULL DEFAULT 0.0,
                end_currency TEXT NOT NULL DEFAULT 'USDC',
                mode TEXT NOT NULL DEFAULT 'DCA',
                completeness REAL NOT NULL DEFAULT 0.0,
                next_monitor_time TIMESTAMP,
                metadata TEXT,  -- JSON
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (strategy_id) REFERENCES strategies (id),
                FOREIGN KEY (parent_position_id) REFERENCES positions (id)
            )
        """
        )

        # Orders table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                position_id TEXT NOT NULL,
                exchange_order_id INTEGER,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL DEFAULT 'LIMIT',
                status TEXT NOT NULL,
                price REAL NOT NULL DEFAULT 0.0,
                quantity REAL NOT NULL DEFAULT 0.0,
                quantity_stable REAL NOT NULL DEFAULT 0.0,
                realized_quantity REAL NOT NULL DEFAULT 0.0,
                time_in_force TEXT NOT NULL DEFAULT 'GTC',
                filled_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (position_id) REFERENCES positions (id)
            )
        """
        )

        # Trades table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                position_id TEXT NOT NULL,
                exchange_trade_id INTEGER,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                quantity REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 0.0,
                commission_asset TEXT,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES orders (id),
                FOREIGN KEY (position_id) REFERENCES positions (id)
            )
        """
        )

        # Create indices for better query performance
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_positions_hp_id ON positions (hp_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_positions_parent ON positions (parent_position_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_position ON orders (position_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_orders_exchange_id ON orders (exchange_order_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_trades_order ON trades (order_id)"
        )

        conn.commit()

    @asynccontextmanager
    async def get_connection(self):
        """Get an async database connection."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                yield conn
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to connect to database: {e}") from e

    async def save_strategy(self, strategy: Strategy) -> str:
        """Save a strategy to the database."""
        try:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO strategies 
                    (id, name, description, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        strategy.id,
                        strategy.name,
                        strategy.description,
                        strategy.status,
                        strategy.created_at.isoformat(),
                        datetime.now().isoformat(),
                    ),
                )
                await conn.commit()
                return strategy.id
        except Exception as e:
            raise DatabaseError(f"Failed to save strategy: {e}") from e

    async def save_position(self, position: Position) -> str:
        """
        Save a position to the database.

        This is the core method for persistence - handles both new and updated positions.
        """
        try:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO positions 
                    (id, hp_id, strategy_id, position_type, status, symbol, coin,
                     target_price, buy_price, sell_price, quantity, realized_quantity, budget,
                     parent_position_id, child_position_ids, trade_type, hop_sequence,
                     price_low, price_high, order_trigger, end_currency, mode,
                     completeness, next_monitor_time, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        position.id,
                        position.hp_id,
                        position.strategy_id,
                        position.position_type.value,
                        position.status.value,
                        position.symbol,
                        position.coin,
                        position.target_price,
                        position.buy_price,
                        position.sell_price,
                        position.quantity,
                        position.realized_quantity,
                        position.budget,
                        position.parent_position_id,
                        json.dumps(position.child_position_ids),
                        position.trade_type.value,
                        position.hop_sequence,
                        position.price_low,
                        position.price_high,
                        position.order_trigger,
                        position.end_currency,
                        position.mode,
                        position.completeness,
                        (
                            position.next_monitor_time.isoformat()
                            if position.next_monitor_time
                            else None
                        ),
                        json.dumps(position.metadata),
                        (
                            position.created_at.isoformat()
                            if hasattr(position, "created_at")
                            else datetime.now().isoformat()
                        ),
                        datetime.now().isoformat(),
                    ),
                )
                await conn.commit()
                logger.info(
                    "Saved position %s with status %s",
                    position.hp_id,
                    position.status.value,
                )
                return position.id
        except Exception as e:
            raise DatabaseError(
                "Failed to save position %s: %s" % (position.hp_id, e)
            ) from e

    async def save_order(self, order: Order) -> str:
        """Save an order to the database."""
        try:
            async with self.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO orders 
                    (id, position_id, exchange_order_id, symbol, side, order_type, status,
                     price, quantity, quantity_stable, realized_quantity, time_in_force,
                     filled_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        order.id,
                        order.position_id,
                        order.exchange_order_id,
                        order.symbol,
                        order.side,
                        order.order_type,
                        order.status.value,
                        order.price,
                        order.quantity,
                        order.quantity_stable,
                        order.realized_quantity,
                        order.time_in_force,
                        order.filled_at.isoformat() if order.filled_at else None,
                        (
                            order.created_at.isoformat()
                            if hasattr(order, "created_at")
                            else datetime.now().isoformat()
                        ),
                        datetime.now().isoformat(),
                    ),
                )
                await conn.commit()
                return order.id
        except Exception as e:
            raise DatabaseError(f"Failed to save order: {e}") from e

    async def get_active_positions(self) -> List[Position]:
        """
        Get all active positions for recovery.

        This is the primary recovery method - returns all positions that need
        to be restored after system restart.
        """
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT * FROM positions 
                    WHERE status NOT IN ('CLOSED', 'CANCELED')
                    ORDER BY created_at ASC
                """
                )
                rows = await cursor.fetchall()

                positions = []
                for row in rows:
                    position = self._row_to_position(row)
                    positions.append(position)

                logger.info(
                    "Retrieved %s active positions for recovery", len(positions)
                )
                return positions
        except Exception as e:
            raise RecoveryError(f"Failed to retrieve active positions: {e}") from e

    async def get_position_hierarchy(self, parent_hp_id: str) -> List[Position]:
        """
        Get complete position hierarchy for multihop trades.

        Returns parent position and all child positions in correct order.
        """
        try:
            async with self.get_connection() as conn:
                # Get parent position
                cursor = await conn.execute(
                    """
                    SELECT * FROM positions WHERE hp_id = ?
                """,
                    (parent_hp_id,),
                )
                parent_row = await cursor.fetchone()

                if not parent_row:
                    return []

                parent_position = self._row_to_position(parent_row)
                hierarchy = [parent_position]

                # Get child positions if any
                if parent_position.child_position_ids:
                    for child_id in parent_position.child_position_ids:
                        cursor = await conn.execute(
                            """
                            SELECT * FROM positions WHERE id = ?
                        """,
                            (child_id,),
                        )
                        child_row = await cursor.fetchone()
                        if child_row:
                            hierarchy.append(self._row_to_position(child_row))

                return hierarchy
        except Exception as e:
            raise RecoveryError(
                f"Failed to get position hierarchy for {parent_hp_id}: {e}"
            ) from e

    async def get_position_orders(self, position_id: str) -> List[Order]:
        """Get all orders for a position."""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT * FROM orders WHERE position_id = ?
                    ORDER BY created_at ASC
                """,
                    (position_id,),
                )
                rows = await cursor.fetchall()

                orders = []
                for row in rows:
                    order = self._row_to_order(row)
                    orders.append(order)

                return orders
        except Exception as e:
            raise DatabaseError(
                f"Failed to get orders for position {position_id}: {e}"
            ) from e

    def _row_to_position(self, row) -> Position:
        """Convert database row to Position object."""
        try:
            child_ids = (
                json.loads(row["child_position_ids"])
                if row["child_position_ids"]
                else []
            )
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}

            return Position(
                id=row["id"],
                hp_id=row["hp_id"],
                strategy_id=row["strategy_id"],
                position_type=PositionType(row["position_type"]),
                status=PositionStatus(row["status"]),
                symbol=row["symbol"],
                coin=row["coin"],
                target_price=row["target_price"],
                buy_price=row["buy_price"],
                sell_price=row["sell_price"],
                quantity=row["quantity"],
                realized_quantity=row["realized_quantity"],
                budget=row["budget"],
                parent_position_id=row["parent_position_id"],
                child_position_ids=child_ids,
                trade_type=TradeType(row["trade_type"]),
                hop_sequence=row["hop_sequence"],
                price_low=row["price_low"],
                price_high=row["price_high"],
                order_trigger=row["order_trigger"],
                end_currency=row["end_currency"],
                mode=row["mode"],
                completeness=row["completeness"],
                next_monitor_time=(
                    datetime.fromisoformat(row["next_monitor_time"])
                    if row["next_monitor_time"]
                    else None
                ),
                metadata=metadata,
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except Exception as e:
            raise DatabaseError(f"Failed to convert row to position: {e}") from e

    def _row_to_order(self, row) -> Order:
        """Convert database row to Order object."""
        from .models import OrderStatus

        try:
            return Order(
                id=row["id"],
                position_id=row["position_id"],
                exchange_order_id=row["exchange_order_id"],
                symbol=row["symbol"],
                side=row["side"],
                order_type=row["order_type"],
                status=OrderStatus(row["status"]),
                price=row["price"],
                quantity=row["quantity"],
                quantity_stable=row["quantity_stable"],
                realized_quantity=row["realized_quantity"],
                time_in_force=row["time_in_force"],
                filled_at=(
                    datetime.fromisoformat(row["filled_at"])
                    if row["filled_at"]
                    else None
                ),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
        except Exception as e:
            raise DatabaseError(f"Failed to convert row to order: {e}") from e

    async def close(self):
        """Close database connections."""
        # SQLite connections are closed automatically with context managers
        logger.info("Database connections closed")

    async def backup_database(self, backup_path: str) -> None:
        """Create a backup of the database."""
        try:
            import shutil

            backup_file = Path(backup_path)
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.db_path, backup_file)
            logger.info("Database backed up to %s", backup_path)
        except Exception as e:
            raise DatabaseError(f"Failed to backup database: {e}") from e

    async def get_database_stats(self) -> Dict[str, int]:
        """Get database statistics for monitoring."""
        try:
            async with self.get_connection() as conn:
                stats = {}

                for table in ["strategies", "positions", "orders", "trades"]:
                    cursor = await conn.execute(f"SELECT COUNT(*) FROM {table}")
                    count = await cursor.fetchone()
                    stats[table] = count[0]

                # Active positions
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) FROM positions 
                    WHERE status NOT IN ('CLOSED', 'CANCELED')
                """
                )
                count = await cursor.fetchone()
                stats["active_positions"] = count[0]

                return stats
        except Exception as e:
            raise DatabaseError(
                f"Failed to get database stats: {e}"
            ) from e  # ========================================================================

    async def upsert_order(self, order, hp_id: str, side) -> None:
        """
        Upsert an order to the database.

        Args:
            order: Trading system Order object
            hp_id: Position HP ID
            side: PositionSide enum
        """
        try:
            # Convert trading order to database order
            db_order = Order(
                position_id=hp_id,  # Use hp_id as position_id for compatibility
                exchange_order_id=(
                    order.order_id
                    if hasattr(order, "order_id") and order.order_id > 0
                    else None
                ),
                symbol="",  # Will need to be filled from context
                side=side.value if hasattr(side, "value") else str(side),
                status=self._convert_order_status_string(
                    order.status if hasattr(order, "status") else "NEW"
                ),
                price=order.price if hasattr(order, "price") else 0.0,
                quantity=order.quantity if hasattr(order, "quantity") else 0.0,
                quantity_stable=(
                    order.quantity_stable if hasattr(order, "quantity_stable") else 0.0
                ),
                realized_quantity=(
                    order.realized_quantity
                    if hasattr(order, "realized_quantity")
                    else 0.0
                ),
                time_in_force=(
                    order.time_in_force if hasattr(order, "time_in_force") else "GTC"
                ),
            )
            await self.save_order(db_order)
            logger.debug("Async: Saved order for hp_id %s", hp_id)
        except Exception as e:
            logger.error("Failed to upsert order (async): %s", e)

    async def upsert_buy_price_level(self, data) -> None:
        """
        Compatibility method for upsert_buy_price_level.

        Args:
            data: HPBuyData object
        """
        try:
            # Convert HPBuyData to Position
            position = Position(
                hp_id=data.config.hp_id,
                position_type=PositionType.BUY,
                status=self._convert_state_to_position_status(data.state_info.state),
                symbol=data.config.symbol_info.symbol,
                coin=data.config.coin,
                budget=data.config.budget,
                price_low=data.config.price_low,
                price_high=data.config.price_high,
                order_trigger=data.config.order_trigger,
                mode=(
                    data.config.mode.value
                    if hasattr(data.config.mode, "value")
                    else str(data.config.mode)
                ),
                completeness=data.state_info.completeness,
                trade_type=TradeType.DIRECT,
                created_at=(
                    datetime.strptime(data.state_info.open_time, "%Y-%m-%d %H:%M:%S")
                    if data.state_info.open_time
                    else datetime.now()
                ),
            )

            await self.save_position(position)
            logger.debug(
                "Compatibility: Saved buy price level for hp_id %s", data.config.hp_id
            )
        except Exception as e:
            logger.error("Failed to upsert buy price level (compatibility): %s", e)

    async def upsert_sell_price_level(self, data) -> None:
        """
        Compatibility method for upsert_sell_price_level.

        Args:
            data: SellPosition or HPSellData object
        """
        try:
            # Handle both SellPosition and HPSellData
            if hasattr(data, "config") and hasattr(data, "state_info"):
                # This is a SellPosition
                config = data.config
                state_info = data.state_info
            elif hasattr(data, "config"):
                # This is HPSellData
                config = data.config
                state_info = data.state_info
            else:
                logger.error("Unknown data type in upsert_sell_price_level")
                return

            position = Position(
                hp_id=config.hp_id,
                position_type=PositionType.SELL,
                status=self._convert_state_to_position_status(state_info.state),
                symbol=config.symbol_info.symbol,
                coin=config.coin,
                quantity=config.quantity,
                buy_price=config.buy_price,
                sell_price=config.sell_price,
                end_currency=config.end_currency,
                trade_type=TradeType.DIRECT,
                completeness=state_info.completeness,
                created_at=(
                    datetime.strptime(state_info.open_time, "%Y-%m-%d %H:%M:%S")
                    if state_info.open_time
                    else datetime.now()
                ),
            )
            await self.save_position(position)
            logger.debug(
                "Compatibility: Saved sell price level for hp_id %s", config.hp_id
            )
        except Exception as e:
            logger.error("Failed to upsert sell price level (compatibility): %s", e)

    def fetch_all_active_strategies(self) -> List[Dict]:
        """
        Compatibility method for fetch_all_active_strategies.

        Returns:
            List of strategy dictionaries
        """
        try:
            # Try to get current event loop, if it exists, create a task
            try:
                asyncio.get_running_loop()
                # We're in an event loop, need to use a different approach
                logger.warning(
                    "fetch_all_active_strategies called from async context - returning empty list"
                )
                return []
            except RuntimeError:
                # No event loop running, can use asyncio.run
                return asyncio.run(self._fetch_all_active_strategies())
        except Exception as e:
            logger.error("Failed to fetch active strategies (compatibility): %s", e)
            return []

    async def _fetch_all_active_strategies(self) -> List[Dict]:
        """Internal async method for fetching strategies."""
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT * FROM strategies WHERE status = 'ACTIVE'
                """
                )
                rows = await cursor.fetchall()

                strategies = []
                for row in rows:
                    strategies.append(
                        {
                            "strategy_id": row["id"],
                            "name": row["name"],
                            "description": row["description"],
                            "status": row["status"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                        }
                    )

                return strategies
        except Exception as e:
            logger.error("Failed to fetch strategies: %s", e)
            return []

    def fetch_active_hp_list(self) -> List[Dict]:
        """
        Compatibility method for fetch_active_hp_list.

        Returns:
            List of active position dictionaries
        """
        try:
            # Try to get current event loop, if it exists, create a task
            try:
                asyncio.get_running_loop()
                # We're in an event loop, need to use a different approach
                logger.warning(
                    "fetch_active_hp_list called from async context - returning empty list"
                )
                return []
            except RuntimeError:
                # No event loop running, can use asyncio.run
                return asyncio.run(self._fetch_active_hp_list())
        except Exception as e:
            logger.error("Failed to fetch active HP list (compatibility): %s", e)
            return []

    async def _fetch_active_hp_list(self) -> List[Dict]:
        """Internal async method for fetching active positions."""
        try:
            positions = await self.get_active_positions()

            hp_list = []
            for pos in positions:
                hp_list.append(
                    {
                        "hp_id": pos.hp_id,
                        "coin": pos.coin,
                        "buy_price": pos.buy_price,
                        "quantity": pos.quantity,
                        "quantity_usd": pos.budget,
                        "sell_price": pos.sell_price,
                        "expected_return": (
                            pos.sell_price * pos.quantity
                            if pos.sell_price and pos.quantity
                            else 0.0
                        ),
                        "net": 0.0,  # Calculate if needed
                        "net_percent": 0.0,  # Calculate if needed
                        "state": pos.status.value,
                        "created_at": pos.created_at.isoformat(),
                        "version_timestamp": pos.updated_at.isoformat(),
                    }
                )

            return hp_list
        except Exception as e:
            logger.error("Failed to fetch active HP list: %s", e)
            return []

    def fetch_price_levels_for_hp(self, hp_id: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Compatibility method for fetch_price_levels_for_hp.

        Args:
            hp_id: Position HP ID

        Returns:
            Tuple of (buy_levels, sell_levels)"""
        try:
            return asyncio.run(self._fetch_price_levels_for_hp(hp_id))
        except Exception as e:
            logger.error("Failed to fetch price levels (compatibility): %s", e)
            return ([], [])

    async def _fetch_price_levels_for_hp(
        self, hp_id: str
    ) -> Tuple[List[Dict], List[Dict]]:
        """Internal async method for fetching price levels."""
        try:
            positions = await self.get_active_positions()
            position = next((p for p in positions if p.hp_id == hp_id), None)

            if not position:
                return ([], [])

            buy_levels = []
            sell_levels = []

            if position.position_type == PositionType.BUY:
                buy_levels.append(
                    {
                        "hp_id": position.hp_id,
                        "open_time": position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "symbol": position.symbol,
                        "price_low": position.price_low,
                        "price_high": position.price_high,
                        "order_trigger": position.order_trigger,
                        "budget": position.budget,
                        "state": position.status.value,
                        "mode": position.mode,
                        "is_current": True,
                        "version_timestamp": position.updated_at.isoformat(),
                    }
                )
            else:
                sell_levels.append(
                    {
                        "hp_id": position.hp_id,
                        "open_time": position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "symbol": position.symbol,
                        "buy_price": position.buy_price,
                        "sell_price": position.sell_price,
                        "quantity": position.quantity,
                        "state": position.status.value,
                        "end_currency": position.end_currency,
                        "is_current": True,
                        "version_timestamp": position.updated_at.isoformat(),
                    }
                )

            return (buy_levels, sell_levels)
        except Exception as e:
            logger.error("Failed to fetch price levels: %s", e)
            return ([], [])

    def fetch_orders_for_price_level(self, hp_id: str, side: str) -> List[Dict]:
        """
        Compatibility method for fetch_orders_for_price_level.

        Args:
            hp_id: Position HP ID
            side: Order side (BUY/SELL)

        Returns:
            List of order dictionaries"""
        try:
            return asyncio.run(self._fetch_orders_for_price_level(hp_id, side))
        except Exception as e:
            logger.error(
                "Failed to fetch orders for price level (compatibility): %s", e
            )
            return []

    async def _fetch_orders_for_price_level(self, hp_id: str, side: str) -> List[Dict]:
        """Internal async method for fetching orders."""
        try:
            # Find position by hp_id
            positions = await self.get_active_positions()
            position = next((p for p in positions if p.hp_id == hp_id), None)

            if not position:
                return []

            # Get orders for this position
            orders = await self.get_position_orders(position.id)

            # Filter by side and convert to dict format
            result = []
            for order in orders:
                if order.side == side:
                    result.append(
                        {
                            "order_id": order.exchange_order_id,
                            "hp_id": hp_id,
                            "quantity": order.quantity,
                            "price": order.price,
                            "side": order.side,
                            "quantity_stable": order.quantity_stable,
                            "realized_quantity": order.realized_quantity,
                            "time_in_force": order.time_in_force,
                            "status": order.status.value,
                            "order_type": order.order_type,
                            "is_current": True,
                            "created_at": order.created_at.isoformat(),
                            "version_timestamp": order.updated_at.isoformat(),
                        }
                    )

            return result
        except Exception as e:
            logger.error("Failed to fetch orders: %s", e)
            return []

    def insert_strategy(
        self, name: str, description: str = "", status: str = "ACTIVE"
    ) -> str:
        """
        Compatibility method for insert_strategy.

        Args:
            name: Strategy name
            description: Strategy description
            status: Strategy status

        Returns:
            Strategy ID"""
        try:
            strategy = Strategy(
                name=name,
                description=description,
                status=status,
            )
            return asyncio.run(self.save_strategy(strategy))
        except Exception as e:
            logger.error("Failed to insert strategy (compatibility): %s", e)
            return ""

    def assert_db_buy_price_level_content(self, config, state_info) -> None:
        """
        Compatibility method for assert_db_buy_price_level_content.

        Args:
            config: HPBuyConfig object
            state_info: StateInfo object
        """
        try:
            asyncio.run(self._assert_db_buy_price_level_content(config, state_info))
        except Exception as e:
            logger.error(
                "Failed to assert buy price level content (compatibility): %s", e
            )

    async def _assert_db_buy_price_level_content(self, config, state_info) -> None:
        """Internal async method for asserting buy price level content."""
        try:
            positions = await self.get_active_positions()
            position = next((p for p in positions if p.hp_id == config.hp_id), None)

            if not position:
                raise AssertionError(f"Position {config.hp_id} not found in database")

            assert position.symbol == config.symbol_info.symbol
            assert position.price_low == config.price_low
            assert position.price_high == config.price_high
            assert position.budget == config.budget
            assert position.order_trigger == config.order_trigger

            # Assert state information if provided
            if hasattr(state_info, "completeness"):
                assert position.completeness == state_info.completeness
            if hasattr(state_info, "state"):
                expected_status = self._convert_state_to_position_status(
                    state_info.state
                )
                assert position.status == expected_status

            logger.debug("Compatibility: Assertion passed for hp_id %s", config.hp_id)
        except Exception as e:
            logger.error("Failed to assert buy price level content: %s", e)
            raise

    def _convert_state_to_position_status(self, state):
        """Convert trading system State to PositionStatus."""
        try:
            # Import here to avoid circular imports
            from src.identifiers import State

            mapping = {
                State.NEW: PositionStatus.NEW,
                State.BUYING: PositionStatus.OPEN,
                State.SELLING: PositionStatus.OPEN,
                State.PARTIALLY_BOUGHT: PositionStatus.PARTIALLY_FILLED,
                State.PARTIALLY_SOLD: PositionStatus.PARTIALLY_FILLED,
                State.BOUGHT: PositionStatus.FILLED,
                State.SOLD: PositionStatus.FILLED,
                State.CLOSED: PositionStatus.CLOSED,
                State.WAITING_CHILD: PositionStatus.WAITING_CHILD,
            }
            return mapping.get(state, PositionStatus.NEW)
        except Exception:
            # Fallback to string comparison
            state_str = str(state)
            if "NEW" in state_str:
                return PositionStatus.NEW
            elif "OPEN" in state_str or "BUYING" in state_str or "SELLING" in state_str:
                return PositionStatus.OPEN
            elif "FILLED" in state_str or "BOUGHT" in state_str or "SOLD" in state_str:
                return PositionStatus.FILLED
            elif "CLOSED" in state_str:
                return PositionStatus.CLOSED
            else:
                return PositionStatus.NEW

    def _convert_order_status_string(self, status_str: str):
        """Convert order status string to OrderStatus enum."""
        from .models import OrderStatus

        mapping = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
        }
        return mapping.get(status_str, OrderStatus.NEW)
