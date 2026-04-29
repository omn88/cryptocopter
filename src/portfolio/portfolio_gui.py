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
from src.common.identifiers import (
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
    HPSell,
    HPSellConfig,
    StateInfo,
    PositionSide,
)
from src.database import Database
from src.portfolio.usd_price_resolver import UsdPriceResolver

logger = logging.getLogger(__name__)


class PortfolioUI(BoxLayout):
    virtual_positions = ListProperty([])
    saldo_usd_label = ObjectProperty(None)  # Label for USD saldo in the GUI
    saldo_btc_label = ObjectProperty(None)  # Label for BTC saldo in the GUI

    coin_list_data = ListProperty()

    def __init__(
        self,
        ui_queue: queue.Queue,
        strategy_config_queue: queue.Queue,
        price_resolver: UsdPriceResolver,
        db: Database,
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
        self.strategy_config_queue: queue.Queue = strategy_config_queue
        self.price_resolver = price_resolver
        self.coin_list_data = []
        self.inventory: List[InventoryItem] = []
        self.db = db
        self.test_mode = test_mode  # Add test_mode parameter
        self._last_refresh_time = 0.0  # Track last refresh time to throttle updates
        self._hp_currency_processed: set[str] = (
            set()
        )  # Track HP IDs that have already added currency
        self._hp_locked_amounts: Dict[str, Dict[str, float]] = (
            {}
        )  # Track locked amounts by HP ID and currency

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

    def sell_lot_button(self, lot_symbol, available_quantity, buy_price):
        """Handle sell button for individual lot (child row)."""

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

        # Find the parent coin data
        parent_coin = None
        for coin in self.coin_list_data:
            if not coin.get("is_lot_row", False) and coin["symbol"] == symbol:
                parent_coin = coin
                break

        if not parent_coin:
            logger.error("Could not find parent coin data for %s", symbol)
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

                # Create sell order via config queue
                if not self.strategy_config_queue or not self.price_resolver.symbols:
                    logger.error(
                        "Strategy config queue or symbols info not available. Cannot create sell orders."
                    )
                    # Show user-friendly error popup
                    error_popup = Popup(
                        title="Error",
                        content=Label(
                            text="Trading strategy not ready.\nCannot create sell orders at this time."
                        ),
                        size_hint=(0.4, 0.3),
                        auto_dismiss=True,
                    )
                    error_popup.open()
                    return

                popup.dismiss()  # Close our popup first

                try:
                    # Create sell configuration and send to strategy executor via config queue
                    coin_symbol = symbol[:-3] if symbol.endswith("USD") else symbol
                    symbol_key = f"{coin_symbol}USDC"

                    if symbol_key not in self.price_resolver.symbols:
                        fallback_symbol = f"{coin_symbol}USDT"
                        if fallback_symbol in self.price_resolver.symbols:
                            logger.info(
                                f"Using fallback symbol {fallback_symbol} instead of {symbol_key}"
                            )
                            symbol_key = fallback_symbol
                        else:
                            logger.error(
                                f"Symbol info not found for {symbol_key} or fallback {fallback_symbol}"
                            )
                            error_popup = Popup(
                                title="Symbol Error",
                                content=Label(
                                    text=f"Symbol {symbol_key} not supported for trading"
                                ),
                                size_hint=(0.4, 0.3),
                                auto_dismiss=True,
                            )
                            error_popup.open()
                            return

                    # Create HP sell configuration
                    sell_config = HPSell(
                        config=HPSellConfig(
                            symbol=self.price_resolver.symbols[symbol_key],
                            hp_id="",  # Empty HP ID for new position
                            coin=coin_symbol,
                            quantity=sell_quantity,
                            buy_price=avg_buy_price,
                            sell_price=sell_price,
                            end_currency="USDC",
                        ),
                        state_info=StateInfo(
                            side=PositionSide.SHORT,
                            open_time=time.strftime("%Y-%m-%d %H:%M:%S"),
                        ),
                    )

                    # Send to strategy executor via config queue
                    self.strategy_config_queue.put_nowait(sell_config)

                    logger.info(
                        f"Successfully queued sell order for {symbol}: qty={sell_quantity} @ {sell_price}"
                    )

                except Exception as e:
                    logger.error("Failed to create sell order: %s", e)
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
            logger.warning("No lots found for %s", symbol)
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
                        logger.info("Deleted lot %s from database", lot.id)
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
                        logger.info(
                            "Updated lot %s quantity to %s", lot.id, new_quantity
                        )
                    except Exception:
                        logger.exception("Failed to update lot %s in database", lot.id)
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
            logger.warning("Parent coin %s not found", symbol)
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
            logger.warning("No lots found for %s or parent coin not found", symbol)
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
            logger.info(
                "Convert operation detected: %s -> parent {parent_hp_id}", hp_id
            )

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
            logger.warning("Could not find inventory item with ID %s", lot_id_to_find)
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
                logger.error("Failed to delete inventory item from database: %s", e)

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
                logger.error("Failed to persist partial sell update to database: %s", e)

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
        logger.info("Toggling expand for %s", symbol)

        # Skip if this is a lot row (shouldn't happen but safety check)
        if symbol.startswith("  └─"):
            logger.warning("Attempted to toggle lot row: %s", symbol)
            return

        # Find the parent coin and toggle its state
        for coin_data in self.coin_list_data:
            if (
                not coin_data.get("is_lot_row", False)
                and coin_data.get("symbol") == symbol
            ):
                # Toggle this coin
                coin_data["expanded"] = not coin_data.get("expanded", False)
                logger.info("Toggled %s to expanded={coin_data['expanded']}", symbol)
                break
        else:
            logger.warning("Could not find parent coin with symbol: %s", symbol)
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
                        "available_qty": self._format_quantity(
                            lot_available, parent_coin["symbol"]
                        ),
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

        logger.debug("Rebuild complete: %s items", len(new_data))

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
            logger.debug("[PORTFOLIO GUI DEBUG] First few inventory items:")
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
                "available_qty": self._format_quantity(total_available, coin),
                "locked_qty": str(total_locked),
                "price_usd": "0.00",
                "total_usd": self._format_usd_value(total_value),
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

        # Validate final state
        if len(self.coin_list_data) == 0:
            raise RuntimeError(
                f"coin_list_data should not be empty after processing {len(inventory)} inventory items"
            )

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
                if symbol_key in self.price_resolver.symbols:
                    return self.price_resolver.symbols[symbol_key].adjust_price(
                        avg_price
                    )
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

    def _format_usd_value(self, value: float) -> str:
        """Format USD value elegantly: 0 decimals if < $1, 2 decimals if >= $1."""
        if value < 1.0:
            return f"{value:.0f}"
        return f"{value:.2f}"

    def _format_quantity(self, quantity: float, coin_symbol: str = "") -> str:
        """Format quantity using Symbol's precision rules if available.

        Args:
            quantity: The quantity to format
            coin_symbol: The coin symbol (e.g., 'BTC', 'ETH') to look up Symbol info

        Returns:
            Formatted quantity string with proper precision
        """
        if coin_symbol:
            try:
                symbol_key = f"{coin_symbol}USDT"
                if symbol_key in self.price_resolver.symbols:
                    return self.price_resolver.symbols[symbol_key].format_quantity(
                        quantity
                    )
            except (KeyError, AttributeError):
                pass

        # Fallback: use Symbol's format_quantity logic
        # For quantities < 1, show with proper precision (strip trailing zeros)
        if quantity < 1.0:
            # Show up to 8 decimal places, strip trailing zeros
            formatted = f"{quantity:.8f}".rstrip("0").rstrip(".")
            return formatted if formatted else "0"
        return f"{quantity:.2f}"

    def _get_exchange_available(self, coin: str) -> float:
        """Get real-time available quantity from exchange (sum across all lots).

        This reflects what's actually available to sell on Binance right now.
        """
        total_available = 0.0

        for item in self.inventory:
            if item.coin == coin:
                total_available += item.available_quantity

        return total_available

    def _get_exchange_locked(self, coin: str) -> float:
        """Get real-time locked quantity from exchange (sum across all lots).

        This reflects what's locked in pending orders on Binance.
        """
        total_locked = 0.0

        for item in self.inventory:
            if item.coin == coin:
                total_locked += item.locked_quantity

        return total_locked

    def _get_database_quantity(self, coin: str) -> float:
        """Get total quantity from database records (sum across all lots).

        This reflects your total portfolio tracking (Binance + external storage).
        """
        total_quantity = 0.0

        for item in self.inventory:
            if item.coin == coin:
                total_quantity += item.quantity

        return total_quantity

    def validate_sell_quantity(self, coin: str, quantity: float) -> tuple[bool, str]:
        """Validate if we can sell the requested quantity against exchange availability.

        Args:
            coin: The coin to validate
            quantity: The quantity we want to sell

        Returns:
            (is_valid, error_message) - error_message is empty string if valid
        """
        available = self._get_exchange_available(coin)

        if quantity > available:
            db_total = self._get_database_quantity(coin)
            exchange_total = available + self._get_exchange_locked(coin)

            error_msg = (
                f"Insufficient balance on exchange:\n"
                f"Requested: {quantity:.8f} {coin}\n"
                f"Available on Binance: {available:.8f} {coin}\n"
                f"Locked on Binance: {self._get_exchange_locked(coin):.8f} {coin}\n"
                f"Total in DB: {db_total:.8f} {coin}\n\n"
                f"Please transfer {(quantity - available):.8f} {coin} to Binance first."
            )
            return False, error_msg

        return True, ""

    async def update_ui(self) -> None:
        while not self.test_mode:  # Exit loop immediately in test mode
            try:
                data = self.ui_queue.get_nowait()
                # Process the data and update the UI
                await self._process_ui_event(data)
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error("[PORTFOLIO PRODUCTION] Error processing event: %s", e)
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
            logger.debug("Processed %s events in test mode", processed_count)

    async def _process_ui_event(self, data: Event) -> None:
        """Process a single UI event."""
        if not isinstance(data, Event):
            raise TypeError(f"Expected Event, got {type(data).__name__}")

        if data.name == EventName.PORTFOLIO_INVENTORY:
            logger.debug(
                f"[PORTFOLIO GUI DEBUG] Received PORTFOLIO_INVENTORY event with content type: {type(data.content)}"
            )
            if isinstance(data.content, List):
                logger.debug(
                    f"[PORTFOLIO GUI DEBUG] PORTFOLIO_INVENTORY content is list with {len(data.content)} items"
                )
            if not isinstance(data.content, List):
                raise TypeError(
                    f"Expected List for PORTFOLIO_INVENTORY, got {type(data.content).__name__}"
                )
            self.set_inventory(data.content)
        if data.name == EventName.ACCOUNT_POSITION:
            if not isinstance(data.content, AccountPosition):
                raise TypeError(
                    f"Expected AccountPosition, got {type(data.content).__name__}"
                )
            await self.handle_account_position(data.content)
        if data.name == EventName.PRICE_UPDATES:
            if not isinstance(data.content, PriceUpdates):
                raise TypeError(
                    f"Expected PriceUpdates, got {type(data.content).__name__}"
                )
            # Update saldo in USD and BTC
            await self.update_coin_prices(data.content)

        # Handle HP Manager events for quantity management
        if data.name == EventName.HP_SELL_POSITION_CREATED:
            if not isinstance(data.content, HPSellPositionCreated):
                raise TypeError(
                    f"Expected HPSellPositionCreated, got {type(data.content).__name__}"
                )
            await self.handle_hp_sell_created(data.content)
        if data.name == EventName.HP_SELL_POSITION_PARTIALLY_FILLED:
            if not isinstance(data.content, HPSellPositionPartiallyFilled):
                raise TypeError(
                    f"Expected HPSellPositionPartiallyFilled, got {type(data.content).__name__}"
                )
            await self.handle_hp_sell_partially_filled(data.content)
        if data.name == EventName.HP_SELL_POSITION_COMPLETED:
            if not isinstance(data.content, HPSellPositionCompleted):
                raise TypeError(
                    f"Expected HPSellPositionCompleted, got {type(data.content).__name__}"
                )
            await self.handle_hp_sell_completed(data.content)
        if data.name == EventName.HP_BUY_ORDERS_PLACED:
            if not isinstance(data.content, HPBuyOrdersPlaced):
                raise TypeError(
                    f"Expected HPBuyOrdersPlaced, got {type(data.content).__name__}"
                )
            await self.handle_hp_buy_orders_placed(data.content)
        if data.name == EventName.HP_BUY_POSITION_FILLED:
            if not isinstance(data.content, HPBuyPositionFilled):
                raise TypeError(
                    f"Expected HPBuyPositionFilled, got {type(data.content).__name__}"
                )
            await self.handle_hp_buy_filled(data.content)
        if data.name == EventName.HP_BUY_POSITION_PARTIALLY_FILLED:
            if not isinstance(data.content, HPBuyPositionPartiallyFilled):
                raise TypeError(
                    f"Expected HPBuyPositionPartiallyFilled, got {type(data.content).__name__}"
                )
            await self.handle_hp_buy_partially_filled(data.content)
        if data.name == EventName.HP_POSITION_CANCELLED:
            if not isinstance(data.content, HPPositionCancelled):
                raise TypeError(
                    f"Expected HPPositionCancelled, got {type(data.content).__name__}"
                )
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
                    self.price_resolver.symbols[f"{symbol}USDT"].adjust_price(price)
                )
                total_in_usd = round(float(coin["quantity"]) * price, 2)
                coin["total_usd"] = self._format_usd_value(total_in_usd)

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
        # Defensive: ensure all coins have total_usd field before sorting
        for coin in parent_coins:
            if "total_usd" not in coin:
                coin["total_usd"] = "0.00"
        parent_coins.sort(key=lambda x: float(x.get("total_usd", "0.00")), reverse=True)

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
                        "available_qty": self._format_quantity(
                            lot_available, parent_coin["symbol"]
                        ),
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
        total_usd = sum([float(coin.get("total_usd", "0")) for coin in parent_coins])
        self.saldo_usd_label = float(self._format_usd_value(total_usd))
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

    async def handle_account_position(self, account_position: AccountPosition) -> None:
        """Handle account position updates - sync exchange balances to inventory.

        In production: Backend (portfolio.py) handles this + GUI for redundancy.
        In tests: Only GUI handles this (no backend running).
        """
        logger.info(
            "Syncing exchange balances to inventory from AccountPosition update"
        )

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

        # Refresh UI to show updated quantities (skip in test mode)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

        logger.debug("Account position update processed - inventory quantities synced")

    async def handle_hp_sell_created(self, event: HPSellPositionCreated):
        """Handle HP sell position creation - immediately lock quantities proportionally.

        In production: Exchange locks quantities and WebSocket AccountPosition updates inventory.
        In tests: We need immediate local locking since there's no real exchange.
        """
        logger.info(
            f"HP Sell Created: {event.hp_id} - {event.coin} qty:{event.quantity}"
        )

        # Immediately lock quantities locally (for tests and early feedback)
        coin_items = [item for item in self.inventory if item.coin == event.coin]

        if not coin_items:
            logger.warning(f"Cannot lock {event.coin} - no inventory items found")
            return

        # Calculate total available quantity across all lots
        total_available = sum(item.available_quantity for item in coin_items)

        if total_available < event.quantity:
            logger.warning(
                f"Cannot lock {event.quantity} {event.coin} - only {total_available} available"
            )
            return

        # Lock quantities proportionally across lots based on their available amounts
        remaining_to_lock = event.quantity
        for item in coin_items:
            if remaining_to_lock <= 0:
                break

            if item.available_quantity > 0:
                # Lock from this lot proportionally or up to its available amount
                lock_amount = min(item.available_quantity, remaining_to_lock)
                item.available_quantity -= lock_amount
                item.locked_quantity += lock_amount
                remaining_to_lock -= lock_amount

                logger.debug(
                    f"Locked {lock_amount} {event.coin} from lot {item.id} "
                    f"(available: {item.available_quantity + lock_amount:.8f} -> {item.available_quantity:.8f}, "
                    f"locked: {item.locked_quantity - lock_amount:.8f} -> {item.locked_quantity:.8f})"
                )

        logger.info(
            f"Locked {event.quantity} {event.coin} across {len(coin_items)} lots"
        )

        # NOTE: Exchange will also lock on its side and send AccountPosition update.
        # When that arrives, handle_account_position() will sync to exchange state.
        # The local locking here provides immediate feedback and works for tests.

        # Refresh UI (skip in test mode)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def handle_hp_buy_orders_placed(self, event: HPBuyOrdersPlaced):
        """Handle HP buy orders placed - immediately lock budget.

        In production: Exchange locks budget and WebSocket AccountPosition updates inventory.
        In tests: We need immediate local locking since there's no real exchange.
        """
        logger.info(
            f"HP Buy Orders Placed: {event.hp_id} - {event.budget_amount} {event.end_currency}"
        )

        # Immediately lock budget locally (for tests and early feedback)
        currency_items = [
            item for item in self.inventory if item.coin == event.end_currency
        ]

        if not currency_items:
            logger.warning(
                f"Cannot lock {event.end_currency} budget - no inventory items found"
            )
            return

        # Calculate total available across all lots
        total_available = sum(item.available_quantity for item in currency_items)

        if total_available < event.budget_amount:
            logger.warning(
                f"Cannot lock {event.budget_amount} {event.end_currency} - only {total_available} available"
            )
            return

        # Lock budget proportionally across lots
        remaining_to_lock = event.budget_amount
        for item in currency_items:
            if remaining_to_lock <= 0:
                break

            if item.available_quantity > 0:
                lock_amount = min(item.available_quantity, remaining_to_lock)
                item.available_quantity -= lock_amount
                item.locked_quantity += lock_amount
                remaining_to_lock -= lock_amount

                logger.debug(
                    f"Locked {lock_amount} {event.end_currency} from lot {item.id} "
                    f"(available: {item.available_quantity + lock_amount:.8f} -> {item.available_quantity:.8f}, "
                    f"locked: {item.locked_quantity - lock_amount:.8f} -> {item.locked_quantity:.8f})"
                )

        logger.info(f"Locked {event.budget_amount} {event.end_currency} budget")

        # NOTE: Exchange will also lock on its side and send AccountPosition update.
        # When that arrives, handle_account_position() will sync to exchange state.

        # Refresh UI to prepare for exchange sync (skip in test mode)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

    async def handle_hp_sell_partially_filled(
        self, event: HPSellPositionPartiallyFilled
    ):
        """Handle HP sell partial fill - reduce inventory and redistribute locks."""
        logger.info(
            f"HP Sell Partially Filled: {event.hp_id} - {event.coin} filled:{event.filled_quantity} (total filled:{event.total_filled})"
        )

        # Reduce inventory by the filled quantity using HP-specific lot reduction
        await self._update_lots_after_hp_sell(
            event.hp_id, event.coin, event.filled_quantity
        )

        logger.info(
            f"Exchange will update locked amounts for {event.coin} - waiting for account update"
        )

        # NOTE: We don't manually redistribute locks.
        # Binance WebSocket will send updated account position with new locked amounts
        # after the fill, which will be synced to inventory via handle_account_position.

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
                logger.info("Adding currency for final multihop child %s", event.hp_id)
            elif is_direct_sell_child:
                # Direct sell child (e.g., "1000_SELL")
                should_add_currency = True
                logger.info("Adding currency for direct sell child %s", event.hp_id)
            elif is_pure_digit_id and is_likely_direct_sell:
                # For direct sells with pure digit IDs, we add currency since there's only one completion event
                should_add_currency = True
                logger.info("Adding currency for direct sell %s", event.hp_id)
            elif is_pure_digit_id:
                # For pure digit IDs that are NOT direct trading pairs, this is likely a convert operation
                # Convert operations use a single HP ID and should receive the currency directly
                should_add_currency = True
                logger.info("Adding currency for convert operation %s", event.hp_id)
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

        logger.info(
            f"Exchange will clear locks for {event.coin} after completion - waiting for account update"
        )

        # NOTE: We don't manually clear locks.
        # Binance WebSocket will send updated account position with unlocked amounts
        # after completion, synced via handle_account_position.

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
                logger.error("Failed to persist new inventory item to database: %s", e)

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
            logger.info("Created new parent coin entry for %s", coin)

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
                logger.error("Failed to persist new inventory item to database: %s", e)

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

        # Reduce quote currency inventory by the amount spent (total_cost)
        # Extract quote currency from the symbol (e.g., ETHUSDC -> USDC)
        quote_currency = self._extract_quote_currency_for_coin(event.coin, event.symbol)
        await self._reduce_spent_currency_and_unlock_remaining(
            quote_currency, event.total_cost, event.hp_id
        )

        logger.info(
            f"Added {event.quantity_bought} {event.coin} to portfolio from HP buy"
        )

    def _extract_quote_currency_for_coin(self, coin: str, symbol: str) -> str:
        """Extract the quote currency from the trading symbol by removing the coin part."""
        # For symbol like ETHUSDC, remove ETH to get USDC
        # For symbol like BTCUSDT, remove BTC to get USDT
        if symbol.startswith(coin):
            quote_currency = symbol[len(coin) :]
            logger.debug(
                f"Extracted quote currency '{quote_currency}' from symbol '{symbol}' for coin '{coin}'"
            )
            return quote_currency

        # Fallback to USDC if we can't extract properly
        logger.warning(
            f"Could not extract quote currency from symbol '{symbol}' for coin '{coin}', defaulting to USDC"
        )
        return "USDC"

    async def _reduce_spent_currency(self, currency: str, amount: float):
        """Reduce spent currency (like USDC) from portfolio - mirrors _add_received_currency."""
        logger.info("Reducing spent currency from portfolio: %s {currency}", amount)

        # Find existing currency in coin_list_data
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
            # Reduce from existing currency in coin_list_data
            current_qty = float(existing_currency.get("quantity", 0))
            current_locked = float(existing_currency.get("locked_qty", 0))

            new_total = max(0, current_qty - amount)
            new_locked = max(0, current_locked - amount)

            existing_currency["quantity"] = str(new_total)
            existing_currency["locked_qty"] = str(new_locked)

            # Also update inventory if it exists
            if existing_inventory:
                existing_inventory.quantity = max(
                    0, existing_inventory.quantity - amount
                )
                existing_inventory.locked_quantity = max(
                    0, existing_inventory.locked_quantity - amount
                )

                # Update database
                try:
                    await self.db.update_inventory_item(existing_inventory)
                    logger.debug(
                        f"Updated {currency} inventory item {existing_inventory.id} in database"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to update {currency} inventory item in database: {e}"
                    )

            logger.info(
                f"Reduced {amount} {currency} from existing balance. New total: {new_total}, locked: {new_locked}"
            )
        else:
            logger.warning(
                f"{currency} not found in portfolio - cannot reduce {amount}"
            )
            return

    async def _reduce_spent_currency_and_unlock_remaining(
        self, currency: str, actual_spent: float, hp_id: str
    ):
        """
        Reduce spent currency and unlock remaining locked amount for completed HP buy.

        This method:
        1. Reduces total currency by the actual amount spent
        2. Unlocks ALL locked amounts for this HP ID (since the trade is complete)

        Args:
            currency: The quote currency (e.g., USDC)
            actual_spent: The actual amount spent on the trade
            hp_id: The HP ID to unlock remaining budget for
        """
        logger.info(
            f"Processing HP buy completion: {actual_spent} {currency} spent for HP {hp_id}"
        )

        # Check if we have locked amount tracking for this HP ID
        locked_amount = 0.0
        if (
            hp_id in self._hp_locked_amounts
            and currency in self._hp_locked_amounts[hp_id]
        ):
            locked_amount = self._hp_locked_amounts[hp_id][currency]
            logger.debug(
                f"Found tracked locked amount: {locked_amount} {currency} for HP {hp_id}"
            )
        else:
            logger.warning(
                f"No locked amount tracking found for HP {hp_id} and currency {currency}"
            )

        # Find existing currency in coin_list_data
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
            current_total = float(existing_currency.get("quantity", 0))
            current_locked = float(existing_currency.get("locked_qty", 0))

            # Reduce total by actual amount spent
            new_total = max(0, current_total - actual_spent)

            # Unlock the full locked amount for this HP (since trade is complete)
            remaining_to_unlock = locked_amount if locked_amount > 0 else actual_spent
            new_locked = max(0, current_locked - remaining_to_unlock)

            # Calculate new available quantity (total - locked)
            new_available = new_total - new_locked

            existing_currency["quantity"] = str(new_total)
            existing_currency["locked_qty"] = str(new_locked)
            existing_currency["available_qty"] = str(new_available)

            logger.info(
                f"HP {hp_id} completed - {currency}: spent {actual_spent}, unlocked {remaining_to_unlock}"
            )
            current_available = float(existing_currency.get("available_qty", 0))
            logger.info(
                f"{currency} updated: total {current_total:.2f} -> {new_total:.2f}, locked {current_locked:.2f} -> {new_locked:.2f}, available {current_available:.2f} -> {new_available:.2f}"
            )

            # Also update inventory if it exists
            if existing_inventory:
                existing_inventory.quantity = max(
                    0, existing_inventory.quantity - actual_spent
                )
                existing_inventory.locked_quantity = max(
                    0, existing_inventory.locked_quantity - remaining_to_unlock
                )

                # Update database
                try:
                    await self.db.update_inventory_item(existing_inventory)
                    logger.debug(
                        f"Updated {currency} inventory item {existing_inventory.id} in database"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to update {currency} inventory item in database: {e}"
                    )

            # Clean up tracking for this HP ID
            if hp_id in self._hp_locked_amounts:
                if currency in self._hp_locked_amounts[hp_id]:
                    del self._hp_locked_amounts[hp_id][currency]
                if not self._hp_locked_amounts[
                    hp_id
                ]:  # Remove HP ID if no currencies left
                    del self._hp_locked_amounts[hp_id]
                logger.debug("Cleaned up locked amount tracking for HP %s", hp_id)

        else:
            logger.warning(
                f"{currency} not found in portfolio - cannot process HP completion for {hp_id}"
            )
            return

    async def handle_hp_position_cancelled(self, event: HPPositionCancelled):
        """Handle HP position cancellation - immediately unlock quantities.

        In production: Exchange unlocks and WebSocket AccountPosition updates inventory.
        In tests: We need immediate local unlocking since there's no real exchange.
        """
        logger.info(
            f"HP Position Cancelled: {event.hp_id} - {event.position_type} {event.quantity} {event.coin}"
        )

        # Immediately unlock quantities locally (for tests and early feedback)
        coin_items = [item for item in self.inventory if item.coin == event.coin]

        if not coin_items:
            logger.warning(f"Cannot unlock {event.coin} - no inventory items found")
            return

        # Calculate total locked quantity across all lots
        total_locked = sum(item.locked_quantity for item in coin_items)

        if total_locked < event.quantity:
            logger.warning(
                f"Cannot unlock {event.quantity} {event.coin} - only {total_locked} locked"
            )
            # Unlock what we have
            unlock_amount = total_locked
        else:
            unlock_amount = event.quantity

        # Unlock quantities proportionally across lots based on their locked amounts
        remaining_to_unlock = unlock_amount
        for item in coin_items:
            if remaining_to_unlock <= 0:
                break

            if item.locked_quantity > 0:
                # Unlock from this lot proportionally or up to its locked amount
                unlock_from_lot = min(item.locked_quantity, remaining_to_unlock)
                item.locked_quantity -= unlock_from_lot
                item.available_quantity += unlock_from_lot
                remaining_to_unlock -= unlock_from_lot

                logger.debug(
                    f"Unlocked {unlock_from_lot} {event.coin} from lot {item.id} "
                    f"(locked: {item.locked_quantity + unlock_from_lot:.8f} -> {item.locked_quantity:.8f}, "
                    f"available: {item.available_quantity - unlock_from_lot:.8f} -> {item.available_quantity:.8f})"
                )

        logger.info(
            f"Unlocked {unlock_amount} {event.coin} across {len(coin_items)} lots"
        )

        # NOTE: Exchange will also unlock on its side and send AccountPosition update.
        # When that arrives, handle_account_position() will sync to exchange state.
        # The local unlocking here provides immediate feedback and works for tests.

        # Refresh UI (skip in test mode)
        if not self.test_mode:
            self._rebuild_coin_list_with_lots()
            self.ids.coin_list.refresh_from_data()

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

            logger.info("Created new %s entry with {amount}", currency)
