# database.py

from typing import Optional, Dict, List
import aiomysql

from src.common.identifiers.common import Order
from src.common.identifiers.spot import Position, StrategyConfig


# SQL Statements
CREATE_STRATEGIES_TABLE = """
CREATE TABLE IF NOT EXISTS strategies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    strategy_id INT,
    quantity FLOAT NOT NULL,
    price FLOAT NOT NULL,
    quantity_stable FLOAT NOT NULL,
    order_id INT NOT NULL,
    realized_quantity FLOAT NOT NULL,
    open_time TIMESTAMP,
    time_in_force VARCHAR(10) NOT NULL,
    status VARCHAR(10) NOT NULL,
    order_type VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id)
);
"""

CREATE_STRATEGY_STATES_TABLE = """
CREATE TABLE IF NOT EXISTS strategy_states (
    strategy_id INT PRIMARY KEY,
    state TEXT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id)
);
"""

CREATE_PRICE_LEVELS_TABLE = """
CREATE TABLE IF NOT EXISTS price_levels (
    system_id VARCHAR(36) PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price_low FLOAT NOT NULL,
    price_high FLOAT NOT NULL,
    order_trigger FLOAT NOT NULL,
    budget FLOAT NOT NULL
);
"""

CREATE_POSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS positions (
    id VARCHAR(36) PRIMARY KEY,
    symbol VARCHAR(10) NOT NULL,
    quantity FLOAT NOT NULL,
    state VARCHAR(10) NOT NULL,
    side VARCHAR(10) NOT NULL,
    status VARCHAR(10) NOT NULL,
    opened BOOLEAN NOT NULL,
    strategy_id INT,
    FOREIGN KEY (strategy_id) REFERENCES strategies(id)
);
"""


class Database:
    def __init__(self, host: str, port: int, user: str, password: str, db: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.db = db
        self.pool = None

    async def create_pool(self):
        self.pool = await aiomysql.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.db,
            autocommit=True,
        )

    async def close_pool(self):
        self.pool.close()
        await self.pool.wait_closed()

    async def setup_tables(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(CREATE_STRATEGIES_TABLE)
                await cur.execute(CREATE_ORDERS_TABLE)
                await cur.execute(CREATE_STRATEGY_STATES_TABLE)
                await cur.execute(CREATE_PRICE_LEVELS_TABLE)
                await cur.execute(CREATE_POSITIONS_TABLE)
                await conn.commit()

    async def fetch_strategy(self, strategy_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM strategies WHERE id=%s", (strategy_id,)
                )
                result = await cur.fetchone()
                return result

    async def create_strategy(self, name: str, description: str) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO strategies (name, description) VALUES (%s, %s)",
                    (name, description),
                )
                await conn.commit()

    async def create_order(self, strategy_id: int, order: Order) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO orders (strategy_id, quantity, price, quantity_stable, order_id, realized_quantity, open_time, time_in_force, status, order_type) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        strategy_id,
                        order.quantity,
                        order.price,
                        order.quantity_stable,
                        order.order_id,
                        order.realized_quantity,
                        order.open_time,
                        order.time_in_force,
                        order.status,
                        order.order_type,
                    ),
                )
                await conn.commit()

    async def save_strategy_state(self, strategy_id: int, state: Dict) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "REPLACE INTO strategy_states (strategy_id, state) VALUES (%s, %s)",
                    (strategy_id, str(state)),
                )
                await conn.commit()

    async def load_strategy_state(self, strategy_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT state FROM strategy_states WHERE strategy_id=%s",
                    (strategy_id,),
                )
                result = await cur.fetchone()
                if result:
                    return eval(result["state"])
                return None

    async def fetch_all_strategy_states(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT strategy_id, state FROM strategy_states")
                result = await cur.fetchall()
                return [
                    {"strategy_id": row["strategy_id"], "state": eval(row["state"])}
                    for row in result
                ]

    async def create_price_level(self, config: StrategyConfig) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO price_levels (system_id, symbol, side, price_low, price_high, order_trigger, budget) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        config.system_id,
                        config.symbol,
                        config.side,
                        config.price_low,
                        config.price_high,
                        config.order_trigger,
                        config.budget,
                    ),
                )
                await conn.commit()

    async def create_position(self, position: Position, strategy_id: int) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO positions (id, symbol, quantity, state, side, status, opened, strategy_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        position.id,
                        position.symbol,
                        position.quantity,
                        position.state,
                        position.side,
                        position.status,
                        position.opened,
                        strategy_id,
                    ),
                )
                await conn.commit()
