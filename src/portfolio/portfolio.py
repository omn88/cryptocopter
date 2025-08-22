import asyncio
from collections import defaultdict
import csv
import logging
import os
import queue
import threading
import time
from typing import DefaultDict, Dict, List, Optional
import uuid
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
)
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.portfolio.inventory_manager import InventoryManager

# Specify the path to the .env file
DOTENV_FILE = "config/.env"
config_env = Config(RepositoryEnv(DOTENV_FILE))

logger = logging.getLogger("portfolio")


class PortfolioManager:
    def __init__(
        self,
        broker: BrokerSpot,
        ui_queue: queue.Queue,
        symbols_info: Dict[str, SymbolInfo],
        price_resolver: UsdPriceResolver,
        db: TradingDatabase,
    ):
        self.client: Optional[BinanceClient] = None
        self.broker = broker
        self.ui_queue = ui_queue
        self.worker_queue: queue.Queue = queue.Queue()
        self.price_updates: Dict[str, float] = {}  # Store latest price updates
        self.btc_saldo = 0.0
        self.usd_saldo = 0.0
        self.price_resolver = price_resolver
        self.symbols_info = symbols_info
        self.db = db
        self.inventory: List[InventoryItem] = []  # In-memory inventory
        self.inventory_manager = (
            InventoryManager()
        )  # Inventory manager for aggregations

        # Starting the async loop
        self.loop = asyncio.new_event_loop()
        self.stop_event = asyncio.Event()
        self.thread = threading.Thread(target=self.start_loop)
        self.thread.start()

    async def init_portfolio_source(self) -> None:
        """Initialize portfolio from data sources in priority order: 1) Database, 2) CSV file."""
        try:
            # Priority 1: Use fetch_all_inventory_items for DB inventory retrieval
            db_items = await self.db.fetch_all_inventory_items()
            if db_items:
                # Convert dict items to InventoryItem objects
                self.inventory = [InventoryItem(**item) for item in db_items]
                self.inventory_manager.inventory = self.inventory  # Update the manager
                logger.info(
                    f"Portfolio loaded from database with {len(self.inventory)} items."
                )
            else:
                # Priority 2: Try to load from inventory.csv if database is empty
                logger.info("Database empty, checking for inventory.csv file.")
                if await self._try_load_inventory_csv():
                    logger.info("Portfolio loaded from inventory.csv file.")
                else:
                    # Priority 3: Start with empty inventory
                    logger.info(
                        "No inventory source found, starting with empty portfolio."
                    )
                    self.inventory = []

        except Exception as e:
            logger.error(f"Failed to initialize portfolio source: {e}")
            self.inventory = []  # Fallback to empty inventory

    async def _try_load_inventory_csv(self) -> bool:
        """Try to load inventory from CSV file. Returns True if successful, False otherwise."""

        filename = "inventory.csv"
        if not os.path.exists(filename):
            logger.info("No inventory.csv file found in current directory.")
            return False

        try:
            with open(filename, "r") as f:
                reader = csv.DictReader(f)
                parsed = [row for row in reader]

            inventory_items = []
            for row in parsed:
                try:
                    item = InventoryItem(
                        id=str(uuid.uuid4()),
                        coin=row["coin"],
                        buy_price=float(row["buy_price"]),
                        quantity=float(row["quantity"]),
                        available_quantity=float(row["quantity"]),
                        locked_quantity=0.0,
                        source="CSV_IMPORT",
                        timestamp=time.time(),
                        notes="Imported from CSV",
                    )
                    inventory_items.append(item)
                except Exception as e:
                    logger.error("Failed to parse inventory row: %s error: %s", row, e)

            if inventory_items:
                self.inventory = inventory_items
                self.inventory_manager.inventory = self.inventory  # Update the manager
                logger.info(
                    f"Successfully loaded {len(inventory_items)} items from {filename}"
                )
                return True
            else:
                logger.warning("No valid inventory items found in CSV file.")
                return False

        except Exception as e:
            logger.error("Failed to load inventory CSV: %s", e)
            return False

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

        # Initialize portfolio inventory before starting the main loop
        await self.init_portfolio_source()

        # Send initial inventory to UI
        self.ui_queue.put_nowait(
            Event(
                name=EventName.PORTFOLIO_INVENTORY,
                content=self.inventory,
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
        """Handle account position updates (forward to UI only - inventory is managed separately)."""
        logger.info("Handling account position update - forwarding to UI.")

        # Simply forward the account position to UI
        # The inventory is managed separately through database operations
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

        # Calculate USD-equivalent prices for inventory coins
        inventory_coins = set(item.coin for item in self.inventory)
        for coin in inventory_coins:
            try:
                usd_price = self.price_resolver.resolve_usd(coin)
                self.price_updates[coin] = usd_price
            except ValueError:
                logger.info("Error finding price for coin: %s", coin)

        # Always include BTC price for reference
        try:
            usd_price = self.price_resolver.resolve_usd("BTC")
            self.price_updates["BTC"] = usd_price
        except ValueError:
            logger.info("Error finding BTC price")

        self.ui_queue.put(
            Event(
                name=EventName.PRICE_UPDATES,
                content=PriceUpdates(msg=self.price_updates),
            )
        )

    async def update_inventory(self, new_inventory: List[InventoryItem]):
        """Update the inventory, update inventory manager, and notify the UI."""
        self.inventory = new_inventory
        self.inventory_manager.inventory = new_inventory  # Update the manager

        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    def add_inventory_item(self, item: InventoryItem):
        """Add a new inventory item and notify the UI."""
        self.inventory.append(item)
        self.inventory_manager.add_item(item)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    def remove_inventory_item(self, item_id: str):
        """Remove an inventory item by id and notify the UI."""
        self.inventory = [i for i in self.inventory if i.id != item_id]
        self.inventory_manager.remove_item(item_id)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def load_inventory_from_db(self, db) -> None:
        """Load inventory from the database and update in-memory inventory, then notify UI."""
        items = await db.fetch_all_inventory_items()
        self.inventory = [InventoryItem(**item) for item in items]
        self.inventory_manager.inventory = self.inventory  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def add_inventory_item_db(self, db, item: InventoryItem) -> None:
        """Add inventory item to DB and in-memory, then notify UI."""
        await db.insert_inventory_item(item)
        self.inventory.append(item)
        self.inventory_manager.add_item(item)  # Update the manager
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
        self.inventory_manager.update_item(item)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def remove_inventory_item_db(self, db, item_id: str) -> None:
        """Remove inventory item from DB and in-memory, then notify UI."""
        await db.delete_inventory_item(item_id)
        self.inventory = [i for i in self.inventory if i.id != item_id]
        self.inventory_manager.remove_item(item_id)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )
