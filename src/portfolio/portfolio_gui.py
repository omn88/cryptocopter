import asyncio
import os
import csv
import uuid
from collections import defaultdict
import logging
import queue
import time
from typing import Dict, List, Union, Optional
from kivy.properties import ListProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from src.gui.hp_manager.hpfront import HpFront
from src.identifiers import (
    AccountPosition,
    Event,
    EventName,
    InventoryItem,
    PriceUpdates,
    HPSellPositionCreated,
    HPSellPositionCompleted,
    HPSellPositionPartiallyFilled,
    HPBuyPositionFilled,
    HPBuyPositionPartiallyFilled,
    HPBuyOrdersPlaced,
    HPPositionCancelled,
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
        test_mode: bool = False,
        **kwargs,
    ) -> None:
        # Initialize the base class (BoxLayout) only if not in test mode
        if not test_mode:
            super().__init__(**kwargs)  # This ensures proper widget initialization
        else:
            # In test mode, skip Kivy widget initialization
            object.__init__(self)

        self.ui_queue = ui_queue
        self.symbols_info = symbols_info
        self.coin_list_data = []
        self.inventory: List[InventoryItem] = []
        self.db = db
        self.test_mode = test_mode  # Add test_mode parameter
        self._last_refresh_time = 0.0  # Track last refresh time to throttle updates
        self._hp_currency_processed: set[str] = (
            set()
        )  # Track HP IDs that have already added currency
        self.hp_manager: Optional[HpFront] = (
            None  # Reference to HP manager for sell functionality
        )
        self.app = None

    def initialize(self):
        """Initialize the PortfolioUI and start UI queue processing."""
        if not self.test_mode:
            self.queue_task = asyncio.create_task(self.update_ui())
            logger.info(
                "[PORTFOLIO PRODUCTION] Started UI queue processing task in production mode"
            )
        else:
            logger.info(
                "[PORTFOLIO PRODUCTION] Skipped UI queue task - running in test mode"
            )

    def set_hp_manager_reference(self, hp_manager, app):
        """Set reference to HP manager and main app for sell functionality."""
        self.hp_manager = hp_manager
        self.app = app

    def sell_lot_button(self, lot_symbol, available_quantity, buy_price):
        """Handle sell button for individual lot (child row)."""
        # Check if HP Manager is available before proceeding
        if not self.hp_manager:
            logger.warning("HP Manager not available - sell functionality disabled")
            error_popup = Popup(
                title="HP Manager Required",
                content=Label(
                    text="HP Manager is not available.\nSell functionality requires HP Manager to be active."
                ),
                size_hint=(0.5, 0.3),
                auto_dismiss=True,
            )
            error_popup.open()
            return

        # Extract the parent symbol from the lot display
        # Find the parent coin this lot belongs to by matching buy price and available quantity
        parent_symbol = None
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin.get("lots"):
                # Check if this coin has a lot with matching buy price
                for lot in coin["lots"]:
                    if hasattr(lot, "buy_price"):
                        if str(lot.buy_price) == str(buy_price):
                            parent_symbol = coin["symbol"]
                            parent_coin = coin
                            break
                if parent_symbol:
                    break

        if not parent_symbol or not parent_coin:
            logger.error("Could not find parent symbol for lot")
            return

        # Create a modified parent coin data for this specific lot
        lot_data = {
            "symbol": parent_symbol,
            "available_qty": str(available_quantity),  # Use lot's available quantity
            "quantity": str(available_quantity),  # Use lot's quantity
            "weighted_avg_buy_price": float(buy_price),  # Use lot's buy price
        }

        # Show sell dialog for this specific lot with prefilled quantity
        self.open_sell_quantity_popup(
            parent_symbol, lot_data, prefill_quantity=float(available_quantity)
        )

    def sell_parent_button(self, symbol):
        """Handle sell button for parent coin (allows partial or full sell)."""
        # Check if HP Manager is available before proceeding
        if not self.hp_manager:
            logger.warning("HP Manager not available - sell functionality disabled")
            error_popup = Popup(
                title="HP Manager Required",
                content=Label(
                    text="HP Manager is not available.\nSell functionality requires HP Manager to be active."
                ),
                size_hint=(0.5, 0.3),
                auto_dismiss=True,
            )
            error_popup.open()
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

        # Show sell dialog to let user choose quantity
        self.open_sell_quantity_popup(symbol, parent_coin)

    def open_sell_quantity_popup(self, symbol, parent_coin, prefill_quantity=None):
        """Open a popup dialog to choose sell quantity and price."""
        available_qty = float(parent_coin.get("available_qty", "0"))
        total_qty = float(parent_coin.get("quantity", "0"))
        avg_buy_price = parent_coin.get("weighted_avg_buy_price", 0.0)

        # If this is a child lot, use prefill_quantity, otherwise show all available
        is_child_lot = prefill_quantity is not None
        display_qty = prefill_quantity if is_child_lot else available_qty

        layout = BoxLayout(orientation="vertical", spacing=10, padding=20)

        # Information labels
        lot_type = "Lot" if is_child_lot else "Position"
        info_label = Label(
            text=f"Sell {symbol} {lot_type}",
            size_hint_y=None,
            height=40,
            font_size="18sp",
        )

        if is_child_lot:
            # For child lots, show lot-specific information
            total_info_label = Label(
                text=f"Lot Quantity: {display_qty:.8f} {symbol}",
                size_hint_y=None,
                height=30,
                font_size="14sp",
            )

            available_info_label = Label(
                text=f"Available to Sell: {display_qty:.8f} {symbol}",
                size_hint_y=None,
                height=30,
                font_size="14sp",
                color=[0, 1, 0, 1],  # Green color for available quantity
            )
        else:
            # For parent positions, show total holdings
            total_info_label = Label(
                text=f"Total Holdings: {total_qty:.8f} {symbol}",
                size_hint_y=None,
                height=30,
                font_size="14sp",
            )

            available_info_label = Label(
                text=f"Available to Sell: {available_qty:.8f} {symbol}",
                size_hint_y=None,
                height=30,
                font_size="14sp",
                color=[0, 1, 0, 1],  # Green color for available quantity
            )

        price_info_label = Label(
            text=f"Buy Price: ${avg_buy_price:.4f}",
            size_hint_y=None,
            height=30,
            font_size="14sp",
        )

        # Quantity input
        quantity_input = TextInput(
            hint_text=f"Quantity to sell (max: {display_qty:.8f})",
            multiline=False,
            input_filter="float",
            size_hint_y=None,
            height=40,
            text=(
                f"{display_qty:.8f}".rstrip("0").rstrip(".") if is_child_lot else ""
            ),  # Prefill for child lots
        )

        # Sell price input
        price_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=40, spacing=10
        )
        price_label = Label(text="Sell Price:", size_hint_x=0.3)
        price_input = TextInput(
            hint_text="Enter sell price",
            multiline=False,
            input_filter="float",
            size_hint_x=0.7,
        )
        price_layout.add_widget(price_label)
        price_layout.add_widget(price_input)

        # Expected return calculation
        return_label = Label(
            text="Expected return will be calculated...",
            size_hint_y=None,
            height=30,
            font_size="14sp",
            color=[0.8, 0.8, 0.8, 1],
        )

        # Update expected return when price changes
        def update_expected_return(instance, text):
            try:
                if not quantity_input.text or not text:
                    return_label.text = "Expected return will be calculated..."
                    return

                sell_price = float(text)
                quantity_float = float(quantity_input.text)

                if sell_price > 0 and avg_buy_price > 0 and quantity_float > 0:
                    profit = (sell_price - avg_buy_price) * quantity_float
                    profit_percent = ((sell_price / avg_buy_price) - 1) * 100
                    return_label.text = (
                        f"Expected return: {profit:.2f} USDC ({profit_percent:.2f}%)"
                    )
                else:
                    return_label.text = "Expected return will be calculated..."
            except ValueError:
                return_label.text = "Invalid price or quantity entered"

        # Update expected return when quantity changes too
        def update_return_on_quantity_change(instance, text):
            update_expected_return(price_input, price_input.text)

        price_input.bind(text=update_expected_return)
        quantity_input.bind(text=update_return_on_quantity_change)

        # Quick percentage buttons for quantity
        button_layout = BoxLayout(
            orientation="horizontal", spacing=10, size_hint_y=None, height=50
        )
        quick_25_btn = Button(text="25%", size_hint_x=0.25)
        quick_50_btn = Button(text="50%", size_hint_x=0.25)
        quick_75_btn = Button(text="75%", size_hint_x=0.25)
        quick_100_btn = Button(text="100%", size_hint_x=0.25)

        # Action buttons
        action_layout = BoxLayout(
            orientation="horizontal", spacing=10, size_hint_y=None, height=50
        )
        cancel_btn = Button(text="Cancel", size_hint_x=0.5)
        sell_btn = Button(
            text="CREATE SELL ORDER",
            size_hint_x=0.5,
            background_color=[0.2, 0.8, 0.2, 1],
        )

        def set_percentage(percentage):
            def callback(instance):
                qty_to_set = display_qty * (percentage / 100.0)
                quantity_input.text = f"{qty_to_set:.8f}".rstrip("0").rstrip(".")
                # Trigger return calculation update
                update_expected_return(price_input, price_input.text)

            return callback

        def sell_callback(instance):
            try:
                sell_quantity = (
                    float(quantity_input.text.strip())
                    if quantity_input.text.strip()
                    else 0
                )
                sell_price = (
                    float(price_input.text.strip()) if price_input.text.strip() else 0
                )

                # Use display_qty as the maximum allowed (either lot quantity or available quantity)
                max_allowed = display_qty

                if sell_quantity <= 0:
                    logger.error("Sell quantity must be greater than 0")
                    return
                if sell_quantity > max_allowed:
                    logger.error(
                        f"Cannot sell {sell_quantity} - only {max_allowed} available"
                    )
                    return
                if sell_price <= 0:
                    logger.error("Sell price must be greater than 0")
                    return

                # Create the sell order directly without switching tabs or opening another popup
                if not self.hp_manager:
                    logger.error(
                        "HP Manager is not available. Cannot create sell orders."
                    )
                    # Show user-friendly error popup
                    error_popup = Popup(
                        title="Error",
                        content=Label(
                            text="HP Manager is not available.\nCannot create sell orders at this time."
                        ),
                        size_hint=(0.4, 0.3),
                        auto_dismiss=True,
                    )
                    error_popup.open()
                    return

                popup.dismiss()  # Close our popup first

                # Call the HP manager's confirmation method directly
                hp_id = ""  # Empty HP ID for new position

                # Create a dummy popup object since _confirm_sell_hp expects one
                class DummyPopup:
                    def dismiss(self):
                        pass  # Do nothing - our popup is already dismissed

                dummy_popup = DummyPopup()

                try:
                    self.hp_manager._confirm_sell_hp(
                        dummy_popup,
                        hp_id,
                        symbol,
                        str(sell_quantity),
                        str(avg_buy_price),
                        str(sell_price),
                    )
                    logger.info(
                        f"Successfully created sell order for {symbol}: qty={sell_quantity} @ {sell_price}"
                    )
                except Exception as e:
                    logger.error(f"Failed to create sell order: {e}")
                    # Show user-friendly error popup
                    error_popup = Popup(
                        title="Sell Order Failed",
                        content=Label(text=f"Failed to create sell order:\n{str(e)}"),
                        size_hint=(0.5, 0.4),
                        auto_dismiss=True,
                    )
                    error_popup.open()

            except ValueError:
                logger.error("Invalid quantity or price entered")

        def cancel_callback(instance):
            popup.dismiss()
            # Stay on portfolio tab - don't switch to HP Manager

        # Bind button callbacks
        quick_25_btn.bind(on_release=set_percentage(25))
        quick_50_btn.bind(on_release=set_percentage(50))
        quick_75_btn.bind(on_release=set_percentage(75))
        quick_100_btn.bind(on_release=set_percentage(100))
        sell_btn.bind(on_release=sell_callback)
        cancel_btn.bind(on_release=cancel_callback)

        # Build layout
        layout.add_widget(info_label)
        layout.add_widget(total_info_label)
        layout.add_widget(available_info_label)
        layout.add_widget(price_info_label)
        layout.add_widget(Label(text="", size_hint_y=None, height=10))  # Spacer

        layout.add_widget(quantity_input)

        button_layout.add_widget(quick_25_btn)
        button_layout.add_widget(quick_50_btn)
        button_layout.add_widget(quick_75_btn)
        button_layout.add_widget(quick_100_btn)
        layout.add_widget(button_layout)

        layout.add_widget(Label(text="", size_hint_y=None, height=10))  # Spacer
        layout.add_widget(price_layout)
        layout.add_widget(return_label)

        action_layout.add_widget(cancel_btn)
        action_layout.add_widget(sell_btn)
        layout.add_widget(action_layout)

        popup = Popup(
            title=f"Sell {symbol}",
            content=layout,
            size_hint=(0.6, 0.8),
            auto_dismiss=False,
        )
        popup.open()

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

                # Remove from inventory if it exists
                if hasattr(self, "inventory") and self.inventory and hasattr(lot, "id"):
                    self.inventory = [
                        item for item in self.inventory if item.id != lot.id
                    ]

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
                    # Update the lot in coin_list_data
                    lot.quantity = new_quantity
                    lot.available_quantity = new_quantity
                    # Also reduce locked quantity proportionally
                    if hasattr(lot, "locked_quantity") and lot.locked_quantity > 0:
                        # Calculate how much of the locked quantity was sold
                        sold_from_locked = min(remaining_to_sell, lot.locked_quantity)
                        lot.locked_quantity = max(
                            0, lot.locked_quantity - sold_from_locked
                        )

                    # Update corresponding inventory item if it exists
                    if (
                        hasattr(self, "inventory")
                        and self.inventory
                        and hasattr(lot, "id")
                    ):
                        for inv_item in self.inventory:
                            if inv_item.id == lot.id:
                                inv_item.quantity = new_quantity
                                inv_item.available_quantity = new_quantity
                                if hasattr(inv_item, "locked_quantity"):
                                    inv_item.locked_quantity = lot.locked_quantity
                                break

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

    async def _update_lots_after_hp_sell(
        self, hp_id: str, symbol: str, quantity_sold: float
    ):
        """Update the specific HP lot after a sell - either reduce quantity or remove completely."""
        logger.info(
            f"Updating HP lot: hp_{hp_id} for {symbol} (qty sold: {quantity_sold})"
        )

        # Find the parent coin
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin["symbol"] == symbol:
                parent_coin = coin
                break

        if not parent_coin or not parent_coin.get("lots"):
            logger.warning(f"No lots found for {symbol} or parent coin not found")
            return

        # Extract parent HP ID for multihop and convert operations
        # Multihop: "1000a" or "1000b" -> "1000"
        # Convert: "1000_SELL" -> "1000"
        parent_hp_id = hp_id
        if hp_id.endswith(("a", "b")):  # Multihop operations
            parent_hp_id = hp_id[:-1]
            logger.info(
                f"Multihop operation detected: {hp_id} -> parent {parent_hp_id}"
            )
        elif hp_id.endswith("_SELL"):  # Convert operations
            parent_hp_id = hp_id[:-5]  # Remove "_SELL"
            logger.info(f"Convert operation detected: {hp_id} -> parent {parent_hp_id}")

        # Find the specific lot with the parent HP ID
        lot_to_update = None
        lot_id_to_find = f"hp_{parent_hp_id}"

        for lot in parent_coin["lots"]:
            lot_id = getattr(lot, "id", "") if hasattr(lot, "id") else lot.get("id", "")
            if lot_id == lot_id_to_find:
                lot_to_update = lot
                break

        if not lot_to_update:
            logger.warning(
                f"Could not find lot with ID {lot_id_to_find} for HP {hp_id} (parent: {parent_hp_id})"
            )
            # Fallback to FIFO if we can't find the specific lot
            await self._update_lots_after_sell(symbol, quantity_sold)
            return

        # Update the HP inventory item
        inventory_item_to_update = None
        for item in self.inventory:
            if item.id == lot_id_to_find:
                inventory_item_to_update = item
                break

        if not inventory_item_to_update:
            logger.warning(f"Could not find inventory item with ID {lot_id_to_find}")
            return

        # Check if this is a partial sell or complete sell
        if inventory_item_to_update.quantity <= quantity_sold:
            # Complete sell - remove the entire HP inventory item
            parent_coin["lots"].remove(lot_to_update)
            self.inventory.remove(inventory_item_to_update)

            # CRITICAL FIX: Delete inventory item from database
            try:
                await self.db.delete_inventory_item(inventory_item_to_update.id)
                logger.debug(
                    f"Deleted inventory item from database: {inventory_item_to_update.id}"
                )
            except Exception as e:
                logger.error(f"Failed to delete inventory item from database: {e}")

            logger.info(
                f"Removed HP lot {lot_id_to_find} completely (sold {quantity_sold})"
            )
        else:
            # Partial sell - reduce the quantity
            new_quantity = inventory_item_to_update.quantity - quantity_sold
            inventory_item_to_update.quantity = new_quantity
            inventory_item_to_update.available_quantity = (
                new_quantity  # Assume all available for now
            )

            # CRITICAL FIX: Persist updated inventory item to database
            try:
                await self.db.update_inventory_item(inventory_item_to_update)
                logger.debug(
                    f"Persisted partial sell update to database: {inventory_item_to_update.id}"
                )
            except Exception as e:
                logger.error(f"Failed to persist partial sell update to database: {e}")

            logger.info(
                f"Reduced HP lot {lot_id_to_find} from {inventory_item_to_update.quantity + quantity_sold} to {new_quantity}"
            )

        # Recalculate parent coin totals
        total_quantity = 0.0
        total_value = 0.0

        for remaining_lot in parent_coin["lots"]:
            lot_qty = (
                getattr(remaining_lot, "quantity", 0)
                if hasattr(remaining_lot, "quantity")
                else remaining_lot.get("quantity", 0)
            )
            lot_price = (
                getattr(remaining_lot, "buy_price", 0)
                if hasattr(remaining_lot, "buy_price")
                else remaining_lot.get("buy_price", 0)
            )
            total_quantity += lot_qty
            total_value += lot_qty * lot_price

        # Update parent coin quantities
        parent_coin["quantity"] = str(round(total_quantity, 8))
        parent_coin["available_qty"] = str(
            round(total_quantity, 8)
        )  # Assume all available for now
        parent_coin["locked_qty"] = "0"

        # Update weighted average buy price
        if total_quantity > 0:
            weighted_avg_price = total_value / total_quantity
            parent_coin["weighted_avg_buy_price"] = weighted_avg_price
            parent_coin["buy_price"] = str(round(weighted_avg_price, 2))
        else:
            # No lots left - remove the parent coin entirely
            logger.info(
                f"No lots remaining for {symbol} - removing parent coin from inventory"
            )
            self.coin_list_data.remove(parent_coin)
            return

        # Update has_lots flag
        parent_coin["has_lots"] = len(parent_coin["lots"]) > 0

        logger.info(
            f"Updated {symbol} after removing HP lot {hp_id}. Remaining quantity: {total_quantity}, lots: {len(parent_coin['lots'])}"
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

        # Force refresh (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self.ids.coin_list.refresh_from_data()

    def set_inventory(self, inventory: List[InventoryItem]):
        """Update the coin list data from the inventory, with all resources available."""

        # DEBUG: Add comprehensive logging for inventory processing
        logger.debug(
            f"[PORTFOLIO GUI DEBUG] set_inventory called with {len(inventory)} items"
        )

        # Assert that inventory is not empty
        if len(inventory) == 0:
            logger.warning(
                "[PORTFOLIO GUI DEBUG] set_inventory called with empty inventory list"
            )
        else:
            logger.debug(f"[PORTFOLIO GUI DEBUG] First few inventory items:")
            for i, item in enumerate(inventory[:3]):
                logger.debug(
                    f"[PORTFOLIO GUI DEBUG] Item {i}: {item.coin} qty={item.quantity} price={item.buy_price}"
                )

        # Store the inventory items
        self.inventory = inventory.copy()  # Make a copy to avoid reference issues

        # Group inventory items by coin
        coin_lots = defaultdict(list)
        for item in inventory:
            coin_lots[item.coin].append(item)

        logger.debug(
            f"[PORTFOLIO GUI DEBUG] Grouped into {len(coin_lots)} unique coins: {list(coin_lots.keys())}"
        )

        coin_list = []

        for coin, lots in coin_lots.items():
            total_qty = sum(lot.quantity for lot in lots)
            total_available = sum(lot.available_quantity for lot in lots)
            total_locked = sum(lot.locked_quantity for lot in lots)

            # Calculate weighted average buy price
            weighted_avg_buy_price = self._calculate_weighted_average_buy_price(
                lots, coin
            )

            # Calculate total value based on inventory
            total_value = sum(lot.quantity * lot.buy_price for lot in lots)

            coin_data = {
                "symbol": coin,
                "buy_price": (
                    f"${weighted_avg_buy_price}" if weighted_avg_buy_price > 0 else "—"
                ),
                "quantity": str(total_qty),
                "available_qty": str(total_available),
                "locked_qty": str(total_locked),
                "price_usd": "0.00",
                "total_usd": f"{total_value:.2f}",
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

            coin_list.append(coin_data)
            logger.debug(
                f"[PORTFOLIO GUI DEBUG] Added coin {coin}: qty={total_qty}, value=${total_value:.2f}"
            )

        self.coin_list_data = coin_list
        logger.info(
            f"[PORTFOLIO GUI DEBUG] set_inventory completed: coin_list_data has {len(self.coin_list_data)} coins"
        )

        # Assert final state
        assert (
            len(self.coin_list_data) > 0
        ), f"coin_list_data should not be empty after processing {len(inventory)} inventory items"

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
        while not self.test_mode:  # Exit loop immediately in test mode
            try:
                data = self.ui_queue.get_nowait()
                # Process the data and update the UI
                await self._process_ui_event(data)
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"[PORTFOLIO PRODUCTION] Error processing event: {e}")
                await asyncio.sleep(0.1)

    async def process_test_events(self) -> None:
        """Process all pending events in test mode (non-blocking)."""
        processed_count = 0
        try:
            while True:
                data = self.ui_queue.get_nowait()
                await self._process_ui_event(data)
                processed_count += 1
        except queue.Empty:
            logger.debug(f"Processed {processed_count} events in test mode")

    async def _process_ui_event(self, data: Event) -> None:
        """Process a single UI event."""
        assert isinstance(data, Event)

        if data.name == EventName.PORTFOLIO_INVENTORY:
            logger.debug(
                f"[PORTFOLIO GUI DEBUG] Received PORTFOLIO_INVENTORY event with content type: {type(data.content)}"
            )
            if isinstance(data.content, List):
                logger.debug(
                    f"[PORTFOLIO GUI DEBUG] PORTFOLIO_INVENTORY content is list with {len(data.content)} items"
                )
            assert isinstance(data.content, List)
            self.set_inventory(data.content)
        if data.name == EventName.ACCOUNT_POSITION:
            assert isinstance(data.content, AccountPosition)
            # Don't update inventory from account positions - inventory is managed separately
            # Account positions only show exchange balances, not full portfolio inventory
            logger.debug(
                f"[PORTFOLIO GUI DEBUG] Received ACCOUNT_POSITION but ignoring - inventory managed separately"
            )
        if data.name == EventName.PRICE_UPDATES:
            assert isinstance(data.content, PriceUpdates)
            # Update saldo in USD and BTC
            await self.update_coin_prices(data.content)

        # Handle HP Manager events for quantity management
        if data.name == EventName.HP_SELL_POSITION_CREATED:
            assert isinstance(data.content, HPSellPositionCreated)
            await self.handle_hp_sell_created(data.content)
        if data.name == EventName.HP_SELL_POSITION_PARTIALLY_FILLED:
            assert isinstance(data.content, HPSellPositionPartiallyFilled)
            await self.handle_hp_sell_partially_filled(data.content)
        if data.name == EventName.HP_SELL_POSITION_COMPLETED:
            assert isinstance(data.content, HPSellPositionCompleted)
            await self.handle_hp_sell_completed(data.content)
        if data.name == EventName.HP_BUY_ORDERS_PLACED:
            assert isinstance(data.content, HPBuyOrdersPlaced)
            await self.handle_hp_buy_orders_placed(data.content)
        if data.name == EventName.HP_BUY_POSITION_FILLED:
            assert isinstance(data.content, HPBuyPositionFilled)
            await self.handle_hp_buy_filled(data.content)
        if data.name == EventName.HP_BUY_POSITION_PARTIALLY_FILLED:
            assert isinstance(data.content, HPBuyPositionPartiallyFilled)
            await self.handle_hp_buy_partially_filled(data.content)
        if data.name == EventName.HP_POSITION_CANCELLED:
            assert isinstance(data.content, HPPositionCancelled)
            await self.handle_hp_position_cancelled(data.content)

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

        # Update saldo labels (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self.ids.saldo_usd_label.text = str(self.saldo_usd_label)
            self.ids.saldo_btc_label.text = str(self.saldo_btc_label)

        # Throttled refresh to avoid excessive UI updates that break button bindings (skip in test mode)
        if not self.test_mode:
            current_time = time.time()
            if current_time - self._last_refresh_time > 1.0:  # Max 1 refresh per second
                self.ids.coin_list.refresh_from_data()
                self._last_refresh_time = current_time

    async def handle_hp_sell_created(self, event: HPSellPositionCreated):
        """Handle HP sell position creation - lock quantities using FIFO from lowest buy price."""
        logger.info(
            f"HP Sell Created: {event.hp_id} - {event.coin} qty:{event.quantity}"
        )

        # Find the parent coin
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin["symbol"] == event.coin:
                parent_coin = coin
                break

        if not parent_coin:
            logger.warning(f"Parent coin {event.coin} not found for HP sell")
            return

        # Lock quantities using FIFO (lowest buy price first)
        await self._lock_quantities_fifo(event.coin, event.quantity)

        # Refresh UI to show locked quantities (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def handle_hp_buy_orders_placed(self, event: HPBuyOrdersPlaced):
        """Handle HP buy orders placement - lock budget in end currency (usually USDC)."""
        logger.info(
            f"HP Buy Orders Placed: {event.hp_id} - {event.coin} budget:{event.budget_amount} {event.end_currency}"
        )

        # Find the parent coin (end currency, usually USDC)
        parent_coin = None
        for coin in self.coin_list_data:
            if (
                not coin.get("is_lot_row", False)
                and coin["symbol"] == event.end_currency
            ):
                parent_coin = coin
                break

        if not parent_coin:
            logger.warning(
                f"Parent coin {event.end_currency} not found for HP buy budget locking"
            )
            return

        # Lock budget using FIFO (lowest buy price first) - same as sell position locking
        await self._lock_quantities_fifo(event.end_currency, event.budget_amount)

        # Refresh UI to show locked quantities (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def handle_hp_sell_partially_filled(
        self, event: HPSellPositionPartiallyFilled
    ):
        """Handle HP sell partial fill - reduce inventory quantities immediately for development tracking."""
        logger.info(
            f"HP Sell Partially Filled: {event.hp_id} - {event.coin} filled:{event.filled_quantity} (total filled:{event.total_filled})"
        )

        # Reduce inventory by the filled quantity using HP-specific lot reduction
        await self._update_lots_after_hp_sell(
            event.hp_id, event.coin, event.filled_quantity
        )

        # Refresh UI to show updated quantities (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def handle_hp_buy_partially_filled(self, event: HPBuyPositionPartiallyFilled):
        """Handle HP buy partial fill - add inventory quantities immediately for development tracking."""
        logger.info(
            f"HP Buy Partially Filled: {event.hp_id} - {event.coin} filled:{event.filled_quantity} (total filled:{event.total_filled})"
        )

        # Add inventory by the filled quantity using HP-specific lot addition
        await self._add_inventory_after_hp_buy_fill(
            event.hp_id, event.coin, event.filled_quantity, event.buy_price
        )

        # Refresh UI to show updated quantities (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def handle_hp_sell_completed(self, event: HPSellPositionCompleted):
        """Handle HP sell completion - add received currency."""
        logger.info(
            f"HP Sell Completed: {event.hp_id} - Sold {event.quantity_sold} {event.coin}, Received {event.end_currency_received} {event.end_currency}"
        )

        # Note: Inventory reduction is now handled by fill events, not completion events

        # Determine if we should add received currency:
        # 1. Always skip intermediate multihop steps (IDs ending with "a")
        # 2. Add currency for final multihop steps (IDs ending with "b", "c", etc. but not "a")
        # 3. Add currency for direct sell children (IDs ending with "_SELL")
        # 4. For pure digit IDs (like "1000"), this could be either:
        #    - Direct sell parent: should not add currency (child "1000_SELL" will handle it)
        #    - Multihop parent: should not add currency (children "1000a", "1000b" will handle it)
        #    - Convert operation: should add currency (no children, direct conversion)
        #
        # To distinguish convert operations from parent positions, we check if this is the only
        # completion event we expect to receive for this HP ID (no children will send events).

        is_intermediate_multihop = event.hp_id.endswith("a")
        is_final_multihop_child = (
            len(event.hp_id) > 4
            and not event.hp_id.isdigit()
            and not is_intermediate_multihop
        )
        is_direct_sell_child = event.hp_id.endswith("_SELL")
        is_pure_digit_id = event.hp_id.isdigit()

        # Common direct trading pairs that don't need multihop
        direct_pairs = {
            ("BTC", "USDC"),
            ("BTC", "USDT"),
            ("ETH", "USDC"),
            ("ETH", "USDT"),
            ("BNB", "USDC"),
            ("BNB", "USDT"),
            ("USDC", "USDT"),
        }
        is_likely_direct_sell = (event.coin, event.end_currency) in direct_pairs

        # Determine the root HP ID for tracking (extract parent HP ID for child operations)
        root_hp_id = event.hp_id
        if is_final_multihop_child or is_direct_sell_child:
            # For multihop children like "1000b" -> "1000", direct sell children like "1000_SELL" -> "1000"
            if is_final_multihop_child:
                root_hp_id = event.hp_id[:-1]  # Remove last character "b", "c", etc.
            elif is_direct_sell_child:
                root_hp_id = event.hp_id[:-5]  # Remove "_SELL" suffix

        # Check if we've already processed currency for this root HP operation
        if root_hp_id in self._hp_currency_processed:
            logger.info(
                f"Currency already processed for HP operation {root_hp_id}, skipping duplicate {event.hp_id}"
            )
            should_add_currency = False
        else:
            should_add_currency = False
            if is_final_multihop_child:
                # Definitely a final multihop child (e.g., "1000b")
                should_add_currency = True
                logger.info(f"Adding currency for final multihop child {event.hp_id}")
            elif is_direct_sell_child:
                # Direct sell child (e.g., "1000_SELL")
                should_add_currency = True
                logger.info(f"Adding currency for direct sell child {event.hp_id}")
            elif is_pure_digit_id and is_likely_direct_sell:
                # For direct sells with pure digit IDs, we add currency since there's only one completion event
                should_add_currency = True
                logger.info(f"Adding currency for direct sell {event.hp_id}")
            elif is_pure_digit_id:
                # For pure digit IDs that are NOT direct trading pairs, this is likely a convert operation
                # Convert operations use a single HP ID and should receive the currency directly
                should_add_currency = True
                logger.info(f"Adding currency for convert operation {event.hp_id}")
            elif is_intermediate_multihop:
                logger.info(
                    f"Skipping currency addition for intermediate multihop step {event.hp_id}"
                )

        if should_add_currency:
            # Mark this root HP operation as processed to avoid duplicates
            self._hp_currency_processed.add(root_hp_id)
            await self._add_received_currency(
                event.end_currency, event.end_currency_received
            )

        # Refresh UI (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def _add_inventory_after_hp_buy_fill(
        self, hp_id: str, coin: str, filled_quantity: float, buy_price: float
    ):
        """Add inventory for partial buy fills - creates/updates HP inventory item incrementally."""
        logger.info(
            f"Adding inventory for HP buy fill: HP {hp_id} - {filled_quantity} {coin} at ${buy_price}"
        )

        # Create one inventory item per HP ID (not per price)
        inventory_id = f"hp_{hp_id}"

        # Check if inventory item with this HP ID already exists
        existing_item = None
        for item in self.inventory:
            if item.id == inventory_id:
                existing_item = item
                break

        if existing_item:
            # Update existing item - accumulate quantity and calculate weighted average price
            total_value = (existing_item.quantity * existing_item.buy_price) + (
                filled_quantity * buy_price
            )
            total_quantity = existing_item.quantity + filled_quantity
            weighted_avg_price = total_value / total_quantity

            existing_item.quantity = total_quantity
            existing_item.available_quantity += filled_quantity
            existing_item.buy_price = weighted_avg_price

            # CRITICAL FIX: Persist updated inventory item to database
            try:
                await self.db.update_inventory_item(existing_item)
                logger.debug(
                    f"Persisted updated inventory item to database: {inventory_id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to persist updated inventory item to database: {e}"
                )

            logger.info(
                f"Updated existing HP item {inventory_id}: new qty={existing_item.quantity}, weighted avg price=${weighted_avg_price:.2f}"
            )
            new_lot = existing_item
        else:
            # Create new inventory item for this HP ID
            new_lot = InventoryItem(
                id=inventory_id,
                coin=coin,
                buy_price=buy_price,
                quantity=filled_quantity,
                available_quantity=filled_quantity,
                locked_quantity=0.0,
                source="HP_BUY",
                timestamp=time.time(),
                notes=f"HP buy position {hp_id}",
            )

            # Add to main inventory list and save to database
            self.inventory.append(new_lot)

            # CRITICAL FIX: Persist new inventory item to database
            try:
                await self.db.insert_inventory_item(new_lot)
                logger.debug(
                    f"Persisted new inventory item to database: {inventory_id}"
                )
            except Exception as e:
                logger.error(f"Failed to persist new inventory item to database: {e}")

            logger.info(
                f"Created new HP item {inventory_id}: qty={filled_quantity}, price=${buy_price}"
            )

        # Find existing parent coin or create new one
        parent_coin = None
        for coin_data in self.coin_list_data:
            if not coin_data.get("is_lot_row", False) and coin_data["symbol"] == coin:
                parent_coin = coin_data
                break

        if parent_coin:
            # Update parent coin quantities
            current_qty = float(parent_coin.get("quantity", 0))
            current_available = float(parent_coin.get("available_qty", 0))

            parent_coin["quantity"] = str(current_qty + filled_quantity)
            parent_coin["available_qty"] = str(current_available + filled_quantity)

            # Ensure the lot is in the parent's lots list
            if new_lot not in parent_coin["lots"]:
                parent_coin["lots"].append(new_lot)
        else:
            # Create new coin entry
            new_coin = {
                "symbol": coin,
                "quantity": str(filled_quantity),
                "available_qty": str(filled_quantity),
                "locked_qty": "0.0",
                "lots": [new_lot],
                "is_lot_row": False,
                "show_lots": True,
            }
            self.coin_list_data.append(new_coin)
            logger.info(f"Created new parent coin entry for {coin}")

    async def _lock_quantities_fifo(self, coin: str, quantity_to_lock: float):
        """Lock quantities using FIFO (lowest buy price first)."""
        # Find the parent coin
        parent_coin = None
        for coin_data in self.coin_list_data:
            if not coin_data.get("is_lot_row", False) and coin_data["symbol"] == coin:
                parent_coin = coin_data
                break

        if not parent_coin or not parent_coin.get("lots"):
            logger.warning(f"No lots found for {coin} to lock quantities")
            return

        # Sort lots by buy price (lowest first) for FIFO locking
        lots = parent_coin["lots"]
        lots.sort(
            key=lambda lot: (
                getattr(lot, "buy_price", 0)
                if hasattr(lot, "buy_price")
                else lot.get("buy_price", 0)
            )
        )

        remaining_to_lock = quantity_to_lock

        for lot in lots:
            if remaining_to_lock <= 0:
                break

            if hasattr(lot, "available_quantity"):  # InventoryItem object
                available = lot.available_quantity
            else:  # Dictionary (shouldn't happen with real inventory but safety check)
                available = float(lot.get("available_quantity", 0))

            # Calculate how much we can lock from this lot
            can_lock = min(available, remaining_to_lock)

            if can_lock > 0:
                # Update lot quantities
                if hasattr(lot, "available_quantity"):  # InventoryItem object
                    lot.available_quantity -= can_lock
                    lot.locked_quantity += can_lock

                    # CRITICAL FIX: Persist locked quantities to database
                    try:
                        await self.db.update_inventory_item(lot)
                        logger.debug(
                            f"Persisted lock state to database for lot {lot.id}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to persist locked quantity to database: {e}"
                        )

                remaining_to_lock -= can_lock
                logger.debug(
                    f"Locked {can_lock} from lot at price {getattr(lot, 'buy_price', 'unknown')}"
                )

        # Update parent available quantity
        total_available = sum(
            (
                getattr(lot, "available_quantity", 0)
                if hasattr(lot, "available_quantity")
                else lot.get("available_quantity", 0)
            )
            for lot in lots
        )
        total_locked = sum(
            (
                getattr(lot, "locked_quantity", 0)
                if hasattr(lot, "locked_quantity")
                else lot.get("locked_quantity", 0)
            )
            for lot in lots
        )

        parent_coin["available_qty"] = str(total_available)
        parent_coin["locked_qty"] = str(total_locked)

        logger.info(
            f"Locked {quantity_to_lock - remaining_to_lock} {coin}. Remaining available: {total_available}, Locked: {total_locked}"
        )

    async def handle_hp_buy_filled(self, event: HPBuyPositionFilled):
        """Handle HP buy position filled - add new inventory to portfolio."""
        logger.info(
            f"HP Buy Filled: {event.hp_id} - Bought {event.quantity_bought} {event.coin} at ${event.buy_price}"
        )

        # Create one inventory item per HP ID (not per price)
        inventory_id = f"hp_{event.hp_id}"

        # Check if inventory item with this HP ID already exists
        existing_item = None
        for item in self.inventory:
            if item.id == inventory_id:
                existing_item = item
                break

        if existing_item:
            # Update existing item - accumulate quantity and calculate weighted average price
            total_value = (existing_item.quantity * existing_item.buy_price) + (
                event.quantity_bought * event.buy_price
            )
            total_quantity = existing_item.quantity + event.quantity_bought
            weighted_avg_price = total_value / total_quantity

            existing_item.quantity = total_quantity
            existing_item.available_quantity += event.quantity_bought
            existing_item.buy_price = weighted_avg_price

            # CRITICAL FIX: Persist updated inventory item to database
            try:
                await self.db.update_inventory_item(existing_item)
                logger.debug(
                    f"Persisted updated inventory item to database: {inventory_id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to persist updated inventory item to database: {e}"
                )

            logger.info(
                f"Updated existing HP item {inventory_id}: new qty={existing_item.quantity}, weighted avg price=${weighted_avg_price:.2f}"
            )
            new_lot = existing_item
        else:
            # Create new inventory item for this HP ID
            new_lot = InventoryItem(
                id=inventory_id,
                coin=event.coin,
                buy_price=event.buy_price,
                quantity=event.quantity_bought,
                available_quantity=event.quantity_bought,
                locked_quantity=0.0,
                source="HP_BUY",
                timestamp=time.time(),
                notes=f"HP buy position {event.hp_id}",
            )

            # Add to main inventory list and save to database
            self.inventory.append(new_lot)

            # CRITICAL FIX: Persist new inventory item to database
            try:
                await self.db.insert_inventory_item(new_lot)
                logger.debug(
                    f"Persisted new inventory item to database: {inventory_id}"
                )
            except Exception as e:
                logger.error(f"Failed to persist new inventory item to database: {e}")

            logger.info(
                f"Created new HP item {inventory_id}: qty={event.quantity_bought}, price=${event.buy_price}"
            )

        # Find existing parent coin or create new one
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin["symbol"] == event.coin:
                parent_coin = coin
                break

        if parent_coin:
            # Add to existing coin
            parent_coin["lots"].append(new_lot)
            current_qty = float(parent_coin.get("quantity", 0))
            current_available = float(parent_coin.get("available_qty", 0))

            parent_coin["quantity"] = str(current_qty + event.quantity_bought)
            parent_coin["available_qty"] = str(
                current_available + event.quantity_bought
            )
        else:
            # Create new coin entry
            new_coin = {
                "symbol": event.coin,
                "buy_price": f"${event.buy_price}",
                "quantity": str(event.quantity_bought),
                "available_qty": str(event.quantity_bought),
                "locked_qty": "0",
                "price_usd": "0.00",
                "total_usd": "0.00",
                "pnl": "—",
                "pnl_color": [1, 1, 1, 1],
                "weighted_avg_buy_price": event.buy_price,
                "lots": [new_lot],
                "expanded": False,
                "has_lots": True,
                "portfolio_manager": self,
            }
            self.coin_list_data.append(new_coin)

        # Refresh UI (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

        logger.info(
            f"Added {event.quantity_bought} {event.coin} to portfolio from HP buy"
        )

    async def handle_hp_position_cancelled(self, event: HPPositionCancelled):
        """Handle HP position cancellation - unlock quantities that were locked."""
        logger.info(
            f"[PORTFOLIO CANCELLATION] HP Position Cancelled: {event.hp_id} - {event.position_type} {event.quantity} {event.coin}"
        )
        logger.info(f"[PORTFOLIO CANCELLATION] Test mode: {self.test_mode}")
        logger.info(
            f"[PORTFOLIO CANCELLATION] Before unlock - {event.coin} locked quantity check..."
        )

        if event.position_type == "SELL":
            # Unlock quantities that were locked for this sell position
            logger.info(
                f"[PORTFOLIO CANCELLATION] Processing SELL cancellation for {event.coin}"
            )
            await self._unlock_quantities_fifo(event.coin, event.quantity)
            logger.info(
                f"[PORTFOLIO CANCELLATION] Completed unlock operation for {event.coin}"
            )
        elif event.position_type == "BUY":
            # For buy positions, unlock the budget that was locked when orders were placed
            logger.info(
                f"[PORTFOLIO CANCELLATION] Processing BUY cancellation for {event.coin}"
            )
            await self._unlock_quantities_fifo(event.coin, event.quantity)
            logger.info(
                f"[PORTFOLIO CANCELLATION] Completed budget unlock operation for {event.coin}"
            )

        # Refresh UI (skip in test mode to avoid Kivy widget access)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def _unlock_quantities_fifo(self, coin: str, quantity_to_unlock: float):
        """Unlock quantities using FIFO (same order as locking)."""
        # Find the parent coin
        parent_coin = None
        for coin_data in self.coin_list_data:
            if not coin_data.get("is_lot_row", False) and coin_data["symbol"] == coin:
                parent_coin = coin_data
                break

        if not parent_coin or not parent_coin.get("lots"):
            logger.warning(f"No lots found for {coin} to unlock quantities")
            return

        # Sort lots by buy price (lowest first) for FIFO unlocking
        lots = parent_coin["lots"]
        lots.sort(
            key=lambda lot: (
                getattr(lot, "buy_price", 0)
                if hasattr(lot, "buy_price")
                else lot.get("buy_price", 0)
            )
        )

        remaining_to_unlock = quantity_to_unlock

        for lot in lots:
            if remaining_to_unlock <= 0:
                break

            if hasattr(lot, "locked_quantity"):  # InventoryItem object
                locked = lot.locked_quantity
            else:  # Dictionary (shouldn't happen with real inventory but safety check)
                locked = float(lot.get("locked_quantity", 0))

            # Calculate how much we can unlock from this lot
            can_unlock = min(locked, remaining_to_unlock)

            if can_unlock > 0:
                # Update lot quantities
                if hasattr(lot, "locked_quantity"):  # InventoryItem object
                    lot.locked_quantity -= can_unlock
                    lot.available_quantity += can_unlock

                    # CRITICAL FIX: Persist unlocked quantities to database
                    try:
                        await self.db.update_inventory_item(lot)
                        logger.debug(
                            f"Persisted unlock state to database for lot {lot.id}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to persist unlocked quantity to database: {e}"
                        )

                remaining_to_unlock -= can_unlock
                logger.debug(
                    f"Unlocked {can_unlock} from lot at price {getattr(lot, 'buy_price', 'unknown')}"
                )

        # Update parent available/locked quantities
        total_available = sum(
            (
                getattr(lot, "available_quantity", 0)
                if hasattr(lot, "available_quantity")
                else lot.get("available_quantity", 0)
            )
            for lot in lots
        )
        total_locked = sum(
            (
                getattr(lot, "locked_quantity", 0)
                if hasattr(lot, "locked_quantity")
                else lot.get("locked_quantity", 0)
            )
            for lot in lots
        )

        parent_coin["available_qty"] = str(total_available)
        parent_coin["locked_qty"] = str(total_locked)

        logger.info(
            f"Unlocked {quantity_to_unlock - remaining_to_unlock} {coin}. Available: {total_available}, Locked: {total_locked}"
        )

    async def _add_received_currency(self, currency: str, amount: float):
        """Add received currency (like USDC) to portfolio."""
        # Find existing currency in coin_list_data
        logger.info("Adding received currency to portfolio")
        existing_currency = None
        for coin_data in self.coin_list_data:
            if (
                not coin_data.get("is_lot_row", False)
                and coin_data["symbol"] == currency
            ):
                existing_currency = coin_data
                break

        # Find existing currency in inventory
        existing_inventory = None
        if hasattr(self, "inventory") and self.inventory:
            for item in self.inventory:
                if item.coin == currency:
                    existing_inventory = item
                    break

        if existing_currency:
            # Add to existing currency in coin_list_data
            current_qty = float(existing_currency.get("quantity", 0))
            current_available = float(existing_currency.get("available_qty", 0))

            existing_currency["quantity"] = str(current_qty + amount)
            existing_currency["available_qty"] = str(current_available + amount)

            # Also update inventory if it exists
            if existing_inventory:
                existing_inventory.available_quantity += amount
                existing_inventory.quantity = (
                    existing_inventory.available_quantity
                    + existing_inventory.locked_quantity
                )

            logger.info(
                f"Added {amount} {currency} to existing balance. New total: {current_qty + amount}"
            )
        else:
            # Create new currency entry in coin_list_data
            new_currency = {
                "symbol": currency,
                "buy_price": "—",  # Received currency doesn't have buy price
                "quantity": str(amount),
                "available_qty": str(amount),
                "locked_qty": "0",
                "price_usd": "1.00" if currency == "USDC" else "0.00",
                "total_usd": str(amount) if currency == "USDC" else "0.00",
                "pnl": "—",
                "pnl_color": [1, 1, 1, 1],
                "weighted_avg_buy_price": 0.0,
                "lots": [],
                "expanded": False,
                "has_lots": False,
                "portfolio_manager": self,
            }
            self.coin_list_data.append(new_currency)

            # Also create new inventory item if inventory exists
            if hasattr(self, "inventory") and self.inventory is not None:
                new_inventory_item = InventoryItem(
                    id=str(uuid.uuid4()),
                    coin=currency,
                    buy_price=1.0 if currency == "USDC" else 0.0,
                    quantity=amount,
                    available_quantity=amount,
                    locked_quantity=0.0,
                )
                self.inventory.append(new_inventory_item)

                # CRITICAL FIX: Persist new inventory item to database
                try:
                    await self.db.insert_inventory_item(new_inventory_item)
                    logger.debug(
                        f"Persisted new {currency} inventory item to database: {new_inventory_item.id}"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to persist new {currency} inventory item to database: {e}"
                    )

            logger.info(f"Created new {currency} entry with {amount}")
