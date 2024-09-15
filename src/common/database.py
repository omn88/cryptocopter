import asyncio
import datetime
import logging
import threading
import time
from typing import Dict, List, Optional
import uuid
import aiomysql

from src.common.identifiers.spot import Order
from src.common.identifiers.spot import State, StrategyConfig

logger = logging.getLogger("database")


# SQL Statements
CREATE_STRATEGIES_TABLE = """
CREATE TABLE IF NOT EXISTS strategies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    strategy_id CHAR(36) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status ENUM('ACTIVE', 'CLOSED') NOT NULL DEFAULT 'ACTIVE',
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    version_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PRICE_LEVELS_TABLE = """
CREATE TABLE IF NOT EXISTS price_levels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    open_time VARCHAR(20) NOT NULL,
    price_level_id CHAR(36) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    price_low FLOAT NOT NULL,
    price_high FLOAT NOT NULL,
    order_trigger FLOAT NOT NULL,
    budget FLOAT NOT NULL,
    state VARCHAR(20) NOT NULL,
    mode VARCHAR(10) NOT NULL,
    stagnation_counter INT NOT NULL DEFAULT 0,
    next_monitor_time VARCHAR(20) NOT NULL DEFAULT '1970-01-01 00:00:00',
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    version_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

"""

CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    price_level_id CHAR(36) NOT NULL,
    quantity FLOAT NOT NULL,
    price FLOAT NOT NULL,
    quantity_stable FLOAT NOT NULL,
    realized_quantity FLOAT NOT NULL,
    time_in_force VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL,
    order_type VARCHAR(10) NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    version_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, host: str, port: int, user: str, password: str, name: str):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.name = name
        self.pool = None
        self.loop = None
        self.thread: Optional[threading.Thread] = None

    async def initialize(self) -> None:
        self.thread = threading.Thread(target=self.run_worker)
        self.thread.start()
        while self.loop is None:
            logger.info("loop is none, sleep 0.1s")
            time.sleep(0.1)
        logger.info("loop is OK")
        await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(
                self.create_database_if_not_exists(), self.loop
            )
        )

        await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(self.create_pool(), self.loop)
        )

    def run_worker(self):
        """Sets up the event loop for this thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop_worker(self):
        logger.info("DB: Stop the event loop and join the thread")
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not None:
            self.thread.join()
            logger.info("DB thread finished")

    def run_db_task(self, coro):
        """Runs a coroutine in the worker's event loop."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    async def create_pool(self):
        self.pool = await aiomysql.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.name,
            autocommit=True,
        )

    async def close_pool(self):
        self.pool.close()
        await self.pool.wait_closed()

    async def create_database_if_not_exists(self):
        try:
            logger.debug(
                "Will setup pool with config: host %s, port %s, user %s, pass %s",
                self.host,
                self.port,
                self.user,
                self.password,
            )
            temp_pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                autocommit=True,
            )
            logger.debug("Pool created")
            async with temp_pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(f"CREATE DATABASE IF NOT EXISTS {self.name};")
                    await cur.execute(
                        f"GRANT ALL PRIVILEGES ON {self.name}.* TO '{self.user}'@'localhost';"
                    )
            temp_pool.close()
            await temp_pool.wait_closed()
            logger.info("Database %s checked/created successfully.", self.name)
        except aiomysql.Error as err:
            logger.error("Error creating database %s: %s", self.name, err)

    async def setup_tables(self):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(CREATE_STRATEGIES_TABLE)
                await cur.execute(CREATE_PRICE_LEVELS_TABLE)
                await cur.execute(CREATE_ORDERS_TABLE)

                await conn.commit()

    async def drop_tables(self):
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("DROP TABLE IF EXISTS strategies")
                await cur.execute("DROP TABLE IF EXISTS price_levels")
                await cur.execute("DROP TABLE IF EXISTS orders")
                await conn.commit()

    async def insert_strategy(self, name, description, status="ACTIVE"):
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                strategy_id = str(uuid.uuid4())
                insert_query = """
                INSERT INTO strategies (strategy_id, name, description, status)
                VALUES (%s, %s, %s, %s)
                """
                await cur.execute(
                    insert_query, (strategy_id, name, description, status)
                )
                await conn.commit()
                logger.info("Inserted strategy with ID: %s", strategy_id)
                return strategy_id

    async def insert_order(self, price_level_id: str, order: Order) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO orders (order_id, price_level_id, quantity, price, quantity_stable, realized_quantity, time_in_force, status, order_type) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        order.order_id,
                        price_level_id,
                        order.quantity,
                        order.price,
                        order.quantity_stable,
                        order.realized_quantity,
                        order.time_in_force,
                        order.status,
                        order.order_type,
                    ),
                )
                await conn.commit()

    async def insert_price_level(self, config: StrategyConfig, state: State) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO price_levels (open_time, price_level_id, symbol, side, price_low, price_high, order_trigger, budget, state, mode) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        config.open_time,
                        config.system_id,
                        config.symbol_info.symbol,
                        config.side.value,
                        config.price_low,
                        config.price_high,
                        config.order_trigger,
                        config.budget,
                        state.value,
                        config.mode.value,
                    ),
                )
                await conn.commit()

    async def fetch_all_active_strategies(self) -> List[Dict]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM strategies WHERE status = 'ACTIVE' AND is_current=TRUE"
                )
                result = await cur.fetchall()
                return result

    async def fetch_all_active_price_levels(self) -> List[Dict]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                SELECT * FROM price_levels
                WHERE state IN ('NEW', 'OPEN', 'STAGNATED') AND is_current=TRUE
                """
                await cur.execute(query)
                result = await cur.fetchall()
                return result

    async def fetch_orders_for_price_level(self, price_level_id: str) -> List[Dict]:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT * FROM orders WHERE price_level_id=%s AND is_current=TRUE",
                    price_level_id,
                )
                result = await cur.fetchall()
                return result

    async def update_price_level(
        self,
        config: StrategyConfig,
        state: State,
        stagnation_counter: int,
        next_monitor_time: str,
    ) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Mark the current record as not current
                await cur.execute(
                    "UPDATE price_levels SET is_current=FALSE WHERE price_level_id=%s AND is_current=TRUE",
                    (config.system_id,),
                )
                # Insert a new record with the updated values
                version_timestamp = datetime.datetime.now().isoformat()
                insert_query = """
                INSERT INTO price_levels (
                    open_time, price_level_id, symbol, side, mode, price_low, price_high, order_trigger, budget, state, is_current, version_timestamp, stagnation_counter, next_monitor_time
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                """
                await cur.execute(
                    insert_query,
                    (
                        config.open_time,
                        config.system_id,
                        config.symbol_info.symbol,
                        config.side.value,
                        config.mode.value,
                        config.price_low,
                        config.price_high,
                        config.order_trigger,
                        config.budget,
                        state.value,
                        version_timestamp,
                        stagnation_counter,
                        next_monitor_time,
                    ),
                )
                await conn.commit()

    async def update_order(
        self,
        order_id: int,
        price_level_id: str,
        quantity: float,
        price: float,
        quantity_stable: float,
        realized_quantity: float,
        time_in_force: str,
        status: str,
        order_type: str,
    ) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Mark the current order as not current
                await cur.execute(
                    "UPDATE orders SET is_current=FALSE WHERE price_level_id=%s AND is_current=TRUE AND price=%s",
                    (price_level_id, price),
                )
                # Insert a new record with the updated values
                version_timestamp = datetime.datetime.now().isoformat()
                insert_query = """
                INSERT INTO orders (
                    order_id, price_level_id, quantity, price, quantity_stable, realized_quantity, time_in_force, status, order_type, is_current, version_timestamp
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                """
                await cur.execute(
                    insert_query,
                    (
                        order_id,
                        price_level_id,
                        quantity,
                        price,
                        quantity_stable,
                        realized_quantity,
                        time_in_force,
                        status,
                        order_type,
                        version_timestamp,
                    ),
                )
                await conn.commit()
