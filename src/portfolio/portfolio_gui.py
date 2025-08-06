import asyncio
import os
import csv
import uuid
from collections import defaultdict
import logging
import queue
import time
from typing import Dict, List, Union
from kivy.properties import ListProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label

from src.identifiers import (
    AccountPosition,
    CoinBalance,
    Event,
    EventName,
    InventoryItem,
    PriceUpdates,
)
from src.common.symbol_info import SymbolInfo
from src.database import TradingDatabase

logger = logging.getLogger("portfolio_gui_handler")


logger = logging.getLogger("portfolio_ui")


class PortfolioUI(BoxLayout):
    virtual_positions = ListProperty([])
    saldo_usd_label = ObjectProperty(None)  # Label for USD saldo in the GUI
    saldo_btc_label = ObjectProperty(None)  # Label for BTC saldo in the GUI

    coin_list_data = ListProperty()

    def __init__(
        self,
        ui_queue: queue.Queue,
        symbols_info: Dict[str, SymbolInfo],
        db: TradingDatabase,
        balances: Dict[str, CoinBalance],
        **kwargs,
    ) -> None:
        # Initialize the base class (BoxLayout)
        super().__init__(**kwargs)  # This ensures proper widget initialization
        self.ui_queue = ui_queue
        self.symbols_info = symbols_info
        self.coin_list_data = []
        self.inventory: List[InventoryItem] = []
        self.db = db
        self.balances: Dict[str, CoinBalance] = balances
        self._last_refresh_time = 0.0  # Track last refresh time to throttle updates
        self.hp_manager = None  # Reference to HP manager for sell functionality
        self.app = None  # Reference to the main app for tab switching
        # On startup, check if DB is empty and choose data source
        try:
            asyncio.create_task(self.init_portfolio_source(balances=balances))
        except RuntimeError:
            # No event loop running (e.g., in tests), skip async initialization
            logger.warning("No event loop running, skipping async initialization")

    def set_hp_manager_reference(self, hp_manager, app):
        """Set reference to HP manager and main app for sell functionality."""
        self.hp_manager = hp_manager
        self.app = app

    def sell_lot_button(self, lot_symbol, quantity, buy_price):
        """Handle sell button for individual lot (child row)."""
        if not self.hp_manager or not self.app:
            logger.error(
                "HP Manager or App reference not set. Cannot navigate to sell tab."
            )
            return

        # Extract the parent symbol from the lot display
        # Find the parent coin this lot belongs to
        parent_symbol = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin.get("lots"):
                for lot in coin["lots"]:
                    if hasattr(lot, "quantity") and hasattr(lot, "buy_price"):
                        if str(lot.quantity) == str(quantity) and str(
                            lot.buy_price
                        ) == str(buy_price):
                            parent_symbol = coin["symbol"]
                            break
                if parent_symbol:
                    break

        if not parent_symbol:
            logger.error("Could not find parent symbol for lot")
            return

        # Switch to HP Manager tab
        hp_tab = self.app.strategies.get("HPManager")
        if hp_tab:
            self.app.root.switch_to(hp_tab)

            # Generate a lot ID (could be based on symbol + buy_price + quantity)
            lot_id = f"{parent_symbol}_{buy_price}_{quantity}"

            # Call HP manager's sell function with lot data
            self.hp_manager.sell_hp_button(lot_id, parent_symbol, quantity, buy_price)
            logger.info(f"Navigated to HP Manager sell tab for lot: {lot_id}")
        else:
            logger.error("HP Manager tab not found")

    def sell_parent_button(self, symbol):
        """Handle sell button for parent coin (allows partial or full sell)."""
        if not self.hp_manager or not self.app:
            logger.error(
                "HP Manager or App reference not set. Cannot navigate to sell tab."
            )
            return

        # Find the parent coin data
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin["symbol"] == symbol:
                parent_coin = coin
                break

        if not parent_coin:
            logger.error(f"Could not find parent coin data for {symbol}")
            return

        # Switch to HP Manager tab
        hp_tab = self.app.strategies.get("HPManager")
        if hp_tab:
            self.app.root.switch_to(hp_tab)

            # For parent sells, use the weighted average buy price and available quantity
            available_qty = parent_coin.get("available_qty", "0")
            avg_buy_price = parent_coin.get("weighted_avg_buy_price", 0.0)

            # Generate a parent sell ID
            parent_id = f"{symbol}_parent"

            # Call HP manager's sell function with parent data
            self.hp_manager.sell_hp_button(
                parent_id, symbol, available_qty, avg_buy_price
            )
            logger.info(f"Navigated to HP Manager sell tab for parent: {symbol}")
        else:
            logger.error("HP Manager tab not found")

    async def update_inventory_after_sell(
        self, symbol: str, quantity_sold: float, sell_from_lots: bool = True
    ):
        """Update inventory after a sell operation.

        Args:
            symbol: The coin symbol that was sold
            quantity_sold: The amount that was sold
            sell_from_lots: If True, sell from lowest buy price lots first (FIFO)
        """
        if sell_from_lots:
            # Update lots by selling from lowest buy price first (FIFO)
            await self._update_lots_after_sell(symbol, quantity_sold)
        else:
            # Update parent quantities directly (for exchange-based positions)
            await self._update_parent_after_sell(symbol, quantity_sold)

        # Refresh the UI to show updated quantities
        self._rebuild_coin_list_with_lots()

    async def _update_lots_after_sell(self, symbol: str, quantity_sold: float):
        """Update lots by selling from lowest buy price first (FIFO)."""
        # Find the parent coin
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin["symbol"] == symbol:
                parent_coin = coin
                break

        if not parent_coin or not parent_coin.get("lots"):
            logger.warning(f"No lots found for {symbol}")
            return

        # Sort lots by buy price (lowest first) for FIFO selling
        lots = parent_coin["lots"]
        lots.sort(
            key=lambda lot: (
                getattr(lot, "buy_price", 0)
                if hasattr(lot, "buy_price")
                else lot.get("buy_price", 0)
            )
        )

        remaining_to_sell = quantity_sold
        lots_to_remove = []

        for i, lot in enumerate(lots):
            if remaining_to_sell <= 0:
                break

            if hasattr(lot, "quantity"):  # InventoryItem object
                lot_quantity = lot.quantity
            else:  # Dictionary
                lot_quantity = lot.get("quantity", 0)

            if lot_quantity <= remaining_to_sell:
                # Sell entire lot
                remaining_to_sell -= lot_quantity
                lots_to_remove.append(i)

                # Remove from database if it's an InventoryItem
                if hasattr(lot, "id"):
                    try:
                        await self.db.delete_inventory_item(lot.id)
                        logger.info(f"Deleted lot {lot.id} from database")
                    except Exception as e:
                        logger.error(
                            f"Failed to delete lot {lot.id} from database: {e}"
                        )
            else:
                # Partial sell of this lot
                new_quantity = lot_quantity - remaining_to_sell
                if hasattr(lot, "quantity"):  # InventoryItem object
                    lot.quantity = new_quantity
                    lot.available_quantity = new_quantity

                    # Update in database
                    try:
                        await self.db.update_inventory_item(lot)
                        logger.info(f"Updated lot {lot.id} quantity to {new_quantity}")
                    except Exception as e:
                        logger.error(f"Failed to update lot {lot.id} in database: {e}")
                else:  # Dictionary
                    lot["quantity"] = new_quantity

                remaining_to_sell = 0

        # Remove sold lots (in reverse order to maintain indices)
        for i in reversed(lots_to_remove):
            lots.pop(i)

        # Update parent coin quantities
        total_remaining = sum(
            (
                getattr(lot, "quantity", 0)
                if hasattr(lot, "quantity")
                else lot.get("quantity", 0)
            )
            for lot in lots
        )
        parent_coin["quantity"] = str(total_remaining)

        # Recalculate weighted average buy price
        if lots:
            new_avg_price = self._calculate_weighted_average_buy_price(lots, symbol)
            parent_coin["buy_price"] = f"${new_avg_price}" if new_avg_price > 0 else "—"
            parent_coin["weighted_avg_buy_price"] = new_avg_price
        else:
            parent_coin["buy_price"] = "—"
            parent_coin["weighted_avg_buy_price"] = 0.0

        logger.info(
            f"Updated {symbol} after selling {quantity_sold}. Remaining quantity: {total_remaining}"
        )

    async def _update_parent_after_sell(self, symbol: str, quantity_sold: float):
        """Update parent coin quantities for exchange-based positions."""
        # Find the parent coin
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin["symbol"] == symbol:
                parent_coin = coin
                break

        if not parent_coin:
            logger.warning(f"Parent coin {symbol} not found")
            return

        # Update quantities
        current_quantity = float(parent_coin.get("quantity", 0))
        current_available = float(parent_coin.get("available_qty", 0))

        new_quantity = max(0, current_quantity - quantity_sold)
        new_available = max(0, current_available - quantity_sold)

        parent_coin["quantity"] = str(new_quantity)
        parent_coin["available_qty"] = str(new_available)

        logger.info(
            f"Updated {symbol} parent quantities. New quantity: {new_quantity}, Available: {new_available}"
        )

    def toggle_expand_coin_item(self, symbol: str) -> None:
        """Toggle the expanded state for a coin, following HP list approach."""
        logger.info(f"Toggling expand for {symbol}")

        # Skip if this is a lot row (shouldn't happen but safety check)
        if symbol.startswith("  └─"):
            logger.warning(f"Attempted to toggle lot row: {symbol}")
            return

        # Find the parent coin and toggle its state
        for coin_data in self.coin_list_data:
            if (
                not coin_data.get("is_lot_row", False)
                and coin_data.get("symbol") == symbol
            ):
                # Toggle this coin
                coin_data["expanded"] = not coin_data.get("expanded", False)
                logger.info(f"Toggled {symbol} to expanded={coin_data['expanded']}")
                break
        else:
            logger.warning(f"Could not find parent coin with symbol: {symbol}")
            return

        # Rebuild the entire list
        self._rebuild_coin_list_with_lots()

    def _rebuild_coin_list_with_lots(self):
        """Rebuild coin_list_data with expanded lots as separate items."""
        logger.debug("=== Rebuilding coin list ===")

        # Step 1: Collect all parent coins (skip any existing lot rows)
        parent_coins = []
        for coin_data in self.coin_list_data:
            if not coin_data.get("is_lot_row", False):
                parent_coins.append(coin_data)

        # Step 2: Build new list with parent coins and their expanded lots
        new_data = []
        for parent_coin in parent_coins:
            # Ensure parent coin has all required properties
            parent_coin["portfolio_manager"] = self
            parent_coin["has_lots"] = len(parent_coin.get("lots", [])) > 0
            parent_coin["is_lot_row"] = False

            # Calculate and update weighted average buy price for parent coin
            if parent_coin.get("lots"):
                weighted_avg_buy_price = self._calculate_weighted_average_buy_price(
                    parent_coin["lots"], parent_coin.get("symbol")
                )
                parent_coin["buy_price"] = (
                    f"${weighted_avg_buy_price}" if weighted_avg_buy_price > 0 else "—"
                )

            # Add the parent coin
            new_data.append(parent_coin)

            # If expanded, add lot rows immediately after
            if parent_coin.get("expanded", False) and parent_coin.get("lots"):
                # Calculate how much of the parent's available quantity to distribute among lots
                parent_available = float(parent_coin.get("available_qty", "0"))
                total_lot_quantity = sum(
                    (
                        getattr(lot, "quantity", 0)
                        if hasattr(lot, "quantity")
                        else lot.get("quantity", 0)
                    )
                    for lot in parent_coin["lots"]
                )

                for lot in parent_coin["lots"]:
                    # Create lot row
                    if hasattr(lot, "quantity"):  # InventoryItem object
                        lot_quantity = lot.quantity
                        price_usd = str(getattr(lot, "buy_price", 0))
                    else:  # Dictionary
                        lot_quantity = lot.get("quantity", 0)
                        price_usd = str(lot.get("buy_price", 0))

                    # Calculate proportional available quantity for this lot
                    # If the parent has less available than total lots, distribute proportionally
                    if total_lot_quantity > 0:
                        lot_proportion = lot_quantity / total_lot_quantity
                        lot_available = min(
                            lot_quantity, parent_available * lot_proportion
                        )
                    else:
                        lot_available = 0

                    lot_item = {
                        "symbol": f"  └─ Lot",
                        "buy_price": f"${price_usd}",  # Show buy price in new column
                        "quantity": str(lot_quantity),
                        "available_qty": f"{lot_available:.8f}".rstrip("0").rstrip(
                            "."
                        ),  # Proportional available
                        "locked_qty": "0",
                        "price_usd": "—",  # Don't show current price for lots
                        "total_usd": "0.00",
                        "pnl": "—",  # No PnL for individual lots
                        "pnl_color": [1, 1, 1, 1],  # White color
                        "weighted_avg_buy_price": (
                            float(price_usd) if price_usd != "0" else 0.0
                        ),
                        "expanded": False,
                        "lots": [],
                        "is_lot_row": True,
                        "has_lots": False,
                        "portfolio_manager": self,
                    }
                    new_data.append(lot_item)

        # Step 3: Update the data
        self.coin_list_data.clear()
        self.coin_list_data.extend(new_data)

        logger.debug(f"Rebuild complete: {len(new_data)} items")

        # Force refresh
        self.ids.coin_list.refresh_from_data()

    async def init_portfolio_source(self, balances: Dict[str, CoinBalance]) -> None:
        """Check portfolio data sources in priority order: 1) Database, 2) CSV file, 3) Exchange."""
        try:
            # Priority 1: Use fetch_all_inventory_items for DB inventory retrieval
            db_items = await self.db.fetch_all_inventory_items()
            if db_items:
                self.set_inventory(db_items, balances)
                self.ids.coin_list.refresh_from_data()
                logger.info("Portfolio loaded from database.")
            else:
                # Priority 2: Try to load from inventory.csv if database is empty
                logger.info("Database empty, checking for inventory.csv file.")
                if await self._try_load_inventory_csv():
                    logger.info("Portfolio loaded from inventory.csv file.")
                else:
                    # Priority 3: Fallback to exchange data
                    logger.info(
                        "No inventory.csv found, portfolio will be loaded from exchange."
                    )

            # Always start update_ui() to handle price updates and other events
            asyncio.create_task(self.update_ui())

        except Exception as e:
            logger.error(f"Failed to initialize portfolio source: {e}")

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
                    )
                    inventory_items.append(item)
                except Exception as e:
                    logger.error("Failed to parse inventory row: %s error: %s", row, e)

            if inventory_items:
                self.set_inventory(inventory_items, self.balances)
                self.ids.coin_list.refresh_from_data()
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

    def open_virtual_position_popup(self):
        layout = BoxLayout(orientation="vertical", spacing=10, padding=20)
        symbol_input = TextInput(hint_text="Symbol", multiline=False)
        quantity_input = TextInput(
            hint_text="Quantity", multiline=False, input_filter="float"
        )
        wallet_input = TextInput(hint_text="Wallet name (optional)", multiline=False)
        add_btn = Button(text="Add", size_hint_y=None, height=40)

        def add_manual_position_callback(instance):
            symbol = symbol_input.text.strip().upper()
            quantity = quantity_input.text.strip()
            wallet = wallet_input.text.strip()
            if symbol and quantity:
                # Add manual position to UI (quantity only, does not affect available)
                self.coin_list_data.append(
                    {
                        "symbol": symbol,
                        "buy_price": "—",  # Manual positions don't have individual buy prices
                        "quantity": quantity,
                        "available_qty": "0",  # Manual positions do not affect available
                        "locked_qty": "0",
                        "price_usd": "0.00",
                        "total_usd": "0.00",
                        "pnl": "—",  # No buy price for manual positions
                        "pnl_color": [1, 1, 1, 1],  # Default white color (RGBA)
                        "weighted_avg_buy_price": 0.0,  # No buy price for manual positions
                        "lots": [],
                        "expanded": False,
                        "has_lots": False,
                        "portfolio_manager": self,  # Add reference to portfolio manager
                    }
                )
                self.ids.coin_list.refresh_from_data()
                popup.dismiss()

        add_btn.bind(on_release=add_manual_position_callback)

        layout.add_widget(
            Label(text="Add Manual Position", size_hint_y=None, height=30)
        )
        layout.add_widget(symbol_input)
        layout.add_widget(quantity_input)
        layout.add_widget(wallet_input)
        layout.add_widget(add_btn)

        popup = Popup(
            title="Add Manual Position",
            content=layout,
            size_hint=(0.5, 0.5),
            auto_dismiss=True,
        )
        popup.open()

    def remove_manual_position(self, symbol, is_manual=True):
        """Remove a manually added position from the UI."""
        idx_to_remove = None
        for idx, coin in enumerate(self.coin_list_data):
            # Identify manual positions by checking if they don't have lots (indicating they weren't loaded from inventory)
            if coin["symbol"] == symbol and not coin.get("lots", []):
                idx_to_remove = idx
                break
        if idx_to_remove is not None:
            self.coin_list_data.pop(idx_to_remove)
            self.ids.coin_list.refresh_from_data()

    def set_inventory(
        self, inventory: List[InventoryItem], balances: Dict[str, CoinBalance]
    ):
        """Update the coin list data from the inventory, with all resources available."""

        # Group inventory items by coin
        coin_lots = defaultdict(list)
        for item in inventory:
            coin_lots[item.coin].append(item)

        coin_list = []

        for coin, lots in coin_lots.items():
            total_qty = sum(lot.quantity for lot in lots)
            # Calculate weighted average buy price
            weighted_avg_buy_price = self._calculate_weighted_average_buy_price(
                lots, coin
            )

            # Use CoinBalance if available, else fallback to inventory
            cb = balances.get(coin)
            available_qty = str(cb.free) if cb else str(total_qty)
            locked_qty = str(cb.locked) if cb else "0"
            total_value = str(cb.total_value) if cb else "0.00"
            coin_list.append(
                {
                    "symbol": coin,
                    "buy_price": (
                        f"${weighted_avg_buy_price}"
                        if weighted_avg_buy_price > 0
                        else "—"
                    ),
                    "quantity": str(total_qty),
                    "available_qty": available_qty,
                    "locked_qty": locked_qty,
                    "price_usd": "0.00",
                    "total_usd": total_value,
                    "pnl": "—",  # Will be calculated when current prices are available
                    "pnl_color": [
                        1,
                        1,
                        1,
                        1,
                    ],  # Default white color (RGBA), will be updated based on PnL
                    "weighted_avg_buy_price": weighted_avg_buy_price,  # Store for PnL calculation
                    "lots": lots,
                    "expanded": False,
                    "has_lots": len(lots) > 0,
                    "portfolio_manager": self,  # Add reference to portfolio manager
                }
            )
        self.coin_list_data = coin_list

    def _calculate_weighted_average_buy_price(
        self, lots: List[InventoryItem], coin_symbol: str
    ) -> float:
        """Calculate weighted average buy price from a list of lots."""
        if not lots:
            return 0.0

        total_value = 0.0
        total_quantity = 0.0

        for lot in lots:
            total_value += lot.buy_price * lot.quantity
            total_quantity += lot.quantity

        avg_price = total_value / total_quantity if total_quantity > 0 else 0.0

        # Apply symbol-specific price precision if available
        if avg_price > 0 and coin_symbol:
            try:
                symbol_key = f"{coin_symbol}USDT"
                if symbol_key in self.symbols_info:
                    return self.symbols_info[symbol_key].adjust_price(avg_price)
            except (KeyError, AttributeError):
                # Fallback to original precision if symbol info not available
                pass

        # Default fallback: round to 4 decimal places for reasonable display
        return round(avg_price, 4) if avg_price > 0 else 0.0

    def _calculate_pnl_percentage(self, buy_price: float, current_price: float) -> str:
        """Calculate PnL percentage between buy price and current price."""
        if buy_price <= 0 or current_price <= 0:
            return "—"

        pnl_percentage = ((current_price - buy_price) / buy_price) * 100
        return f"{pnl_percentage:+.2f}%"

    async def update_ui(self) -> None:
        logger.info("Ready to receive portfolio UI updates.")
        while True:
            try:
                data = self.ui_queue.get_nowait()
                # logger.info("Received data: %s", data)
                # Process the data and update the UI
                assert isinstance(data, Event)

                if data.name == EventName.BALANCES:
                    assert isinstance(data.content, Dict)
                    self.create_coin_list(data.content)
                if data.name == EventName.ACCOUNT_POSITION:
                    assert isinstance(data.content, AccountPosition)
                    self.update_coin_list(data.content)
                if data.name == EventName.PRICE_UPDATES:
                    assert isinstance(data.content, PriceUpdates)
                    # Update saldo in USD and BTC
                    await self.update_coin_prices(data.content)
                if data.name == EventName.PORTFOLIO_INVENTORY:
                    # Inventory event: update UI with new inventory (all available)
                    if isinstance(data.content, List):
                        self.set_inventory(data.content, balances=self.balances)
                        self.ids.coin_list.refresh_from_data()
                    else:
                        logger.warning(
                            f"PORTFOLIO_INVENTORY event received with unexpected content type: {type(data.content)}"
                        )

            except queue.Empty:
                await asyncio.sleep(0.1)

    def create_coin_list(self, balances: Dict[str, CoinBalance]) -> None:
        """Create the coin list in the UI based on new ticker data."""
        logger.info("Going to prepare initial coin list.")

        # Get existing coin symbols to avoid duplicates (from CSV or DB)
        existing_coins = {
            coin["symbol"]: coin
            for coin in self.coin_list_data
            if not coin.get("is_lot_row", False)
        }

        for symbol, coin_balance in balances.items():
            # If coin already exists from CSV/DB import, update its balance info
            if symbol in existing_coins:
                logger.debug(f"Updating balance info for existing {symbol}")
                existing_coin = existing_coins[symbol]
                existing_coin["available_qty"] = str(coin_balance.free)
                existing_coin["locked_qty"] = str(coin_balance.locked)
                # Keep the imported total_value if it exists, otherwise use exchange value
                if existing_coin.get("total_usd") == "0.00":
                    existing_coin["total_usd"] = str(coin_balance.total_value)
                continue

            try:
                # Round up to coins precision, to filter out first close to zero quantities
                rounded = self.symbols_info[f"{symbol}USDT"].adjust_quantity(
                    quantity=coin_balance.total
                )
                if rounded:
                    coin_data = {
                        "symbol": symbol,
                        "buy_price": "—",  # Exchange balances don't have buy price history
                        "quantity": str(rounded),
                        "available_qty": str(coin_balance.free),
                        "locked_qty": str(coin_balance.locked),
                        "price_usd": "0.00",
                        "total_usd": "0.00",
                        "pnl": "—",  # No buy price available for exchange balances
                        "pnl_color": [1, 1, 1, 1],  # Default white color (RGBA)
                        "weighted_avg_buy_price": 0.0,  # No buy price for exchange balances
                        "lots": [],
                        "expanded": False,
                        "has_lots": False,
                        "portfolio_manager": self,  # Add reference to portfolio manager
                    }
                    self.coin_list_data.append(coin_data)
            except KeyError as e:
                # Log the error and skip the symbol
                logger.warning(
                    f"Symbol {symbol} not found in symbol info. Skipping. Error: {e}"
                )
                continue

    async def update_coin_prices(self, price_updates: PriceUpdates) -> None:
        """Update the prices of coins based on ticker data from AllTickers and filter based on total value."""

        last_btc_price = price_updates.msg.get("BTC")

        # Update prices for all coins (including lot rows which have lot-specific prices)
        for coin in self.coin_list_data:
            symbol = coin["symbol"]

            # Only update prices for parent coins (not lot rows)
            if not coin.get("is_lot_row", False) and symbol in price_updates.msg:
                price = price_updates.msg[symbol]
                coin["price_usd"] = str(
                    self.symbols_info[f"{symbol}USDT"].adjust_price(price)
                )
                total_in_usd = round(float(coin["quantity"]) * price, 2)
                coin["total_usd"] = str(total_in_usd)

                # Calculate PnL if we have a buy price
                buy_price = coin.get("weighted_avg_buy_price", 0.0)
                if buy_price > 0:
                    pnl_percentage = self._calculate_pnl_percentage(buy_price, price)
                    coin["pnl"] = pnl_percentage
                    # Set color based on PnL
                    if pnl_percentage != "—":
                        if pnl_percentage.startswith("+"):
                            coin["pnl_color"] = [0, 1, 0, 1]  # Green (RGBA)
                        elif pnl_percentage.startswith("-"):
                            coin["pnl_color"] = [1, 0, 0, 1]  # Red (RGBA)
                        else:
                            coin["pnl_color"] = [1, 1, 1, 1]  # White (RGBA)
                else:
                    coin["pnl"] = "—"
                    coin["pnl_color"] = [1, 1, 1, 1]  # White (RGBA)

        # Extract parent coins and sort by value
        parent_coins = [
            coin for coin in self.coin_list_data if not coin.get("is_lot_row", False)
        ]
        parent_coins.sort(key=lambda x: float(x["total_usd"]), reverse=True)

        # Rebuild list maintaining expansion states
        new_coin_list = []
        for parent_coin in parent_coins:
            # Ensure parent coin properties are correct
            parent_coin["has_lots"] = len(parent_coin.get("lots", [])) > 0
            parent_coin["portfolio_manager"] = self

            # Calculate and update weighted average buy price for parent coin
            if parent_coin.get("lots"):
                weighted_avg_buy_price = self._calculate_weighted_average_buy_price(
                    parent_coin["lots"], parent_coin.get("symbol")
                )
                parent_coin["buy_price"] = (
                    f"${weighted_avg_buy_price}" if weighted_avg_buy_price > 0 else "—"
                )

            new_coin_list.append(parent_coin)

            # Add lot rows if expanded
            if parent_coin.get("expanded", False) and parent_coin.get("lots"):
                # Calculate how much of the parent's available quantity to distribute among lots
                parent_available = float(parent_coin.get("available_qty", "0"))
                total_lot_quantity = sum(
                    (
                        getattr(lot, "quantity", 0)
                        if hasattr(lot, "quantity")
                        else lot.get("quantity", 0)
                    )
                    for lot in parent_coin["lots"]
                )

                for lot in parent_coin["lots"]:
                    if hasattr(lot, "quantity"):  # InventoryItem object
                        lot_quantity = lot.quantity
                        buy_price = str(getattr(lot, "buy_price", 0))
                    else:  # Dictionary
                        lot_quantity = lot.get("quantity", 0)
                        buy_price = str(lot.get("buy_price", 0))

                    # Calculate proportional available quantity for this lot
                    if total_lot_quantity > 0:
                        lot_proportion = lot_quantity / total_lot_quantity
                        lot_available = min(
                            lot_quantity, parent_available * lot_proportion
                        )
                    else:
                        lot_available = 0

                    lot_item = {
                        "symbol": f"  └─ Lot",
                        "buy_price": f"${buy_price}",  # Show buy price in new column
                        "quantity": str(lot_quantity),
                        "available_qty": f"{lot_available:.8f}".rstrip("0").rstrip(
                            "."
                        ),  # Proportional available
                        "locked_qty": "0",
                        "price_usd": "—",  # Don't show current price for lots
                        "total_usd": "0.00",
                        "pnl": "—",  # No PnL for individual lots
                        "pnl_color": [1, 1, 1, 1],  # White color
                        "weighted_avg_buy_price": (
                            float(buy_price) if buy_price != "0" else 0.0
                        ),
                        "expanded": False,
                        "lots": [],
                        "is_lot_row": True,
                        "has_lots": False,
                        "portfolio_manager": self,
                    }
                    new_coin_list.append(lot_item)

        # Update the data
        self.coin_list_data.clear()
        self.coin_list_data.extend(new_coin_list)

        # Update saldo labels
        self.saldo_usd_label = round(
            sum([float(coin["total_usd"]) for coin in parent_coins]), 2
        )
        if last_btc_price:
            self.saldo_btc_label = round(self.saldo_usd_label / last_btc_price, 8)

        self.ids.saldo_usd_label.text = str(self.saldo_usd_label)
        self.ids.saldo_btc_label.text = str(self.saldo_btc_label)

        # Throttled refresh to avoid excessive UI updates that break button bindings
        current_time = time.time()
        if current_time - self._last_refresh_time > 1.0:  # Max 1 refresh per second
            self.ids.coin_list.refresh_from_data()
            self._last_refresh_time = current_time

    def update_coin_list(self, account_position: AccountPosition) -> None:
        """Update the coin list based on AccountPosition updates."""
        logger.info("Updating coin list based on AccountPosition updates.")

        for balance in account_position.balances:
            symbol = balance.coin
            total_balance = balance.free + balance.locked

            # Check if the coin exists in the current coin list (only parent coins)
            found = False
            for coin in self.coin_list_data:
                if not coin.get("is_lot_row", False) and coin["symbol"] == symbol:
                    coin["quantity"] = str(round(total_balance, 2))
                    coin["available_qty"] = str(balance.free)
                    coin["locked_qty"] = str(balance.locked)
                    found = True
                    logger.info(f"Updated {symbol} quantity to {total_balance}")
                    break

            # If the coin is not in the current coin list, add it
            if not found:
                logger.info(f"Adding new symbol {symbol} to the coin list.")

                coin_data = {
                    "symbol": symbol,
                    "buy_price": "—",  # Exchange balances don't have buy price history
                    "quantity": str(total_balance),
                    "available_qty": str(balance.free),
                    "locked_qty": str(balance.locked),
                    "price_usd": "0.00",
                    "total_usd": "0.00",
                    "pnl": "—",  # No buy price available for exchange balances
                    "pnl_color": [1, 1, 1, 1],  # Default white color (RGBA)
                    "weighted_avg_buy_price": 0.0,  # No buy price for exchange balances
                    "lots": [],
                    "expanded": False,
                    "has_lots": False,
                    "portfolio_manager": self,  # Add reference to portfolio manager
                }
                self.coin_list_data.append(coin_data)

        # Don't sort here - let update_coin_prices handle sorting to maintain structure
        # Just refresh the UI
        self.ids.coin_list.refresh_from_data()
