import asyncio
import datetime
import logging
import threading
import time
from typing import Dict, List, Optional
import uuid
import aiomysql

from src.identifiers.common import PositionSide
from src.identifiers.spot import (
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    Order,
    State,
    StateInfo,
)
from src.position_buy import HPPositionBuy

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

CREATE_BUY_PRICE_LEVELS_TABLE = """
CREATE TABLE IF NOT EXISTS buy_price_levels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hp_id INT NOT NULL,
    open_time VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
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

CREATE_SELL_PRICE_LEVELS_TABLE = """
CREATE TABLE IF NOT EXISTS sell_price_levels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hp_id INT NOT NULL,
    open_time VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    sell_price FLOAT NOT NULL,
    quantity FLOAT NOT NULL,
    state VARCHAR(20) NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    version_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

"""

CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id BIGINT NOT NULL,
    hp_id INT NOT NULL,
    quantity FLOAT NOT NULL,
    price FLOAT NOT NULL,
    side VARCHAR(20) NOT NULL,
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

# SQL for creating HP List table with the updated structure
CREATE_HPLIST_TABLE = """
CREATE TABLE IF NOT EXISTS hp_list (
    id INT AUTO_INCREMENT PRIMARY KEY,
    hp_id INT NOT NULL,
    asset VARCHAR(20) NOT NULL,
    buy_price FLOAT NOT NULL,
    quantity FLOAT NOT NULL,
    quantity_usdt FLOAT NOT NULL,
    sell_price FLOAT NOT NULL,
    expected_return FLOAT NOT NULL,
    net FLOAT DEFAULT 0.0, -- Added
    net_percent FLOAT DEFAULT 0.0, -- Added
    state VARCHAR(20) DEFAULT 'NEW', -- Added
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
            logger.info("async loop is none, sleep 0.1s")
            time.sleep(0.1)
        logger.info("async loop is OK")
        self.create_database_if_not_exists()
        self.create_pool()
        self.setup_tables()

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

    def run_task(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def create_pool(self):
        async def _create_pool():
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.name,
                autocommit=True,
            )

        return self.run_task(_create_pool())

    def close_pool(self):
        if self.pool:
            self.pool.close()

    def drop_database(self) -> None:
        async def _drop_database():
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
                        await cur.execute(f"DROP DATABASE IF EXISTS `{self.name}`;")
                        await cur.execute(
                            f"GRANT ALL PRIVILEGES ON {self.name}.* TO '{self.user}'@'localhost';"
                        )
                temp_pool.close()
                await temp_pool.wait_closed()
                logger.info("Database %s dropped successfully.", self.name)
            except aiomysql.Error as err:
                logger.error("Error creating database %s: %s", self.name, err)

        return self.run_task(_drop_database())

    def create_database_if_not_exists(self) -> None:
        async def _create_database_if_not_exists():
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

        return self.run_task(_create_database_if_not_exists())

    def setup_tables(self) -> None:
        async def _setup_tables():
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(CREATE_STRATEGIES_TABLE)
                    await cur.execute(CREATE_BUY_PRICE_LEVELS_TABLE)
                    await cur.execute(CREATE_SELL_PRICE_LEVELS_TABLE)
                    await cur.execute(CREATE_HPLIST_TABLE)
                    await cur.execute(CREATE_ORDERS_TABLE)

                    await conn.commit()

        return self.run_task(_setup_tables())

    def drop_tables(self) -> None:
        async def _drop_tables():
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DROP TABLE IF EXISTS strategies")
                    await cur.execute("DROP TABLE IF EXISTS buy_price_levels")
                    await cur.execute("DROP TABLE IF EXISTS buy_price_levels")
                    await cur.execute("DROP TABLE IF EXISTS orders")
                    await cur.execute("DROP TABLE IF EXISTS hp_list")

                    await conn.commit()

        return self.run_task(_drop_tables())

    def insert_strategy(self, name, description, status="ACTIVE") -> str:
        async def _insert_strategy(name, description, status="ACTIVE") -> str:
            assert self.pool
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

        return self.run_task(_insert_strategy(name, description, status))

    def upsert_hp_record(self, hp_record: Dict) -> None:
        async def _upsert_hp_record(hp_record: Dict):
            """
            Insert or update a record in the hp_list table.
            """
            query_check = "SELECT id FROM hp_list WHERE hp_id=%s"
            query_update = """
            UPDATE hp_list
            SET asset=%s, buy_price=%s, quantity=%s, quantity_usdt=%s, sell_price=%s, expected_return=%s, net=%s, net_percent=%s, state=%s, version_timestamp=CURRENT_TIMESTAMP
            WHERE hp_id=%s
            """
            query_insert = """
            INSERT INTO hp_list (hp_id, asset, buy_price, quantity, quantity_usdt, sell_price, expected_return, net, net_percent, state)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            assert self.pool
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query_check, (hp_record["hp_id"],))
                    exists = await cur.fetchone()

                    if exists:
                        await cur.execute(
                            query_update,
                            (
                                hp_record["asset"],
                                hp_record["buy_price"],
                                hp_record["quantity"],
                                hp_record["quantity_usdt"],
                                hp_record["sell_price"],
                                hp_record["expected_return"],
                                hp_record["net"],
                                hp_record["net_percent"],
                                hp_record["state"],
                                hp_record["hp_id"],
                            ),
                        )
                    else:
                        await cur.execute(
                            query_insert,
                            (
                                hp_record["hp_id"],
                                hp_record["asset"],
                                hp_record["buy_price"],
                                hp_record["quantity"],
                                hp_record["quantity_usdt"],
                                hp_record["sell_price"],
                                hp_record["expected_return"],
                                hp_record["net"],
                                hp_record["net_percent"],
                                hp_record["state"],
                            ),
                        )
                    await conn.commit()

        return self.run_task(_upsert_hp_record(hp_record=hp_record))

    def upsert_buy_price_level(self, data: HPBuyData) -> None:
        async def _upsert_price_level(
            data: HPBuyData,
        ) -> None:
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    config = data.config
                    state_info = data.state_info
                    # Check if a record with the same hp_id, side, and state already exists
                    await cur.execute(
                        "SELECT 1 FROM price_levels WHERE hp_id=%s AND side=%s LIMIT 1",
                        (config.hp_id, state_info.side.value),
                    )
                    existing_record = await cur.fetchone()

                    # If no such record exists, proceed with the update and insert
                    if existing_record:
                        # Mark the current record as not current
                        await cur.execute(
                            "UPDATE price_levels SET is_current=FALSE WHERE hp_id=%s AND side=%s AND is_current=TRUE",
                            (config.hp_id, state_info.side.value),
                        )

                    # Insert a new record with the updated values
                    version_timestamp = datetime.datetime.now().isoformat()
                    insert_query = """
                    INSERT INTO price_levels (
                        open_time, hp_id, symbol, side, mode, price_low, price_high, order_trigger, budget, state,
                        is_current, version_timestamp, stagnation_counter, next_monitor_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                    """
                    await cur.execute(
                        insert_query,
                        (
                            state_info.open_time,
                            config.hp_id,
                            config.symbol_info.symbol,
                            state_info.side.value,
                            config.mode.value,
                            config.price_low,
                            config.price_high,
                            config.order_trigger,
                            config.budget,
                            state_info.state.value,
                            version_timestamp,
                            state_info.stagnation_counter,
                            state_info.next_monitor_time,
                        ),
                    )
                    await conn.commit()

        return self.run_task(_upsert_price_level(data=data))

    def upsert_sell_price_level(self, data: HPSellData) -> None:
        async def _upsert_price_level(
            data: HPSellData,
        ) -> None:
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    config: HPSellConfig = data.config
                    state_info: StateInfo = data.state_info
                    # Check if a record with the same hp_id, side, and state already exists
                    await cur.execute(
                        "SELECT 1 FROM price_levels WHERE hp_id=%s AND side=%s LIMIT 1",
                        (config.hp_id, state_info.side.value),
                    )
                    existing_record = await cur.fetchone()

                    # If no such record exists, proceed with the update and insert
                    if existing_record:
                        # Mark the current record as not current
                        await cur.execute(
                            "UPDATE price_levels SET is_current=FALSE WHERE hp_id=%s AND side=%s AND is_current=TRUE",
                            (config.hp_id, state_info.side.value),
                        )

                    # Insert a new record with the updated values
                    version_timestamp = datetime.datetime.now().isoformat()
                    insert_query = """
                    INSERT INTO price_levels (
                        open_time, hp_id, symbol, side, buy_price, sell_price, quantity, end_currency, state,
                        is_current, version_timestamp, stagnation_counter, next_monitor_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s, %s)
                    """
                    await cur.execute(
                        insert_query,
                        (
                            state_info.open_time,
                            config.hp_id,
                            config.symbol_info.symbol,
                            state_info.side.value,
                            config.buy_price,
                            config.sell_price,
                            config.quantity,
                            config.end_currency,
                            state_info.state.value,
                            version_timestamp,
                            state_info.stagnation_counter,
                            state_info.next_monitor_time,
                        ),
                    )
                    await conn.commit()

        return self.run_task(_upsert_price_level(data=data))

    def upsert_order(self, order: Order, hp_id: str, side: PositionSide) -> None:
        async def _upsert_order(order: Order, hp_id: str, side: PositionSide) -> None:
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    # Mark the current order as not current
                    await cur.execute(
                        "UPDATE orders SET is_current=FALSE WHERE order_id=%s AND is_current=TRUE",
                        (order.order_id,),
                    )
                    # Insert a new record with the updated values
                    version_timestamp = datetime.datetime.now().isoformat()
                    insert_query = """
                    INSERT INTO orders (
                        order_id, hp_id, quantity, price, side, quantity_stable, realized_quantity, time_in_force, status, order_type, is_current, version_timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    """
                    await cur.execute(
                        insert_query,
                        (
                            order.order_id,
                            hp_id,
                            order.quantity,
                            order.price,
                            side.value,
                            order.quantity_stable,
                            order.realized_quantity,
                            order.time_in_force,
                            order.status,
                            order.order_type,
                            version_timestamp,
                        ),
                    )
                    await conn.commit()

        return self.run_task(_upsert_order(order=order, hp_id=hp_id, side=side))

    def fetch_active_hp_list(self) -> List[Dict]:
        async def _fetch_active_hp_list() -> List[Dict]:
            fetch_query = "SELECT * FROM hp_list WHERE state NOT IN ('CLOSED', 'SOLD')"
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(fetch_query)
                    records = await cur.fetchall()
                    return list(records)

        return self.run_task(_fetch_active_hp_list())

    def fetch_price_levels_for_hp(self, hp_id: str) -> List[Dict]:
        async def _fetch_price_levels_for_hp(hp_id: str) -> List[Dict]:
            """
            Fetch price levels for a given hp_id.
            """
            query = """
            SELECT *
            FROM price_levels
            WHERE hp_id = %s
            AND is_current = TRUE
            """
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(query, (hp_id,))
                    return await cur.fetchall()

        return self.run_task(_fetch_price_levels_for_hp(hp_id=hp_id))

    def fetch_orders_for_price_level(self, hp_id: str, side: str) -> List[Dict]:
        async def _fetch_orders_for_price_level(hp_id: str, side: str) -> List[Dict]:
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "SELECT * FROM orders WHERE hp_id=%s AND side=%s AND is_current=TRUE",
                        (hp_id, side),
                    )
                    result = await cur.fetchall()
                    return result

        return self.run_task(_fetch_orders_for_price_level(hp_id=hp_id, side=side))

    def fetch_all_active_strategies(self) -> List[Dict]:
        async def _fetch_all_active_strategies() -> List[Dict]:
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cur:
                    await cur.execute(
                        "SELECT * FROM strategies WHERE status = 'ACTIVE' AND is_current=TRUE"
                    )
                    result = await cur.fetchall()
                    return result

        return self.run_task(_fetch_all_active_strategies())

    def assert_db_buy_price_level_content(
        self, config: HPBuyConfig, state: State
    ) -> List[Dict]:
        async def _assert_db_price_level_content(config: HPBuyConfig, state: State):
            assert self.pool is not None
            async with self.pool.acquire() as conn:
                async with conn.cursor(aiomysql.cursors.DictCursor) as cur:
                    await cur.execute(
                        "SELECT * FROM price_levels WHERE price_level_id=%s AND is_current=TRUE",
                        (config.system_id,),
                    )
                    result = await cur.fetchone()

                    logger.info("Result: %s", result)
                    assert result is not None, "Price level not found in the database"
                    assert result.get("symbol") == config.symbol_info.symbol
                    assert result.get("side") == config.side.value
                    assert result.get("price_low") == config.price_low
                    assert result.get("price_high") == config.price_high
                    assert result.get("state") == state.value
                    assert result.get("budget") == config.budget
                    assert result.get("order_trigger") == config.order_trigger

        return self.run_task(_assert_db_price_level_content(config=config, state=state))
