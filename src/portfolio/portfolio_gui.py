from collections import defaultdict
import logging
import queue
from typing import Dict, List
import uuid
from kivy.properties import ObjectProperty, ListProperty
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


from kivy.uix.boxlayout import BoxLayout
import asyncio
import logging

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
        # On startup, check if DB is empty and choose data source
        try:
            asyncio.create_task(self.init_portfolio_source(balances=balances))
        except RuntimeError:
            # No event loop running (e.g., in tests), skip async initialization
            logger.warning("No event loop running, skipping async initialization")

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

            # Add the parent coin
            new_data.append(parent_coin)

            # If expanded, add lot rows immediately after
            if parent_coin.get("expanded", False) and parent_coin.get("lots"):
                for lot in parent_coin["lots"]:
                    # Create lot row
                    if hasattr(lot, "quantity"):  # InventoryItem object
                        quantity = str(lot.quantity)
                        price_usd = str(getattr(lot, "buy_price", 0))
                    else:  # Dictionary
                        quantity = str(lot.get("quantity", 0))
                        price_usd = str(lot.get("buy_price", 0))

                    lot_item = {
                        "symbol": f"  └─ Lot",
                        "quantity": quantity,
                        "available_qty": quantity,
                        "locked_qty": "0",
                        "price_usd": price_usd,
                        "total_usd": "0.00",
                        "source": "lot",
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
        """Check if portfolio table in DB is empty and choose data source for display."""
        try:
            # Use fetch_all_inventory_items for DB inventory retrieval
            db_items = await self.db.fetch_all_inventory_items()
            if db_items:
                self.set_inventory(db_items, balances)
                self.ids.coin_list.refresh_from_data()
                logger.info("Portfolio loaded from database.")
            else:
                logger.info("Database empty, portfolio will be loaded from exchange.")
                asyncio.create_task(self.update_ui())
        except Exception as e:
            logger.error(f"Failed to initialize portfolio source: {e}")

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
                        "quantity": quantity,
                        "available_qty": "0",  # Manual positions do not affect available
                        "locked_qty": "0",
                        "price_usd": "0.00",
                        "total_usd": "0.00",
                        "source": wallet if wallet else "manual",
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

    def remove_manual_position(self, symbol, source):
        """Remove a manually added position from the UI."""
        idx_to_remove = None
        for idx, coin in enumerate(self.coin_list_data):
            if coin["symbol"] == symbol and coin["source"] == source:
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
            # Use CoinBalance if available, else fallback to inventory
            cb = balances.get(coin)
            available_qty = str(cb.free) if cb else str(total_qty)
            locked_qty = str(cb.locked) if cb else "0"
            total_value = str(cb.total_value) if cb else "0.00"
            coin_list.append(
                {
                    "symbol": coin,
                    "quantity": str(total_qty),
                    "available_qty": available_qty,
                    "locked_qty": locked_qty,
                    "price_usd": "0.00",
                    "total_usd": total_value,
                    "source": "imported",
                    "lots": lots,
                    "expanded": False,
                    "has_lots": len(lots) > 0,
                    "portfolio_manager": self,  # Add reference to portfolio manager
                }
            )
        self.coin_list_data = coin_list

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

        for symbol, coin_balance in balances.items():
            try:
                # Round up to coins precision, to filter out first close to zero quantities
                rounded = self.symbols_info[f"{symbol}USDT"].adjust_quantity(
                    quantity=coin_balance.total
                )
                if rounded:
                    coin_data = {
                        "symbol": symbol,
                        "quantity": str(rounded),
                        "available_qty": str(coin_balance.free),
                        "locked_qty": str(coin_balance.locked),
                        "price_usd": "0.00",
                        "total_usd": "0.00",
                        "source": "binance",
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
            new_coin_list.append(parent_coin)

            # Add lot rows if expanded
            if parent_coin.get("expanded", False) and parent_coin.get("lots"):
                for lot in parent_coin["lots"]:
                    if hasattr(lot, "quantity"):  # InventoryItem object
                        quantity = str(lot.quantity)
                        price_usd = str(getattr(lot, "buy_price", 0))
                    else:  # Dictionary
                        quantity = str(lot.get("quantity", 0))
                        price_usd = str(lot.get("buy_price", 0))

                    lot_item = {
                        "symbol": f"  └─ Lot",
                        "quantity": quantity,
                        "available_qty": quantity,
                        "locked_qty": "0",
                        "price_usd": price_usd,
                        "total_usd": "0.00",
                        "source": "lot",
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
                    "quantity": str(total_balance),
                    "available_qty": str(balance.free),
                    "locked_qty": str(balance.locked),
                    "price_usd": "0.00",
                    "total_usd": "0.00",
                    "source": "binance",
                    "lots": [],
                    "expanded": False,
                    "has_lots": False,
                    "portfolio_manager": self,  # Add reference to portfolio manager
                }
                self.coin_list_data.append(coin_data)

        # Don't sort here - let update_coin_prices handle sorting to maintain structure
        # Just refresh the UI
        self.ids.coin_list.refresh_from_data()
