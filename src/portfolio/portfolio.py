import asyncio
from collections import defaultdict
import csv
import logging
import os
import queue
import time
from typing import Any, Dict, List, Optional
import uuid
from src.database.trading_database import Database
from src.common.client import KrakenClient
from src.domain.enums import EventName, SubscriptionTarget, SubscriptionType
from src.domain.inventory import InventoryItem
from src.domain.orders import AccountPosition, AllTickers, Event, PriceUpdates
from src.domain.subscriptions import SubscriptionInfo
from src.broker import BrokerSpot
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.portfolio.inventory_manager import InventoryManager

logger = logging.getLogger(__name__)


class PortfolioManager:
    def __init__(
        self,
        broker: BrokerSpot,
        ui_queue: queue.Queue,
        price_resolver: UsdPriceResolver,
        db: Database,
        client: KrakenClient,
    ):
        self.client = client
        self.broker = broker
        self.ui_queue = ui_queue
        self.worker_queue: queue.Queue = queue.Queue()
        self.price_updates: Dict[str, float] = {}  # Store latest price updates
        self.btc_saldo = 0.0
        self.usd_saldo = 0.0
        self.price_resolver = price_resolver
        self.db = db
        self.inventory: List[InventoryItem] = []  # In-memory inventory
        self.inventory_manager = (
            InventoryManager()
        )  # Inventory manager for aggregations

        # Starting the async loop
        self.stop_event = asyncio.Event()
        # Asyncio event to signal when initialization is complete
        self.initialization_complete = asyncio.Event()

    async def initialize(self) -> None:
        """Load inventory and signal readiness. Must be awaited before run_loop()."""
        logger.info("PortfolioManager is initializing.")

        # Initialize portfolio inventory before starting the main loop
        await self.init_portfolio_source()

        # DEBUG: Validate inventory before sending to UI
        logger.debug(
            f"[PORTFOLIO DEBUG] About to send inventory to UI: {len(self.inventory)} items"
        )
        if hasattr(self, "inventory") and self.inventory:
            logger.debug(
                f"[PORTFOLIO DEBUG] Inventory exists with {len(self.inventory)} items"
            )
            for i, item in enumerate(self.inventory[:3]):  # Log first 3 items
                logger.debug(
                    f"[PORTFOLIO DEBUG] UI Send Item {i}: {item.coin} qty={item.quantity} price={item.buy_price}"
                )
        else:
            logger.warning(
                "[PORTFOLIO DEBUG] No inventory to send to UI - inventory is empty or None"
            )

        # Send initial inventory to UI
        ui_event = Event(
            name=EventName.PORTFOLIO_INVENTORY,
            content=self.inventory,
        )

        self.ui_queue.put_nowait(ui_event)
        logger.info(
            f"[PORTFOLIO DEBUG] Successfully sent portfolio inventory to UI queue: {len(self.inventory)} items"
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

    async def run_loop(self) -> None:
        """Main worker loop. Call after initialize()."""
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

    async def run(self) -> None:
        """Main portfolio manager loop (convenience wrapper)."""
        await self.initialize()
        await self.run_loop()

    def stop(self) -> None:
        """Gracefully stop the PortfolioManager."""
        logger.info("Stopping PortfolioManager...")

        # Set the stop event to notify the loop to exit
        self.stop_event.set()

        # Unsubscribe from the broker feeds
        self.broker.unsubscribe("PORTFOLIO")

        logger.info("PortfolioManager stopped.")

    async def init_portfolio_source(self) -> None:
        """Initialize portfolio from data sources in priority order: 1) Database, 2) CSV file."""
        try:
            # Priority 1: Use fetch_all_inventory_items for DB inventory retrieval
            db_items = await self.db.fetch_all_inventory_items()
            logger.debug(
                f"[PORTFOLIO DEBUG] Database query returned {len(db_items) if db_items else 0} items"
            )

            if db_items:
                # Convert dict items to InventoryItem objects
                self.inventory = [InventoryItem(**item) for item in db_items]
                self.inventory_manager.inventory = self.inventory  # Update the manager
                logger.info(
                    f"Portfolio loaded from database with {len(self.inventory)} items."
                )

                # Fetch current account balances from Binance to sync available/locked quantities
                await self._sync_account_balances_on_init()

                if len(self.inventory) == 0:
                    raise RuntimeError(
                        f"Database inventory should not be empty but got {len(self.inventory)} items"
                    )
                coin_summary = self.inventory_manager.get_coin_summary()
                if len(coin_summary) == 0:
                    raise RuntimeError(
                        f"Database coin_summary should not be empty but got {len(coin_summary)} coins"
                    )
                logger.debug(
                    f"[PORTFOLIO DEBUG] Database loaded coin_summary: {list(coin_summary.keys())}"
                )
            else:
                # Priority 2: Try to load from inventory.csv if database is empty
                logger.info("Database empty, checking for inventory.csv file.")
                if await self._try_load_inventory_csv():
                    logger.info("Portfolio loaded from inventory.csv file.")

                    # Fetch current account balances from Binance to sync available/locked quantities
                    await self._sync_account_balances_on_init()

                    if len(self.inventory) == 0:
                        raise RuntimeError(
                            f"CSV inventory should not be empty but got {len(self.inventory)} items"
                        )

                    # Validate InventoryManager state
                    coin_summary = self.inventory_manager.get_coin_summary()
                    if len(coin_summary) == 0:
                        raise RuntimeError(
                            f"CSV coin_summary should not be empty but got {len(coin_summary)} coins"
                        )
                    logger.info(
                        f"[PORTFOLIO DEBUG] Final coin_summary after CSV load: {list(coin_summary.keys())}"
                    )
                else:
                    # Priority 3: Start with empty inventory
                    logger.info(
                        "No inventory source found, starting with empty portfolio."
                    )
                    self.inventory = []

        except Exception as e:
            logger.error("Failed to initialize portfolio source: %s", e)
            self.inventory = []  # Fallback to empty inventory

        # Signal that initialization is complete
        self.initialization_complete.set()
        logger.info("Portfolio initialization completed - signaling readiness")

    async def _sync_account_balances_on_init(self) -> None:
        """Fetch account balances from Binance and sync with inventory on startup."""
        try:
            if self.client is None:
                logger.error("Cannot sync account balances: client not initialized")
                return

            logger.info("Fetching account balances from Binance for initial sync...")
            # TODO(PR4): KrakenClient.get_account not implemented yet.
            account_info = await self.client.get_account()  # type: ignore[attr-defined]

            # Extract balances from account info
            balances = account_info.get("balances", [])
            exchange_balances = {}

            for balance in balances:
                coin = balance["asset"]
                free = float(balance["free"])
                locked = float(balance["locked"])

                # Only track coins with non-zero balance
                if free > 0 or locked > 0:
                    exchange_balances[coin] = {"free": free, "locked": locked}

            logger.info(
                f"Fetched balances for {len(exchange_balances)} coins from exchange"
            )

            # Group inventory items by coin to calculate total quantities
            coin_lots: dict[str, list[InventoryItem]] = {}
            for item in self.inventory:
                if item.coin not in coin_lots:
                    coin_lots[item.coin] = []
                coin_lots[item.coin].append(item)

            # Update each coin's lots proportionally based on exchange balances
            for coin, lots in coin_lots.items():
                if coin in exchange_balances:
                    exchange_free = exchange_balances[coin]["free"]
                    exchange_locked = exchange_balances[coin]["locked"]
                    total_qty = sum(lot.quantity for lot in lots)

                    if total_qty > 0:
                        # Distribute available and locked proportionally across lots
                        for lot in lots:
                            proportion = lot.quantity / total_qty
                            lot.available_quantity = exchange_free * proportion
                            lot.locked_quantity = exchange_locked * proportion
                            logger.debug(
                                f"[INIT SYNC] {coin} lot (qty={lot.quantity}): "
                                f"available={lot.available_quantity:.8f}, locked={lot.locked_quantity:.8f}"
                            )
                    else:
                        logger.warning(
                            f"[INIT SYNC] {coin} has zero total quantity in inventory"
                        )
                else:
                    # Coin in inventory but not on exchange - zero out quantities
                    logger.warning(
                        f"[INIT SYNC] {coin} exists in inventory but not on exchange - "
                        f"zeroing available/locked quantities"
                    )
                    for lot in lots:
                        lot.available_quantity = 0.0
                        lot.locked_quantity = 0.0

            logger.info("Initial account balance sync completed")

        except Exception as e:
            logger.error(f"Failed to sync account balances on init: {e}")
            logger.warning(
                "Inventory available/locked quantities may be incorrect until first WebSocket update"
            )

    async def _try_load_inventory_csv(self) -> bool:
        """Try to load inventory from CSV file. Returns True if successful, False otherwise."""

        # Look for inventory.csv in the src/portfolio directory
        filename = os.path.join(os.path.dirname(__file__), "inventory.csv")
        if not os.path.exists(filename):
            logger.info("No inventory.csv file found at %s.", filename)
            return False

        try:
            with open(filename, "r", encoding="utf-8") as f:
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

                # CRITICAL FIX: Save CSV inventory to database for persistence
                logger.info("Saving CSV inventory to database for future recovery...")
                try:
                    for item in inventory_items:
                        await self.db.insert_inventory_item(item)
                    logger.info(
                        f"Successfully saved {len(inventory_items)} inventory items to database"
                    )
                except Exception as e:
                    logger.error("Failed to save CSV inventory to database: %s", e)
                    # Don't fail the load, but warn about recovery issues
                    logger.warning(
                        "Inventory will need to be reloaded from CSV after restart"
                    )

                # DEBUG: Add comprehensive debugging for inventory structure
                logger.debug(
                    f"[PORTFOLIO DEBUG] Total inventory items loaded: {len(inventory_items)}"
                )

                if len(inventory_items) == 0:
                    raise RuntimeError(
                        f"Inventory should not be empty but got {len(inventory_items)} items"
                    )

                # Debug first few items structure
                for i, item in enumerate(inventory_items[:5]):
                    logger.debug(
                        f"[PORTFOLIO DEBUG] Item {i}: coin={item.coin}, quantity={item.quantity}, buy_price={item.buy_price}"
                    )

                # Test InventoryManager aggregation
                coin_summary = self.inventory_manager.get_coin_summary()
                logger.debug(
                    f"[PORTFOLIO DEBUG] InventoryManager coin_summary: {coin_summary}"
                )

                if len(coin_summary) == 0:
                    raise RuntimeError(
                        f"InventoryManager coin_summary should not be empty but got {len(coin_summary)} coins"
                    )

                # Test specific coin aggregation
                for coin in list(coin_summary.keys())[:3]:  # Test first 3 coins
                    total_qty = self.inventory_manager.get_total_quantity_by_coin(coin)
                    avg_price = self.inventory_manager.get_weighted_average_price(coin)
                    logger.debug(
                        f"[PORTFOLIO DEBUG] Coin {coin}: total_qty={total_qty}, avg_price={avg_price}"
                    )

                    if total_qty <= 0:
                        raise RuntimeError(
                            f"Total quantity for {coin} should be > 0 but got {total_qty}"
                        )
                    if avg_price <= 0:
                        raise RuntimeError(
                            f"Average price for {coin} should be > 0 but got {avg_price}"
                        )

                logger.info(
                    "[PORTFOLIO DEBUG] All inventory validations passed successfully"
                )
                return True
            else:
                logger.warning("No valid inventory items found in CSV file.")
                return False

        except Exception as e:
            logger.error("Failed to load inventory CSV: %s", e)
            return False

    async def handle_account_position(self, account_position: AccountPosition) -> None:
        """Handle account position updates - sync exchange data to inventory."""
        logger.info("Syncing exchange balances to inventory")

        # Create a map of exchange balances for quick lookup
        exchange_balances = {
            balance.coin: balance for balance in account_position.balances
        }

        # Group inventory items by coin to calculate total quantities
        coin_lots: dict[str, list[InventoryItem]] = {}
        for item in self.inventory:
            if item.coin not in coin_lots:
                coin_lots[item.coin] = []
            coin_lots[item.coin].append(item)

        # Update each coin's lots proportionally based on exchange balances
        for coin, lots in coin_lots.items():
            if coin in exchange_balances:
                balance = exchange_balances[coin]
                total_qty = sum(lot.quantity for lot in lots)

                if total_qty > 0:
                    # Distribute available and locked proportionally across lots
                    for lot in lots:
                        old_available = lot.available_quantity
                        old_locked = lot.locked_quantity

                        proportion = lot.quantity / total_qty
                        lot.available_quantity = balance.free * proportion
                        lot.locked_quantity = balance.locked * proportion

                        # Log significant changes for debugging
                        if abs(old_available - lot.available_quantity) > 0.00001:
                            logger.debug(
                                "[EXCHANGE SYNC] %s lot (qty=%.8f) available: %.8f -> %.8f",
                                coin,
                                lot.quantity,
                                old_available,
                                lot.available_quantity,
                            )
                        if abs(old_locked - lot.locked_quantity) > 0.00001:
                            logger.debug(
                                "[EXCHANGE SYNC] %s lot (qty=%.8f) locked: %.8f -> %.8f",
                                coin,
                                lot.quantity,
                                old_locked,
                                lot.locked_quantity,
                            )
                else:
                    logger.warning(
                        f"[EXCHANGE SYNC] {coin} has zero total quantity in inventory"
                    )
            # Note: If coin is not in exchange_balances, we leave it unchanged
            # The AccountPosition message may only contain coins that changed,
            # not all coins, so we shouldn't zero out missing coins

        # Check for coins on exchange not in DB (optional warning for validation)
        for coin, balance in exchange_balances.items():
            total_on_exchange = balance.free + balance.locked
            if total_on_exchange > 0.001:  # Ignore dust amounts
                if not any(item.coin == coin for item in self.inventory):
                    logger.warning(
                        "[EXCHANGE SYNC] %s exists on exchange (free=%.8f, locked=%.8f) "
                        "but not in inventory DB - consider adding to inventory",
                        coin,
                        balance.free,
                        balance.locked,
                    )

        # Notify UI of updated inventory with exchange data
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

        # Also forward account position for other potential uses
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
            if not symbol:
                raise ValueError(f"Ticker dict missing required 's' key: {ticker}")
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

    async def update_inventory(self, new_inventory: List[InventoryItem]) -> None:
        """Update the inventory, update inventory manager, and notify the UI."""
        self.inventory = new_inventory
        self.inventory_manager.inventory = new_inventory  # Update the manager

        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    def add_inventory_item(self, item: InventoryItem) -> None:
        """Add a new inventory item and notify the UI."""
        self.inventory.append(item)
        self.inventory_manager.add_item(item)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    def remove_inventory_item(self, item_id: str) -> None:
        """Remove an inventory item by id and notify the UI."""
        self.inventory = [i for i in self.inventory if i.id != item_id]
        self.inventory_manager.remove_item(item_id)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def load_inventory_from_db(self, db: Any) -> None:
        """Load inventory from the database and update in-memory inventory, then notify UI."""
        items = await db.fetch_all_inventory_items()
        self.inventory = [InventoryItem(**item) for item in items]
        self.inventory_manager.inventory = self.inventory  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def add_inventory_item_db(self, db: Any, item: InventoryItem) -> None:
        """Add inventory item to DB and in-memory, then notify UI."""
        await db.insert_inventory_item(item)
        self.inventory.append(item)
        self.inventory_manager.add_item(item)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )

    async def update_inventory_item_db(self, db: Any, item: InventoryItem) -> None:
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

    async def remove_inventory_item_db(self, db: Any, item_id: str) -> None:
        """Remove inventory item from DB and in-memory, then notify UI."""
        await db.delete_inventory_item(item_id)
        self.inventory = [i for i in self.inventory if i.id != item_id]
        self.inventory_manager.remove_item(item_id)  # Update the manager
        self.ui_queue.put_nowait(
            Event(name=EventName.PORTFOLIO_INVENTORY, content=self.inventory)
        )
