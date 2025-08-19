import asyncio
from collections import defaultdict
import logging
import queue
import threading
from typing import DefaultDict, Dict, List, Optional
from decouple import Config, RepositoryEnv
from src.common.symbol_info import SymbolInfo
from src.database.trading_database import TradingDatabase
from src.identifiers import (
    AccountPosition,
    AllTickers,
    Event,
    EventName,
    InventoryItem,
    PriceUpdates,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    BinanceClient,
    CoinBalance,
)
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver

# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))

logger = logging.getLogger("portfolio")


class PortfolioManager:
    def __init__(
        self,
        broker: BrokerSpot,
        ui_queue: queue.Queue,
        balances: Dict[str, CoinBalance],
        symbols_info: Dict[str, SymbolInfo],
        price_resolver: UsdPriceResolver,
        db: TradingDatabase,
    ):
        self.client: Optional[BinanceClient] = None
        self.broker = broker
        self.ui_queue = ui_queue
        self.worker_queue: queue.Queue = queue.Queue()
        self.balances = balances  # Dict[str, CoinBalance]
        self.price_updates: Dict[str, float] = {}  # Store latest price updates
        self.btc_saldo = 0.0
        self.usd_saldo = 0.0
        self.price_resolver = price_resolver
        self.symbols_info = symbols_info
        self.db = db
        self.inventory: List[InventoryItem] = []  # In-memory inventory

        # Starting the async loop
        self.loop = asyncio.new_event_loop()
        self.stop_event = asyncio.Event()
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()

    def start_loop(self) -> None:
        """Starts the asyncio loop in a new thread."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    async def run(self) -> None:
        """Main portfolio manager loop."""
        logger.info("PortfolioManager is running.")

        self.client = BinanceClient(
            api_key=config_env("API_KEY"), api_secret=config_env("API_SECRET")
        )
        self.ui_queue.put_nowait(
            Event(
                name=EventName.BALANCES,
                content=self.balances,
            )
        )

        # Subscribe to user and price updates for portfolio management
        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol="ALL",  # Subscribing to all symbols for user account positions
                target=SubscriptionTarget.PORTFOLIO,
                queue=self.worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id="PORTFOLIO",
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol="ALL",  # Subscribing to all symbols for price updates
                target=SubscriptionTarget.PORTFOLIO,
                queue=self.worker_queue,
            ),
        )

        while not self.stop_event.is_set():
            try:
                event = self.worker_queue.get_nowait()
                # logger.info("Portfolio go new event: %s", event)
                if event.name == EventName.ACCOUNT_POSITION:
                    await self.handle_account_position(event.content)
                elif event.name == EventName.ALL_TICKERS:
                    await self.handle_tickers(event.content)
                elif event.name == EventName.PORTFOLIO_INVENTORY:
                    await self.update_inventory(event.content)
            except queue.Empty:
                await asyncio.sleep(0.1)  # Sleep briefly to prevent busy waiting
                continue

        logger.info("PortfolioManager loop exiting.")

    def stop(self) -> None:
        """Gracefully stop the PortfolioManager."""
        logger.info("Stopping PortfolioManager...")

        # Set the stop event to notify the loop to exit
        self.stop_event.set()

        # Unsubscribe from the broker feeds
        self.broker.unsubscribe("PORTFOLIO")

        # Wait for the thread to finish
        if self.thread.is_alive():
            self.thread.join()

        logger.info("PortfolioManager stopped.")

    async def handle_account_position(self, account_position: AccountPosition) -> None:
        """Handle account position updates (update balances)."""
        logger.info("Handling account position update.")

        for balance in account_position.balances:
            coin = balance.coin
            free = balance.free
            locked = balance.locked
            total_balance = free + locked
            total_value = 0.0
            try:
                total_value = self.price_resolver.resolve_usd(coin) * total_balance
            except Exception:
                pass
            self.balances[coin] = CoinBalance(
                coin=coin,
                free=free,
                locked=locked,
                total=total_balance,
                total_value=total_value,
            )

        self.ui_queue.put_nowait(
            Event(name=EventName.ACCOUNT_POSITION, content=account_position)
        )

    async def handle_tickers(self, tickers_update: AllTickers) -> None:
        """Handle ticker updates to get latest prices."""
        tickers = tickers_update.msg
        if isinstance(tickers, dict):
            tickers = [tickers]
        elif isinstance(tickers, str):
            logging.debug("Received control frame: %s", tickers)
            return

        if not isinstance(tickers, list):
            logging.warning("Unexpected tickers format: %s", tickers)
            return

        for ticker in tickers_update.msg:
            symbol = ticker.get("s")
            assert symbol
            price = float(ticker.get("c", 0))
            # Update price map
            self.price_resolver.update_price(symbol, price)

        # Calculate USD-equivalent prices for known balances
        for coin in self.balances:
            try:
                usd_price = self.price_resolver.resolve_usd(coin)
                self.price_updates[coin] = usd_price

            except ValueError:
                logger.info("Errror to find price for coin: %s", coin)
        if "BTC" not in self.balances:
            usd_price = self.price_resolver.resolve_usd("BTC")
            self.price_updates["BTC"] = usd_price
        self.ui_queue.put(
            Event(
                name=EventName.PRICE_UPDATES,
                content=PriceUpdates(msg=self.price_updates),
            )
        )

    async def update_inventory(self, new_inventory: List[InventoryItem]):
        """Update the inventory, validate against balances, and notify the UI."""
        self.inventory = new_inventory

        # Sum inventory per coin
        inventory_sums: DefaultDict[str, float] = defaultdict(float)
        for item in self.inventory:
            inventory_sums[item.coin] += item.quantity

        for coin in set(list(inventory_sums.keys()) + list(self.balances.keys())):
            imported_sum = inventory_sums.get(coin, 0.0)

            portfolio_balance = self.balances.get(coin)
            if portfolio_balance is None:
                logger.warning("No balance found for coin: %s", coin)
                continue
            assert isinstance(portfolio_balance, CoinBalance)

            # Set tolerance: strict for BTC, ETH, BNB; relaxed (3) for others
            if coin in ("BTC", "ETH", "BNB"):
                tolerance = 1e-3
            else:
                tolerance = 3.0
            if abs(imported_sum - portfolio_balance.total) > tolerance:
                logger.warning(
                    "Discrepancy for %s: imported sum = %s, portfolio balance = %s",
                    coin,
                    imported_sum,
                    portfolio_balance.total,
                )
            else:
                logger.info(
                    "Imported inventory matches for %s: %s (portfolio: %s)",
                    coin,
                    imported_sum,
                    portfolio_balance.total,
                )

        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    def add_inventory_item(self, item: InventoryItem):
        """Add a new inventory item and notify the UI."""
        self.inventory.append(item)
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    def remove_inventory_item(self, item_id: str):
        """Remove an inventory item by id and notify the UI."""
        self.inventory = [i for i in self.inventory if i.id != item_id]
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def load_inventory_from_db(self, db) -> None:
        """Load inventory from the database and update in-memory inventory, then notify UI."""
        items = await db.fetch_all_inventory_items()
        self.inventory = [InventoryItem(**item) for item in items]
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def add_inventory_item_db(self, db, item: InventoryItem) -> None:
        """Add inventory item to DB and in-memory, then notify UI."""
        await db.insert_inventory_item(item)
        self.inventory.append(item)
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def update_inventory_item_db(self, db, item: InventoryItem) -> None:
        """Update inventory item in DB and in-memory, then notify UI."""
        await db.update_inventory_item(item)
        for idx, inv in enumerate(self.inventory):
            if inv.id == item.id:
                self.inventory[idx] = item
                break
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def remove_inventory_item_db(self, db, item_id: str) -> None:
        """Remove inventory item from DB and in-memory, then notify UI."""
        await db.delete_inventory_item(item_id)
        self.inventory = [i for i in self.inventory if i.id != item_id]
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )


async def fetch_initial_balances(
    client: BinanceClient, resolver: UsdPriceResolver
) -> Dict[str, CoinBalance]:
    """Fetch the initial balances from the exchange on startup and filter by value in USD."""
    logger.info("Fetching initial balances from the exchange.")
    balances: Dict[str, CoinBalance] = {}
    account_info = await client.get_account()

    for balance_info in account_info["balances"]:
        coin = balance_info["asset"]
        free = float(balance_info["free"])
        locked = float(balance_info["locked"])
        total_balance = free + locked
        if total_balance <= 0:
            continue
        try:
            price_in_usd = resolver.resolve_usd(coin)
            total_value = price_in_usd * total_balance
        except ValueError:
            total_value = 0.0
        if total_value >= 1.0:
            balances[coin] = CoinBalance(
                coin=coin,
                free=free,
                locked=locked,
                total=total_balance,
                total_value=total_value,
            )
        else:
            logger.debug("Skipping coin %s: only worth $%.2f", coin, total_value)

    logger.info("Initial balances fetched: %s", balances)
    return balances
