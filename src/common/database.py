# database.py

from typing import Optional, Dict, List
import aiomysql

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
            host=self.host, port=self.port,
            user=self.user, password=self.password,
            db=self.db, autocommit=True
        )

    async def close_pool(self):
        self.pool.close()
        await self.pool.wait_closed()

    async def fetch_strategy(self, strategy_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT * FROM strategies WHERE id=%s", (strategy_id,))
                result = await cur.fetchone()
                return result

    async def create_strategy(self, name: str, description: str) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO strategies (name, description) VALUES (%s, %s)", (name, description))
                await conn.commit()

    async def create_order(self, strategy_id: int, type: str, amount: float, price: float) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO orders (strategy_id, type, amount, price) VALUES (%s, %s, %s, %s)", (strategy_id, type, amount, price))
                await conn.commit()

    async def save_strategy_state(self, strategy_name: str, state: Dict) -> None:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    REPLACE INTO strategy_states (strategy_name, state)
                    VALUES (%s, %s)
                    """,
                    (strategy_name, str(state))
                )
                await conn.commit()

    async def load_strategy_state(self, strategy_name: str) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT state FROM strategy_states WHERE strategy_name=%s", (strategy_name,)
                )
                result = await cur.fetchone()
                if result:
                    return eval(result['state'])
                return None

    async def fetch_all_strategy_states(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute("SELECT strategy_name, state FROM strategy_states")
                result = await cur.fetchall()
                return [{"strategy_name": row["strategy_name"], "state": eval(row["state"])} for row in result]
