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
from typing import List, Dict, Tuple, Any, AsyncGenerator, Union
from datetime import datetime
import json
from contextlib import asynccontextmanager
import asyncio
import aiosqlite

from src.identifiers import (
    HPSellConfig,
    SellType,
    State,
    HPBuyData,
    HPSellData,
    SellPosition,
    HPBuyConfig,
    StateInfo,
)

from .models import (
    OrderStatus,
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
    async def delete_position(self, hp_id: str) -> None:
        """Delete a position from the database by hp_id."""
        try:
            async with self.get_connection() as conn:
                await conn.execute("DELETE FROM positions WHERE hp_id = ?", (hp_id,))
                await conn.commit()
                logger.info(f"Deleted position with hp_id: {hp_id}")
        except Exception as e:
            logger.error(f"Failed to delete position {hp_id}: {e}")

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
        )  # Positions table - the core of our recovery system
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                hp_id TEXT NOT NULL UNIQUE,
                strategy_id TEXT,
                position_type TEXT NOT NULL,
                status TEXT NOT NULL,
                strategy_state TEXT NOT NULL DEFAULT 'NEW',
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
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
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
        Uses hp_id as the unique identifier to prevent duplicates.
        """
        try:
            async with self.get_connection() as conn:
                # Use hp_id as the primary key to prevent duplicates
                position_id = position.hp_id

                await conn.execute(
                    """
                    INSERT OR REPLACE INTO positions 
                    (id, hp_id, strategy_id, position_type, status, strategy_state, symbol, coin,
                     target_price, buy_price, sell_price, quantity, realized_quantity, budget,
                     parent_position_id, child_position_ids, trade_type, hop_sequence,
                     price_low, price_high, order_trigger, end_currency, mode,
                     completeness, next_monitor_time, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        position_id,  # Use hp_id as the primary key
                        position.hp_id,
                        position.strategy_id,
                        position.position_type.value,
                        position.status.value,
                        position.strategy_state,
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
                return position_id
        except Exception as e:
            raise DatabaseError(f"Failed to save position {position.hp_id}: {e}") from e

    async def save_order(self, order: Order) -> str:
        """Save an order to the database."""
        try:
            async with self.get_connection() as conn:
                # Defensive: handle None for created_at and updated_at
                created_at = None
                updated_at = None
                if hasattr(order, "created_at") and order.created_at is not None:
                    try:
                        created_at = order.created_at.isoformat()
                    except Exception:
                        created_at = datetime.now().isoformat()
                else:
                    created_at = datetime.now().isoformat()

                if hasattr(order, "updated_at") and order.updated_at is not None:
                    try:
                        updated_at = order.updated_at.isoformat()
                    except Exception:
                        updated_at = datetime.now().isoformat()
                else:
                    updated_at = datetime.now().isoformat()

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
                        created_at,
                        updated_at,
                    ),
                )
                await conn.commit()
                return order.id
        except Exception as e:
            raise DatabaseError(f"Failed to save order: {e}") from e

    async def get_active_positions(self) -> List[Position]:
        """
        Get all active parent positions for recovery.

        Only returns parent positions (hop_sequence == 0 and parent_position_id is NULL or '').
        Child hops are not returned here.
        """
        try:

            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT * FROM positions
                    WHERE status NOT IN ('CLOSED', 'CANCELED')
                      AND (parent_position_id IS NULL OR parent_position_id = '')
                      AND hop_sequence = 0
                      AND hp_id NOT LIKE '%a'
                      AND hp_id NOT LIKE '%b'
                    ORDER BY created_at ASC
                    """
                )
                rows = await cursor.fetchall()

                positions = []
                for row in rows:
                    position = self._row_to_position(row)
                    positions.append(position)

                logger.info(
                    "Retrieved %s active parent positions for recovery", len(positions)
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

    def _row_to_position(self, row: aiosqlite.Row) -> Position:
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
                strategy_state=row["strategy_state"],
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

    def _row_to_order(self, row: aiosqlite.Row) -> Order:
        """Convert database row to Order object."""

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

    async def close(self) -> None:
        """Close database connections."""
        # SQLite connections are closed automatically with context managers
        logger.info("Database connections closed")

    async def get_database_stats(self) -> Dict[str, int]:
        """Get database statistics for monitoring."""
        try:
            async with self.get_connection() as conn:
                stats = {}

                for table in ["strategies", "positions", "orders", "trades"]:
                    cursor = await conn.execute(f"SELECT COUNT(*) FROM {table}")
                    count = await cursor.fetchone()
                    stats[table] = count[0] if count else 0

                # Active positions
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) FROM positions 
                    WHERE status NOT IN ('CLOSED', 'CANCELED')
                """
                )
                count = await cursor.fetchone()
                stats["active_positions"] = count[0] if count else 0

                return stats
        except Exception as e:
            raise DatabaseError(f"Failed to get database stats: {e}") from e

    # ========================================================================
    # Modern async API - Clean interface for the trading system
    # ========================================================================

    async def upsert_order(self, order: Any, hp_id: str, side: Any) -> None:
        """
        Save an order to the database.

        Args:
            order: Trading system Order object
            hp_id: Position HP ID
            side: PositionSide enum
        """
        try:
            # Get the position to extract the symbol
            positions = await self.get_active_positions()
            position = next((p for p in positions if p.hp_id == hp_id), None)
            symbol = position.symbol if position else ""

            # Always preserve the original order.id if present, else fallback to uuid
            db_order_id = getattr(order, "id", None)
            if not db_order_id:
                # fallback: use exchange_order_id or generate new
                db_order_id = str(getattr(order, "order_id", ""))

            # Ensure created_at and updated_at are always datetime objects
            import datetime as _dt

            created_at = getattr(order, "created_at", None)
            if not created_at:
                created_at = _dt.datetime.now()
            updated_at = getattr(order, "updated_at", None)
            if not updated_at:
                updated_at = _dt.datetime.now()

            db_order = Order(
                id=db_order_id,
                position_id=hp_id,  # Use hp_id as position_id for compatibility
                exchange_order_id=(
                    order.order_id
                    if hasattr(order, "order_id") and order.order_id > 0
                    else None
                ),
                symbol=symbol,
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
                created_at=created_at,
                updated_at=updated_at,
            )
            logger.info(
                f"[DB UPSERT] Saving order: id={db_order.id}, hp_id={hp_id}, side={db_order.side}, status={db_order.status}, symbol={db_order.symbol}, realized_quantity={db_order.realized_quantity}"
            )
            await self.save_order(db_order)
            logger.debug("Saved order for hp_id %s", hp_id)
        except Exception as e:
            logger.error("Failed to upsert order: %s", e)

    async def upsert_buy_price_level(
        self, data: HPBuyData, strategy_state: Any = None
    ) -> None:
        """
        Save buy position data to the database.

        Args:
            data: HPBuyData object
            strategy_state: Optional strategy state to use for strategy_state field
        """
        try:
            # Convert HPBuyData to Position
            position = Position(
                hp_id=data.config.hp_id,
                position_type=PositionType.BUY,
                status=self._convert_state_to_position_status(data.state_info.state),
                strategy_state=(
                    strategy_state.value
                    if hasattr(strategy_state, "value") and strategy_state is not None
                    else (
                        str(strategy_state)
                        if strategy_state is not None
                        else (
                            data.state_info.state.value
                            if hasattr(data.state_info.state, "value")
                            else str(data.state_info.state)
                        )
                    )
                ),
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
            logger.debug("Saved buy price level for hp_id %s", data.config.hp_id)
        except Exception as e:
            logger.error("Failed to upsert buy price level: %s", e)

    async def upsert_sell_price_level(
        self, data: SellPosition, strategy_state: State
    ) -> None:
        """
        Save sell position data to the database.

        Args:
            data: SellPosition or HPSellData object
            strategy_state: Optional strategy state
        """
        try:

            config: HPSellConfig = data.config
            state_info: StateInfo = data.state_info

            position = Position(
                hp_id=config.hp_id,
                position_type=PositionType.SELL,
                status=self._convert_state_to_position_status(state_info.state),
                strategy_state=(
                    strategy_state.value
                    if hasattr(strategy_state, "value") and strategy_state is not None
                    else (
                        str(strategy_state)
                        if strategy_state is not None
                        else (
                            state_info.state.value
                            if hasattr(state_info.state, "value")
                            else str(state_info.state)
                        )
                    )
                ),
                symbol=config.symbol_info.symbol,
                coin=config.coin,
                quantity=config.quantity,
                buy_price=config.buy_price,
                sell_price=config.sell_price,
                end_currency=config.end_currency,
                trade_type=(
                    TradeType.DIRECT
                    if data.sell_type == SellType.DIRECT
                    else (
                        TradeType.TWOHOP
                        if data.sell_type == SellType.TWOHOPS
                        else TradeType.CONVERT
                    )
                ),
                completeness=state_info.completeness,
                created_at=(
                    datetime.strptime(state_info.open_time, "%Y-%m-%d %H:%M:%S")
                    if state_info.open_time
                    else datetime.now()
                ),
            )
            await self.save_position(position)
            logger.debug("Saved sell price level for hp_id %s", config.hp_id)
        except Exception as e:
            logger.error("Failed to upsert sell price level: %s", e)

    async def get_orders_by_position_id(self, position_id: str) -> List[Order]:
        """
        Get all orders for a position by position ID.

        Args:
            position_id: The position ID

        Returns:
            List of orders for the position
        """
        return await self.get_position_orders(position_id)

    # ========================================================================
    # Legacy compatibility methods - To be implemented via TDD
    # ========================================================================

    async def fetch_all_active_strategies(self) -> List[Dict[str, Any]]:
        """
        Fetch all active strategies (async).

        Returns:
            List of strategy dictionaries
        """
        try:
            async with self.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT * FROM strategies WHERE status = 'ACTIVE' ORDER BY created_at ASC
                    """
                )
                rows = await cursor.fetchall()
                strategies = []
                for row in rows:
                    strategies.append(
                        {
                            "id": row["id"],
                            "name": row["name"],
                            "description": row["description"],
                            "status": row["status"],
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                        }
                    )
                logger.info("Fetched %d active strategies", len(strategies))
                return strategies
        except Exception as e:
            logger.error("Failed to fetch active strategies: %s", e)
            return []

    async def fetch_orders_for_price_level(
        self, hp_id: str, side: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch orders for a specific HP and side.

        Args:
            hp_id: Position HP ID
            side: Order side (BUY/SELL or LONG/SHORT)

        Returns:
            List of order dictionaries compatible with legacy format
        """
        try:
            async with self.get_connection() as conn:
                # First, get the position for this hp_id
                cursor = await conn.execute(
                    """
                    SELECT id FROM positions WHERE hp_id = ?
                    """,
                    (hp_id,),
                )
                position_row = await cursor.fetchone()

                if not position_row:
                    logger.info("No position found for hp_id: %s", hp_id)
                    return []

                position_id = position_row["id"]

                # Get orders for this position and side
                cursor = await conn.execute(
                    """
                    SELECT * FROM orders
                    WHERE position_id = ? AND side = ?
                    ORDER BY created_at ASC
                    """,
                    (position_id, side),
                )
                rows = await cursor.fetchall()

                # Convert to legacy format for compatibility
                orders = []
                for row in rows:
                    order_dict = {
                        "order_id": row["exchange_order_id"],
                        "quantity": row["quantity"],
                        "price": row["price"],
                        "quantity_stable": row["quantity_stable"],
                        "realized_quantity": row["realized_quantity"],
                        "status": row["status"],
                    }
                    orders.append(order_dict)

                logger.info(
                    "Found %d orders for HP %s, side %s", len(orders), hp_id, side
                )
                return orders

        except Exception as e:
            raise DatabaseError(
                f"Failed to fetch orders for HP {hp_id}, side {side}: {e}"
            ) from e

    # ========================================================================
    # Helper methods
    # ========================================================================

    def _convert_state_to_position_status(self, state: Any) -> PositionStatus:
        """Convert trading system State to PositionStatus."""
        try:

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

    def _convert_order_status_string(self, status_str: str) -> OrderStatus:
        """Convert order status string to OrderStatus enum."""

        mapping = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
        }
        return mapping.get(status_str, OrderStatus.NEW)
