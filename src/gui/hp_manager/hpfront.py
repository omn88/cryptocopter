import asyncio
import csv
import os
import queue
import logging
import time
from typing import Any, Dict, List, Set, Optional, Union
import uuid
from kivy.properties import (
    ListProperty,
    ObjectProperty,
)

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from src.database import TradingDatabase
from src.identifiers import (
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    AllTickers,
    Event,
    EventName,
    HPSellData,
    InventoryItem,
    RemoveRecord,
    State,
    StateInfo,
    UiState,
    BinanceClient,
    Mode,
    PositionSide,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import (
    HPGuiDataBuy,
    HPGuiDataSell,
    HPUpdate,
)
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.gui.hp_manager import HPConfiguration


logger = logging.getLogger("HPFront")


class HpFront(BoxLayout):
    hp_list_data: List[Dict] = ListProperty([])
    expanded_hp_ids: Set[str] = set()  # Track which parent HPs are expanded

    # HP List state filter - default excludes CLOSED and SOLD
    hp_state_filter = ListProperty(
        [
            "NEW",
            "BUYING",
            "PARTIALLY_BOUGHT",
            "BOUGHT",
            "READY_TO_SELL",
            "SELLING",
            "PARTIALLY_SOLD",
            "PART_SOLD_PART_BOUGHT",
            "SOLD_PART_BOUGHT",
            "WAITING_CHILD",
            "NONE",
        ]
    )

    log_display = ObjectProperty(None)
    file_name_input = ObjectProperty(None)
    symbols = ListProperty()

    config_dir = os.path.join("src", "strategies", "spot")

    def __init__(
        self,
        client: BinanceClient,
        strategy_id: str,
        config_queue: queue.Queue,
        ui_queue: queue.Queue,
        symbols_info: Dict[str, SymbolInfo],
        db: TradingDatabase,
        price_resolver: UsdPriceResolver,
        portfolio_queue: queue.Queue,
        test_mode=False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.symbols_info = symbols_info
        self.client = client
        self.strategy_id = strategy_id
        self.ui_queue = ui_queue
        self.config_queue = config_queue
        self.db = db
        self.bind(hp_list_data=self._update_hp_list_view)
        self.symbols = [symbol for symbol, info in self.symbols_info.items()]
        self.test_mode = test_mode
        self.stop_event: asyncio.Event = asyncio.Event()
        self.ui_queue_closed = False
        self.price_resolver = price_resolver
        self.portfolio_queue = portfolio_queue

        # Initialize task references for proper cleanup
        self.queue_task: Optional[asyncio.Task] = None
        self._syncing_hp_data = False  # Prevent sync loops

        # Add logging throttling for frequent operations
        self._last_ticker_log_time = 0.0
        self._last_ui_queue_log_time = 0.0
        self._last_view_update_time = 0.0

        # Suppress GUI initialization when in test mode
        if not self.test_mode:
            # Initialize Unified HP Manager (will be set by KV file)
            self.hp_manager = None

    def initialize(self):
        self.queue_task = asyncio.create_task(self.process_ui_queue())

        # Initialize the HP list view
        if hasattr(self, "ids") and hasattr(self.ids, "hp_list_container"):
            # Trigger initial HP list update
            self._update_hp_list_view()

        # Setup the unified HP manager
        self.setup_hp_manager()

        # Note: CSV auto-loading is now handled by portfolio_gui.py in proper priority order

    def show_buy_modal(self):
        """Show Buy HP modal - delegates to HP manager."""
        if hasattr(self, "hp_manager") and self.hp_manager:
            self.hp_manager.show_buy_modal()
        else:
            logger.warning("HP manager not available for buy modal")

    def show_sell_modal(self):
        """Show Sell HP modal - delegates to HP manager."""
        if hasattr(self, "hp_manager") and self.hp_manager:
            self.hp_manager.show_sell_modal()
        else:
            logger.warning("HP manager not available for sell modal")

    def show_cancel_confirmation(self, hp_id: str, symbol: str, side: str) -> None:
        """Show confirmation dialog for canceling HP position."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.label import Label

        content = BoxLayout(orientation="vertical", spacing=10, padding=10)

        # Warning message
        warning_text = f"""Are you sure you want to CANCEL position {hp_id}?

This action will:
• Cancel all remaining orders on the exchange
• Close the position with status CLOSED
• This action cannot be undone

Position: {hp_id} ({symbol})
Side: {side}"""

        warning_label = Label(
            text=warning_text,
            halign="center",
            valign="middle",
            text_size=(None, None),
            color=[1, 0.8, 0.2, 1],  # Yellow warning color
        )
        warning_label.bind(size=warning_label.setter("text_size"))
        content.add_widget(warning_label)

        # Buttons
        button_layout = BoxLayout(
            orientation="horizontal", spacing=10, size_hint_y=None, height=50
        )

        cancel_btn = Button(text="Cancel", background_color=[0.5, 0.5, 0.5, 1])
        confirm_btn = Button(text="CONFIRM CANCEL", background_color=[0.8, 0.2, 0.2, 1])

        button_layout.add_widget(cancel_btn)
        button_layout.add_widget(confirm_btn)
        content.add_widget(button_layout)

        popup = Popup(
            title="Cancel HP Position - CONFIRMATION REQUIRED",
            content=content,
            size_hint=(0.6, 0.5),
            auto_dismiss=False,
            title_color=[1, 0.8, 0.2, 1],
        )

        # Button actions
        cancel_btn.bind(on_release=popup.dismiss)
        confirm_btn.bind(
            on_release=lambda x: self._confirm_cancel_hp(popup, hp_id, symbol, side)
        )

        popup.open()

    def _confirm_cancel_hp(self, popup, hp_id: str, symbol: str, side: str) -> None:
        """Actually cancel the HP position after confirmation."""
        popup.dismiss()
        # Use PositionSide enum correctly
        if side == "LONG":
            position_side = PositionSide.LONG
        else:
            position_side = PositionSide.LONG  # Default to LONG for buy positions

        record = RemoveRecord(hp_id=hp_id, symbol=symbol, side=position_side)
        self.config_queue.put_nowait(record)
        logger.info("Remove record added to the queue. %s", record)

    def trigger_remove_record(
        self,
        hp_id: str,
        symbol: str,
        side: str,
        *args,
    ) -> None:
        # Handle PositionSide enum correctly
        if side == "LONG":
            position_side = PositionSide.LONG
        elif side == "SHORT":
            position_side = PositionSide.SHORT
        else:
            position_side = PositionSide.LONG  # Default to LONG

        record = RemoveRecord(hp_id=hp_id, symbol=symbol, side=position_side)
        self.config_queue.put_nowait(record)
        logger.info("Remove record added to the queue. %s", record)

    # Unified HP Manager callback methods
    def setup_hp_manager(self):
        """Setup the unified HP manager with callbacks."""
        # Get the unified HP manager from the KV file
        if hasattr(self, "ids") and hasattr(self.ids, "hp_manager"):
            self.hp_manager = self.ids.hp_manager

            # Set up callbacks
            self.hp_manager.create_hp_callback = self.on_unified_create_hp
            self.hp_manager.cancel_hp_callback = self.on_unified_cancel_hp
            self.hp_manager.remove_hp_callback = self.on_unified_remove_hp

            # Set symbols_info and client for HP manager integration
            self.hp_manager.symbols_info = self.symbols_info
            self.hp_manager.client = self.client

            # Update with current data
            self.hp_manager.update_symbols(self.symbols)
            self._sync_hp_manager_data()
        else:
            logger.warning("HP manager not found in KV file")

    def on_unified_create_hp(self, hp_type: str, config: HPConfiguration):
        """Handle HP creation from unified manager."""
        try:
            if hp_type == "BUY":
                self._create_buy_hp_from_config(config)
            elif hp_type == "SELL":
                self._create_sell_hp_from_config(config)
            else:
                logger.error(f"Unknown HP type: {hp_type}")
        except Exception as e:
            logger.error(f"Error creating {hp_type} HP: {e}")

    def _create_buy_hp_from_config(self, config: HPConfiguration):
        """Create Buy HP from unified configuration."""
        if not self.symbols_info.get(config.symbol):
            logger.error(f"Symbol info not found for {config.symbol}")
            return

        new_hp = HPBuyData(
            config=HPBuyConfig(
                coin=config.coin,
                symbol_info=self.symbols_info[config.symbol],
                price_low=config.price_low or 0.0,
                price_high=config.price_high or 0.0,
                budget=config.budget or 1000.0,
                order_trigger=(
                    config.order_trigger / 100.0 if config.order_trigger else 0.01
                ),
                mode=Mode.DCA if config.mode == "DCA" else Mode.SINGLE,
            ),
            state_info=StateInfo(),
        )
        self.config_queue.put_nowait(new_hp)
        logger.info("Buy HP created from unified manager: %s", new_hp)

    def _create_sell_hp_from_config(self, config: HPConfiguration):
        """Create Sell HP from unified configuration."""
        if not self.symbols_info.get(config.symbol):
            logger.error(f"Symbol info not found for {config.symbol}")
            return

        sell_config = HPSellData(
            config=HPSellConfig(
                hp_id=config.hp_id if config.hp_id else str(uuid.uuid4())[:8],
                coin=config.coin,
                buy_price=0.0,  # Will be updated from actual data
                sell_price=config.sell_price or 0.0,
                quantity=config.quantity or 0.0,
                end_currency=config.end_currency or "USDC",
                symbol_info=self.symbols_info[config.symbol],
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.config_queue.put_nowait(sell_config)
        logger.info("Sell HP created from unified manager: %s", sell_config.config)

    def on_unified_cancel_hp(self, hp_id: str, hp_type: str):
        """Handle HP cancellation from unified manager."""
        try:
            if hp_type.upper() == "BUY":
                side = PositionSide.LONG
                symbol = self._get_symbol_from_hp_id(hp_id)
            else:  # SELL
                side = PositionSide.SHORT
                symbol = self._get_symbol_from_hp_id(hp_id)

            if symbol:
                self.trigger_remove_record(hp_id, symbol, side.value)
            else:
                logger.error(f"Could not find symbol for HP ID: {hp_id}")
        except Exception as e:
            logger.error(f"Error cancelling HP {hp_id}: {e}")

    def on_unified_remove_hp(self, hp_id: str, hp_type: str):
        """Handle HP removal from unified manager."""
        # For now, use same logic as cancel
        self.on_unified_cancel_hp(hp_id, hp_type)

    def _get_symbol_from_hp_id(self, hp_id: str) -> Optional[str]:
        """Get symbol from HP ID by searching HP list data."""
        for hp_data in self.hp_list_data:
            if hp_data.get("hp_id") == hp_id:
                return hp_data.get("symbol", hp_data.get("coin"))
        return None

    def _sync_hp_manager_data(self):
        """Sync current HP data with HP manager."""
        if not self.hp_manager:
            logger.warning("No HP manager available for sync")
            return

        # Prevent sync loops
        if getattr(self, "_syncing_hp_data", False):
            return

        self._syncing_hp_data = True
        try:
            logger.info(f"Syncing {len(self.hp_list_data)} HP positions to HP manager")

            # Preserve expansion state before clearing
            expanded_hp_ids = self.hp_manager.hp_data.expanded_hp_ids.copy()

            # Clear existing data
            self.hp_manager.clear_all_positions()

            # Restore expansion state
            self.hp_manager.hp_data.expanded_hp_ids = expanded_hp_ids

            # Directly add positions without complex categorization - this is dev data
            for hp_data in self.hp_list_data:
                try:
                    hp_id = hp_data.get("hp_id", "")
                    is_child = hp_data.get("is_child", False)

                    if is_child:
                        # Determine child type based on side
                        side = hp_data.get("side", "BUY")
                        child_type = "BUY" if side in ["BUY", "LONG"] else "SELL"
                        self.hp_manager.add_hp_position(child_type, hp_id, hp_data)
                        logger.debug(f"Added child: {hp_id} (type: {child_type})")
                    else:
                        # Parent container
                        self.hp_manager.add_hp_position("HP", hp_id, hp_data)
                        logger.debug(f"Added parent: {hp_id}")

                except Exception as e:
                    logger.error(f"Error adding HP position {hp_data}: {e}")

            logger.info("HP manager sync completed")
        finally:
            self._syncing_hp_data = False

    def _determine_hp_type_from_data(self, hp_data: Dict) -> Optional[str]:
        """Determine HP type from existing HP data."""
        side = hp_data.get("side", "").upper()
        state = hp_data.get("state", "").upper()

        # First check side information (most reliable)
        if side == "LONG" or "BUY" in side:
            return "BUY"
        elif side == "SHORT" or "SELL" in side:
            return "SELL"

        # Fallback to state analysis
        if any(x in state for x in ["BUY", "BOUGHT"]):
            return "BUY"
        elif any(x in state for x in ["SELL", "SOLD"]):
            return "SELL"

        # Default to BUY if unclear
        return "BUY"

    def _get_buy_child_state(self, update: HPUpdate) -> str:
        """Get appropriate state for buy child based on parent state and buy completion status."""
        parent_state = update.state.value

        # Map parent states to appropriate buy child states
        if parent_state in ["NEW", "BUYING"]:
            return parent_state
        elif parent_state in ["PARTIALLY_BOUGHT"]:
            return "PARTIALLY_BOUGHT"
        elif parent_state in ["BOUGHT"]:
            return "BOUGHT"
        elif parent_state in ["SELLING", "PARTIALLY_SOLD", "SOLD"]:
            # When selling, buy child should maintain its buy completion state
            # If we have quantity, we were partially bought; if no quantity, we were never bought
            if update.quantity and update.quantity > 0:
                return "PARTIALLY_BOUGHT"
            else:
                return "NEW"  # Edge case: no quantity means nothing was bought
        elif parent_state in ["SOLD_PART_BOUGHT"]:
            # For SOLD_PART_BOUGHT, use total_quantity to check original buy completion
            # quantity=0 (all sold) but total_quantity shows what was originally bought
            if (
                hasattr(update, "total_quantity")
                and update.total_quantity
                and update.total_quantity > 0
            ):
                return "PARTIALLY_BOUGHT"
            else:
                return "NEW"
        elif parent_state in ["PART_SOLD_PART_BOUGHT"]:
            # Complex parent state: buy child should show its buy operation status
            if update.quantity and update.quantity > 0:
                return "PARTIALLY_BOUGHT"
            else:
                return "NEW"
        else:
            # For any other complex states, determine appropriate buy state
            # based on quantity (if we have quantity, we completed some buy orders)
            if update.quantity and update.quantity > 0:
                return "PARTIALLY_BOUGHT"
            else:
                return "NEW"

    def _log_and_return_buy_child_state(self, update: HPUpdate) -> str:
        """Helper method to log and return buy child state."""
        state = self._get_buy_child_state(update)
        logger.debug(
            f"[BUY CHILD] Setting state to: {state} for quantity: {update.quantity}"
        )
        return state

    def _get_sell_child_state_from_update(self, update: HPUpdate) -> str:
        """Get sell child state, prioritizing sell operation state from update."""
        # Check if we have specific sell state information in the update
        logger.info(
            f"_get_sell_child_state_from_update: hasattr(update, 'sell_state')={hasattr(update, 'sell_state')}"
        )
        if hasattr(update, "sell_state"):
            logger.info(
                f"_get_sell_child_state_from_update: sell_state={getattr(update, 'sell_state', None)}"
            )

        if hasattr(update, "sell_state") and update.sell_state:
            sell_state = update.sell_state
            logger.info(
                f"_get_sell_child_state_from_update: Using sell_state={sell_state}"
            )
            if sell_state in ["NEW"]:
                return "SELLING"  # Active sell order
            elif sell_state in ["PARTIALLY_SOLD"]:
                return "PARTIALLY_SOLD"
            elif sell_state in ["SOLD", "FILLED"]:
                return "SOLD"

        # Fall back to parent state logic
        logger.info(
            f"_get_sell_child_state_from_update: Falling back to parent state logic"
        )
        return self._get_sell_child_state(update)

    def _get_sell_child_state(self, update: HPUpdate, sell_data=None) -> str:
        """Get appropriate state for sell child based on parent state and sell operation status."""
        parent_state = update.state.value

        # If we have sell data with state info, prioritize that for sell child state
        if (
            sell_data
            and hasattr(sell_data, "data")
            and hasattr(sell_data.data, "state_info")
        ):
            sell_state = sell_data.data.state_info.state.value
            if sell_state in ["NEW"]:
                return "SELLING"  # Active sell order
            elif sell_state in ["PARTIALLY_SOLD"]:
                return "PARTIALLY_SOLD"
            elif sell_state in ["SOLD", "FILLED"]:
                return "SOLD"
            # If no specific sell state, fall back to parent state logic

        # Map parent states to appropriate sell child states
        if parent_state in ["SELLING"]:
            return "SELLING"
        elif parent_state in ["PARTIALLY_SOLD"]:
            return "PARTIALLY_SOLD"
        elif parent_state in ["SOLD"]:
            return "SOLD"
        elif parent_state in ["PART_SOLD_PART_BOUGHT"]:
            # Complex parent state: sell child should show its sell operation status
            # Since we're in this state, some selling happened, so likely PARTIALLY_SOLD
            return "PARTIALLY_SOLD"
        else:
            # For other states where selling is active, default to SELLING
            if any(
                sell_indicator in parent_state for sell_indicator in ["SELL", "SOLD"]
            ):
                return "SELLING"
            else:
                return "NEW"

    async def process_ui_queue(self) -> None:
        logger.info("Ready to process UI queue")
        while not self.stop_event.is_set():
            try:
                while True:
                    data = self.ui_queue.get_nowait()

                    # Throttle frequent ticker update logs to reduce spam
                    current_time = time.time()
                    if isinstance(data, Event) and data.name == EventName.ALL_TICKERS:
                        # Only log ticker events every 10 seconds
                        if current_time - self._last_ticker_log_time > 10.0:
                            logger.debug("[PROCESS_UI_QUEUE] Processing ticker updates")
                            self._last_ticker_log_time = current_time

                    if isinstance(data, HPGuiDataBuy):
                        # Update the HP list with buy position data
                        # Add side information to the update
                        data.hp_update.side = data.data.state_info.side.value
                        # Update HP list data (KV binding will handle UI updates)
                        self.hp_list_data = self.update_hp_list(
                            update=data.hp_update, hp_list=self.hp_list_data
                        )
                    elif isinstance(data, HPGuiDataSell):
                        # Update the HP list with sell position data
                        logger.debug("UI received SELL position data: %s", data)
                        logger.debug(
                            f"Data type check: {type(data)}, isinstance result: {isinstance(data, HPGuiDataSell)}"
                        )
                        # Add side information to the update
                        data.hp_update.side = data.data.state_info.side.value
                        # Add sell completeness information for collapse logic
                        data.hp_update.sell_completeness = (
                            data.data.state_info.completeness
                        )
                        data.hp_update.sell_state = data.data.state_info.state.value
                        self.hp_list_data = self.update_hp_list(
                            update=data.hp_update, hp_list=self.hp_list_data
                        )
                    elif isinstance(data, Event) and data.name == EventName.ALL_TICKERS:
                        assert isinstance(data.content, AllTickers)
                        self._process_all_tickers(data.content)
                    else:
                        # Debug: Check what data type we received that doesn't match any expected type
                        logger.debug(
                            f"[UNMATCHED DATA TYPE] Received data of type: {type(data)}"
                        )
                        if hasattr(data, "__class__"):
                            logger.debug(
                                f"[UNMATCHED DATA TYPE] Class name: {data.__class__.__name__}"
                            )
                            logger.debug(
                                f"[UNMATCHED DATA TYPE] Module: {data.__class__.__module__}"
                            )
                        if hasattr(data, "hp_update") and hasattr(data, "data"):
                            logger.debug(
                                f"[UNMATCHED DATA TYPE] Looks like HPGuiDataSell but isinstance failed"
                            )
                            logger.debug(
                                f"[UNMATCHED DATA TYPE] HPGuiDataSell class: {HPGuiDataSell}"
                            )
                            logger.debug(
                                f"[UNMATCHED DATA TYPE] HPGuiDataSell module: {HPGuiDataSell.__module__}"
                            )
                            logger.debug(
                                f"[UNMATCHED DATA TYPE] Data class module: {data.__class__.__module__}"
                            )
                            # Try to process it anyway
                            if hasattr(data, "data") and hasattr(
                                data.data, "state_info"
                            ):
                                data.hp_update.side = data.data.state_info.side.value
                                data.hp_update.sell_completeness = (
                                    data.data.state_info.completeness
                                )
                                data.hp_update.sell_state = (
                                    data.data.state_info.state.value
                                )
                                self.hp_list_data = self.update_hp_list(
                                    update=data.hp_update, hp_list=self.hp_list_data
                                )
            except queue.Empty:
                await asyncio.sleep(0.1)
        self.ui_queue_closed = True

    def update_hp_list(self, update: HPUpdate, hp_list: List[Dict]) -> List[Dict]:
        """Update HP list with new container-based approach.

        Every position creates:
        - Regular Buy+Sell: Parent + {parent_id}_BUY + {parent_id}_SELL
        - Two-hop Sell: Parent + {parent_id}a + {parent_id}b
        - Convert Sell: Parent + {parent_id}_SELL
        """
        hp_id = update.hp_id

        # Detect child type with strict patterns
        is_multihop_child = self._is_multihop_child(hp_id)
        is_regular_child = self._is_regular_child(hp_id)

        # Get base HP ID based on child type
        if is_multihop_child:
            base_hp_id = hp_id[:-1]  # Remove 'a', 'b' suffix
        elif is_regular_child:
            base_hp_id = hp_id.split("_")[0]  # Remove '_BUY', '_SELL' suffix
        else:
            base_hp_id = hp_id  # Parent position

        hp_map: Dict[str, Dict] = {}

        # Create a map for fast lookup
        hp_map = {item["hp_id"]: item for item in hp_list}

        quantity_usd = (
            update.symbol_info.format_price(
                update.quantity_usd * self.price_resolver.latest_prices["BTCUSDC"]
            )
            if update.quantity_usd is not None
            and update.symbol_info.symbol.endswith("BTC")
            else (
                update.symbol_info.format_price(update.quantity_usd)
                if update.quantity_usd is not None
                else "0.0"
            )
        )

        # Extract operation side from update
        operation_side = getattr(update, "side", "UNKNOWN")
        if operation_side == "UNKNOWN":
            # Fallback: determine from state or other context
            if "BUY" in update.state.value or "LONG" in update.state.value:
                operation_side = "LONG"
            elif "SELL" in update.state.value or "SHORT" in update.state.value:
                operation_side = "SHORT"

        logger.debug(
            f"Processing HP update: {hp_id}, side: {operation_side}, state: {update.state.value}"
        )

        # Handle both regular children and multihop children in unified container logic
        self._handle_container_position(
            hp_map,
            update,
            hp_id,
            operation_side,
            quantity_usd,
            is_multihop_child,
            base_hp_id,
        )

        self.hp_list = list(hp_map.values())

        # Check if the HP position moved to CLOSED or SOLD state and auto-remove from filter if needed
        if update.state.value in ["CLOSED", "SOLD"]:
            self.auto_remove_closed_sold_states()

        # Calculate parent quantity_usd as total invested amount from all buy children
        # This happens at the very end to ensure all containers have been updated first
        for parent_key, parent in hp_map.items():
            if not parent.get("is_child", False) and parent.get("side") == "PARENT":
                total_invested_amount = 0.0
                for child_key in parent.get("children", []):
                    if child_key in hp_map and "_BUY" in child_key:
                        buy_child = hp_map[child_key]
                        child_quantity_usd = float(buy_child.get("quantity_usd", "0.0"))
                        total_invested_amount += child_quantity_usd

                if total_invested_amount > 0:
                    parent["quantity_usd"] = (
                        str(update.symbol_info.format_price(total_invested_amount))
                        if hasattr(update.symbol_info, "format_price")
                        else f"{total_invested_amount:.2f}"
                    )

        # Apply action button logic to all HP items
        temp_hp_list = list(
            hp_map.values()
        )  # Create temporary list for the helper methods
        self.hp_list_data = (
            temp_hp_list  # Update the instance variable for helper methods
        )

        for hp_item in hp_map.values():
            button_config = self._determine_action_buttons(hp_item)
            hp_item["action_buttons"] = button_config["buttons"]
            hp_item["button_states"] = button_config["states"]

        # Trigger visual refresh
        self._update_hp_list_view()

        return self.hp_list

    def _is_multihop_child(self, hp_id: str) -> bool:
        """
        Detect multihop children: 1000a, 1000b, etc.
        Pattern: numeric_parent_id + single_letter_suffix
        """
        if len(hp_id) < 2:
            return False

        # Check if ends with single letter and rest is numeric
        return hp_id[-1].isalpha() and hp_id[:-1].isdigit()

    def _is_regular_child(self, hp_id: str) -> bool:
        """
        Detect regular children: 1000_BUY, 1000_SELL, etc.
        Pattern: numeric_parent_id + _SUFFIX
        """
        if "_" not in hp_id:
            return False

        parts = hp_id.split("_")
        if len(parts) != 2:
            return False

        parent_part, suffix_part = parts

        # Valid regular child suffixes
        valid_suffixes = {"BUY", "SELL"}

        return parent_part.isdigit() and suffix_part in valid_suffixes

    def _handle_container_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
        is_multihop_child: bool = False,
        base_hp_id: Optional[str] = None,
    ) -> None:
        """Handle new runtime positions with container structure, including multihop children."""

        # Determine if this is a Buy or Sell operation
        # Priority logic: SELLING state should create separate sell child even if side='BUY'
        is_sell_operation = (
            operation_side in ["SHORT", "SELL"]
            or update.state.value in ["SELLING", "SOLD"]
            or "SELL" in update.state.value
        )
        is_buy_operation = not is_sell_operation and (
            operation_side in ["LONG", "BUY"] or "BUY" in update.state.value
        )

        logger.debug(
            f"Container position {hp_id}: is_buy={is_buy_operation}, is_sell={is_sell_operation}, multihop={is_multihop_child}"
        )

        # For multihop children, use base_hp_id for parent container
        parent_hp_id = base_hp_id if is_multihop_child and base_hp_id else hp_id

        # Always ensure parent container exists
        if parent_hp_id not in hp_map or hp_map[parent_hp_id].get("is_child", True):
            # Create parent container
            hp_map[parent_hp_id] = {
                "hp_id": parent_hp_id,
                "coin": f"{update.coin}USD",
                "state": update.state.value,
                "buy_price": "0.0",
                "quantity": "0.0",  # Total realized buy quantity
                "realized_quantity": "0.0",  # Total realized sell quantity
                "quantity_usd": "0.0",
                "sell_price": "0.0",
                "expected_return": "0.0",
                "current_price": "0.0",
                "net": "0.0",
                "net_percent": "0.0",
                "is_child": False,
                "side": "PARENT",
                "children": [],
                "is_expanded": True,  # Start expanded so children are visible
                "action_buttons": [
                    "SELL",
                    "CANCEL",
                ],  # Will be determined by _determine_action_buttons later
            }

        parent = hp_map[parent_hp_id]
        parent.setdefault("children", [])

        if is_buy_operation:
            # Buy HP: Create buy child (includes multihop children)
            if is_multihop_child:
                # For multihop children, use the actual hp_id (e.g., "1000a")
                buy_child_key = hp_id
            else:
                # For regular children, use standard naming convention
                buy_child_key = f"{hp_id}_BUY"

            # Buy children according to new specification:
            # - quantity: Total trade quantity (use total_quantity if available)
            # - realized_quantity: Actually realized quantity (use total_quantity if available)

            # Get total quantity for buy child display
            total_bought_qty_raw = getattr(update, "total_quantity", None)
            if total_bought_qty_raw is None:
                # Fallback to current quantity for buy child display
                total_bought_qty = update.quantity or 0.0
            else:
                total_bought_qty = float(total_bought_qty_raw)

            # Calculate buy child quantity_usd based on total bought quantity and buy price
            # This ensures buy child always shows total invested amount, not remaining value
            buy_child_quantity_usd = total_bought_qty * (update.buy_price or 0.0)
            buy_child_quantity_usd_str = (
                str(update.symbol_info.format_price(buy_child_quantity_usd))
                if update.symbol_info
                else f"{buy_child_quantity_usd:.2f}"
            )

            buy_child = {
                "hp_id": buy_child_key,
                "coin": update.symbol_info.symbol,
                "buy_price": (
                    str(update.symbol_info.format_price(update.buy_price))
                    if update.buy_price
                    else "0.0"
                ),
                "quantity": (
                    str(update.symbol_info.format_quantity(total_bought_qty))
                    if total_bought_qty
                    else "0.0"
                ),
                "realized_quantity": (
                    str(update.symbol_info.format_quantity(total_bought_qty))
                    if total_bought_qty
                    else "0.0"
                ),
                "quantity_usd": buy_child_quantity_usd_str,
                "current_price": (
                    str(update.symbol_info.format_price(update.current_price))
                    if update.current_price
                    else "0.0"
                ),
                "net": (
                    str(update.symbol_info.format_price(update.net))
                    if update.net
                    else "0.0"
                ),
                "net_percent": str(update.net_percent) if update.net_percent else "0.0",
                "state": self._log_and_return_buy_child_state(update),
                "is_child": True,
                "side": "BUY",
                "parent_hp_id": parent_hp_id,  # Use parent_hp_id instead of hp_id for multihop
                "action_buttons": [
                    "CANCEL"
                ],  # Will be determined by _determine_action_buttons later
            }

            # Buy children NEVER have sell_price or expected_return fields
            # They are purely buy operations and should not show sell-related information

            hp_map[buy_child_key] = buy_child
            if buy_child_key not in parent["children"]:
                parent["children"].append(buy_child_key)

            # Update parent quantities according to new specification:
            # - quantity: Total realized buy quantity (always reflects total bought)
            # - realized_quantity: Total realized sell quantity (how much was sold)

            # Calculate total bought quantity - use total_quantity from strategy if available
            total_bought = getattr(update, "total_quantity", None)
            if total_bought is None:
                # Fallback to current quantity if total_quantity not available
                total_bought = getattr(update, "quantity", 0.0) or 0.0

            # For sell operations, we need to calculate how much was actually sold
            short_condition = operation_side == "SHORT"
            sell_condition = (
                "SELL" in update.state.value or "SOLD" in update.state.value
            )
            logger.debug(
                f"[PARENT CONDITION] operation_side={operation_side}, state={update.state.value}, short_condition={short_condition}, sell_condition={sell_condition}"
            )

            combined_condition = short_condition or sell_condition

            if combined_condition:
                # During selling, update.quantity represents remaining quantity after sells
                # So sold quantity = total_bought - remaining_quantity
                remaining_qty = float(update.quantity) if update.quantity else 0.0

                # Calculate sold quantity
                sold_qty = max(0.0, total_bought - remaining_qty)

                # Parent quantity should show total bought amount (not remaining)
                parent["quantity"] = str(
                    update.symbol_info.format_quantity(total_bought)
                )
                parent["realized_quantity"] = str(
                    update.symbol_info.format_quantity(sold_qty)
                )
                logger.info(
                    f"[PARENT SELL] Total bought: {parent['quantity']}, Sold: {parent['realized_quantity']}, Remaining: {remaining_qty}"
                )

            else:
                # For buy operations, just update the total bought
                parent["quantity"] = str(
                    update.symbol_info.format_quantity(total_bought)
                )
            # Ensure both fields exist
            if "realized_quantity" not in parent:
                parent["realized_quantity"] = "0.0"
            parent["buy_price"] = buy_child["buy_price"]
            parent["net"] = buy_child["net"]
            parent["net_percent"] = buy_child["net_percent"]
            parent["state"] = update.state.value

            # For complex states that involve selling, update existing sell child
            if any(
                sell_indicator in update.state.value
                for sell_indicator in ["SELL", "SOLD"]
            ):
                sell_child_key = f"{hp_id}_SELL"
                if sell_child_key in hp_map:
                    existing_sell_child = hp_map[sell_child_key]
                    # Update sell child state for complex parent states
                    existing_sell_child["state"] = (
                        self._get_sell_child_state_from_update(update)
                    )

                    # Update sell child quantities according to new specification
                    total_bought = float(parent.get("quantity", "0.0"))
                    actually_sold = float(parent.get("realized_quantity", "0.0"))
                    existing_sell_child["quantity"] = str(
                        update.symbol_info.format_quantity(total_bought)
                    )
                    existing_sell_child["realized_quantity"] = str(
                        update.symbol_info.format_quantity(actually_sold)
                    )

                    logger.info(
                        f"[SELL CHILD UPDATE] Updated existing sell child state to: {existing_sell_child['state']} for parent state: {update.state.value}"
                    )

        elif is_sell_operation:
            # Sell HP: Create sell child, keeping existing buy child if present

            # Check if there's already a real buy child
            if is_multihop_child:
                # For multihop children, use the actual hp_id (e.g., "1000a")
                buy_child_key = hp_id
            else:
                # For regular children, use standard naming convention
                buy_child_key = f"{hp_id}_BUY"
            has_real_buy_child = buy_child_key in hp_map

            # Update existing buy child if it exists
            if has_real_buy_child:
                existing_buy_child = hp_map[buy_child_key]
                # Update buy child state appropriately for selling phase
                existing_buy_child["state"] = self._get_buy_child_state(update)
                logger.info(
                    f"[BUY CHILD UPDATE] Updated existing buy child state to: {existing_buy_child['state']} for quantity: {update.quantity}"
                )

                # Update buy child quantities according to new specification
                if update.quantity is not None:
                    # For new specification: buy child shows total bought quantity
                    # Use total_quantity if available, otherwise use calculated total
                    total_bought_qty_raw = getattr(update, "total_quantity", None)
                    logger.info(
                        f"[BUY CHILD DEBUG] update.quantity={update.quantity}, total_quantity={total_bought_qty_raw}"
                    )
                    if total_bought_qty_raw is None:
                        # Fallback calculation - total bought = remaining quantity + sold quantity
                        sell_total_qty = 0.0
                        if (
                            hasattr(update, "sell_completeness")
                            and update.sell_completeness is not None
                        ):
                            # If we have sell completeness info, use it
                            sell_total_qty = update.sell_completeness * update.quantity
                        total_bought_qty = update.quantity + sell_total_qty
                        logger.info(
                            f"[BUY CHILD DEBUG] Fallback calculation: {update.quantity} + {sell_total_qty} = {total_bought_qty}"
                        )
                    else:
                        total_bought_qty = float(total_bought_qty_raw)
                        logger.info(
                            f"[BUY CHILD DEBUG] Using total_quantity: {total_bought_qty}"
                        )

                    existing_buy_child["quantity"] = str(
                        update.symbol_info.format_quantity(total_bought_qty)
                    )
                    # For buy child, realized_quantity = total bought (what we've purchased)
                    existing_buy_child["realized_quantity"] = str(
                        update.symbol_info.format_quantity(total_bought_qty)
                    )

                    # Calculate quantity_usd based on total bought quantity and buy price (money invested)
                    # This represents the total value of the position regardless of selling status
                    buy_price = float(existing_buy_child.get("buy_price", 0))
                    quantity_usd_value = total_bought_qty * buy_price
                    existing_buy_child["quantity_usd"] = (
                        str(update.symbol_info.format_price(quantity_usd_value))
                        if update.symbol_info
                        else f"{quantity_usd_value:.2f}"
                    )

                # Buy children should NEVER have sell-related fields
                # Remove any sell-related fields that might exist
                existing_buy_child.pop("sell_price", None)
                existing_buy_child.pop("expected_return", None)

            # Create sell child - but only main sell child for non-multihop scenarios
            # For multihop scenarios, parent IS the main sell position
            if is_multihop_child:
                # For multihop children, use the actual hp_id (e.g., "1000a")
                sell_child_key = hp_id
                create_sell_child = True
            else:
                # For regular non-multihop sell operations, create main sell child
                # But skip main sell child creation for multihop parent scenarios
                # Detect multihop parent: ends with USDT (virtual pair) and state is BOUGHT
                is_multihop_parent = (
                    update.symbol_info.symbol.endswith("USDT")
                    and update.state == State.BOUGHT
                    and is_sell_operation
                )

                logger.debug(
                    f"[MULTIHOP DETECTION] hp_id={hp_id}, symbol={update.symbol_info.symbol}, state={update.state}, is_sell_operation={is_sell_operation}, is_multihop_parent={is_multihop_parent}"
                )

                if is_multihop_parent:
                    # This is a multihop parent - don't create main sell child
                    logger.debug(
                        f"[MULTIHOP PARENT] Skipping main sell child creation for {hp_id}"
                    )
                    create_sell_child = False
                    sell_child_key = None
                else:
                    # Regular sell scenario - create main sell child
                    logger.debug(f"[REGULAR SELL] Creating main sell child for {hp_id}")
                    sell_child_key = f"{hp_id}_SELL"
                    create_sell_child = True

            # Sell children according to new specification:
            # - quantity: Total buy quantity (the amount that should be sold - same as total bought)
            # - realized_quantity: Actually sold quantity (how much was actually sold)

            # Get total bought quantity from parent
            total_bought_qty = float(parent.get("quantity", "0.0"))
            actually_sold_qty = float(parent.get("realized_quantity", "0.0"))

            # Only create sell child if not a multihop parent
            if create_sell_child:
                # For sell child, calculate quantity_usd same as buy child (total bought value)
                # This represents the total value of money invested in the position
                sell_child_quantity_usd = total_bought_qty * (
                    update.buy_price if update.buy_price else 0.0
                )
                sell_child_quantity_usd_str = (
                    str(update.symbol_info.format_price(sell_child_quantity_usd))
                    if update.symbol_info
                    else f"{sell_child_quantity_usd:.2f}"
                )

                sell_child = {
                    "hp_id": sell_child_key,
                    "coin": update.symbol_info.symbol,
                    "buy_price": (
                        str(update.symbol_info.format_price(update.buy_price))
                        if update.buy_price
                        else "0.0"
                    ),
                    "quantity": (
                        str(update.symbol_info.format_quantity(total_bought_qty))
                    ),
                    "realized_quantity": (
                        str(update.symbol_info.format_quantity(actually_sold_qty))
                    ),
                    "quantity_usd": sell_child_quantity_usd_str,
                    "sell_price": (
                        str(update.symbol_info.format_price(update.sell_price))
                        if update.sell_price
                        else "0.0"
                    ),
                    "expected_return": (
                        str(update.symbol_info.format_price(update.expected_return))
                        if update.expected_return
                        else "0.0"
                    ),
                    "current_price": (
                        str(update.symbol_info.format_price(update.current_price))
                        if update.current_price
                        else "0.0"
                    ),
                    "net": (
                        str(update.symbol_info.format_price(update.net))
                        if update.net
                        else "0.0"
                    ),
                    "net_percent": (
                        str(update.net_percent) if update.net_percent else "0.0"
                    ),
                    "state": self._get_sell_child_state_from_update(update),
                    "sell_completeness": str(getattr(update, "sell_completeness", 0.0)),
                    "is_child": True,
                    "side": "SELL",
                    "parent_hp_id": parent_hp_id,  # Use parent_hp_id instead of hp_id for multihop
                    "action_buttons": [
                        "CANCEL"
                    ],  # Will be determined by _determine_action_buttons later
                }

                hp_map[sell_child_key] = sell_child
                if sell_child_key not in parent["children"]:
                    parent["children"].append(sell_child_key)

            # Update parent quantity using same logic as buy operation
            # This ensures parent quantity shows remaining vs total based on state
            operation_side = getattr(update, "side", "BUY")
            short_condition = operation_side == "SHORT"
            sell_condition = "SELL" in update.state.value
            combined_condition = short_condition or sell_condition

            logger.debug(
                f"[PARENT SELL CONDITION] operation_side={operation_side}, state={update.state.value}, short_condition={short_condition}, sell_condition={sell_condition}"
            )
            logger.debug(
                f"[PARENT SELL CONDITION DEBUG] state type: {type(update.state)}, state value type: {type(update.state.value)}"
            )
            logger.debug(
                f"[PARENT SELL CONDITION DEBUG] repr(state.value): {repr(update.state.value)}"
            )
            logger.debug(
                f"[PARENT SELL CONDITION DEBUG] 'SELL' in repr: {'SELL' in update.state.value}"
            )
            logger.debug(
                f"[PARENT SELL CONDITION DEBUG] Combined condition: {combined_condition}"
            )

            if combined_condition:
                # During selling, update.quantity represents remaining quantity after sells
                # So sold quantity = total_bought - remaining_quantity
                remaining_qty = float(update.quantity) if update.quantity else 0.0

                # Calculate sold quantity
                sold_qty = max(0.0, total_bought_qty - remaining_qty)

                # Parent quantity should show total bought quantity (not remaining)
                parent["quantity"] = str(
                    update.symbol_info.format_quantity(total_bought_qty)
                )
                parent["realized_quantity"] = str(
                    update.symbol_info.format_quantity(sold_qty)
                )
                logger.debug(
                    f"[PARENT SELL] Total bought: {parent['quantity']}, Sold: {parent['realized_quantity']} (remaining: {remaining_qty})"
                )

            else:
                # For sell operations without SELL in state, show total bought
                parent["quantity"] = str(
                    update.symbol_info.format_quantity(total_bought_qty)
                )
                logger.debug(
                    f"[PARENT SELL BUY] Set parent total bought quantity: {parent['quantity']}"
                )

            # Update parent with sell data (only for non-multihop children)
            if not is_multihop_child:
                parent["buy_price"] = sell_child[
                    "buy_price"
                ]  # Only update from main sell child
                parent["sell_price"] = sell_child[
                    "sell_price"
                ]  # Only update from main sell child
                parent["expected_return"] = sell_child[
                    "expected_return"
                ]  # Only update from main sell child

            # For sell-first strategies, calculate parent quantity_usd from parent data
            parent_quantity = float(parent.get("quantity", "0.0"))
            parent_buy_price = float(parent.get("buy_price", "0.0"))
            if parent_quantity > 0.0 and parent_buy_price > 0.0:
                parent_quantity_usd = parent_quantity * parent_buy_price
                parent["quantity_usd"] = str(
                    update.symbol_info.format_price(parent_quantity_usd)
                )

            parent["action_buttons"] = [
                "SELL",
                "CANCEL",
            ]  # Will be determined by _determine_action_buttons later

        # Update parent state to reflect the actual operation state
        parent["state"] = update.state.value

    def _process_all_tickers(self, tickers: AllTickers) -> None:
        # Update HP list data with current prices
        for strategy in self.hp_list_data:
            for ticker in tickers.msg:
                symbol = ticker.get("s")
                if strategy["state"] not in [State.CLOSED.value, State.SOLD.value]:
                    # Handle USDT pairs for USD coins (e.g., AXLUSD -> AXLUSDT)
                    if (
                        strategy["coin"].endswith("USD")
                        and symbol == f"{strategy['coin'][:-3]}USDT"
                    ):
                        current_price = self.symbols_info[symbol].format_price(
                            price=float(ticker["c"])
                        )
                        strategy["current_price"] = current_price

                        if float(strategy["buy_price"]):
                            net_percent = round(
                                100
                                * (
                                    float(current_price) / float(strategy["buy_price"])
                                    - 1
                                ),
                                2,
                            )
                            # Calculate actual net profit/loss in USD for USDT pairs
                            net_usd = round(
                                (float(current_price) - float(strategy["buy_price"]))
                                * float(strategy["quantity"]),
                                2,
                            )
                            strategy["net"] = self.symbols_info[symbol].format_price(
                                net_usd
                            )
                            strategy["net_percent"] = str(net_percent)
                    # Handle direct symbol matches (e.g., BTCUSDT)
                    elif symbol == strategy["coin"]:
                        current_price = self.symbols_info[symbol].format_price(
                            price=float(ticker["c"])
                        )
                        strategy["current_price"] = current_price

                        if float(strategy["buy_price"]):
                            net_percent = round(
                                100
                                * (
                                    float(current_price) / float(strategy["buy_price"])
                                    - 1
                                ),
                                2,
                            )
                            # Calculate actual net profit/loss in USD
                            net_usd = round(
                                (float(current_price) - float(strategy["buy_price"]))
                                * float(strategy["quantity"]),
                                2,
                            )
                            strategy["net"] = self.symbols_info[symbol].format_price(
                                net_usd
                            )
                            strategy["net_percent"] = str(net_percent)
        # Only trigger visual refresh if in test mode or if significant changes occurred
        # In production, UI updates are handled by other mechanisms to reduce spam
        if getattr(self, "test_mode", False):
            self._update_hp_list_view()

    def sell_hp_button(self, hp_id, coin, quantity, buy_price):
        """
        Moves to the Sell tab and fills the HP data (HP ID, coin, quantity).

        Args:
        - hp_id: The ID of the HP to sell.
        - coin: The coin involved in the HP.
        - quantity: The amount of the coin to sell.
        """
        # Switch into Existing-HP mode, then move to the "Sell" tab
        # self.ids.hp_mode_existing.state = "down"
        # self.ids.hp_mode_new.state      = "normal"
        self.ids.hp_tabbed_panel.switch_to(
            self.ids.hp_sell_tab
        )  # Assuming 'sell_tab' is the ID for the "Sell" tab.
        # rebuild the “Existing HP” UI
        self.update_hp_mode("existing")

        # Populate the fields in the Sell tab
        self.ids.hp_id_input.text = str(hp_id)
        self.ids.coin_input.text = str(coin[:-3] if coin.endswith("USD") else coin)
        self.ids.quantity_input.text = str(quantity)
        # self.ids.quantity_usd_label.text = str(
        #     round(float(quantity) * float(buy_price), 2)
        # )
        self.ids.buy_price_input.text = str(buy_price)

        # Clear or reset the sell price field
        self.ids.sell_price_input.text = ""

        # Optional: If you want to set focus on the sell price input field
        self.ids.sell_price_input.focus = True

        self.ids.hp_mode_existing.state = "down"
        self.ids.hp_mode_new.state = "normal"

        logger.info(
            "Moved to 'Sell' tab for HP ID: %s, coin: %s, Quantity: %s",
            hp_id,
            coin,
            quantity,
        )

    def new_sell_hp_button(self, hp_id, coin, quantity, buy_price):
        """Show confirmation dialog for selling HP position."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        from kivy.uix.textinput import TextInput

        content = BoxLayout(orientation="vertical", spacing=10, padding=10)

        # Title and info
        info_text = f"""Sell HP Position {hp_id}

Current Position:
• Coin: {coin}
• Quantity: {quantity}
• Buy Price: {buy_price}

Enter sell price to create sell order:"""

        info_label = Label(
            text=info_text,
            halign="center",
            valign="middle",
            text_size=(None, None),
            color=[0.2, 0.8, 0.2, 1],  # Green color
        )
        info_label.bind(size=info_label.setter("text_size"))
        content.add_widget(info_label)

        # Sell price input
        price_layout = BoxLayout(
            orientation="horizontal", size_hint_y=None, height=40, spacing=10
        )
        price_label = Label(text="Sell Price:", size_hint_x=0.3)
        price_input = TextInput(
            hint_text="Enter sell price",
            multiline=False,
            size_hint_x=0.7,
            input_filter="float",
        )
        price_layout.add_widget(price_label)
        price_layout.add_widget(price_input)
        content.add_widget(price_layout)

        # Expected return calculation
        return_label = Label(
            text="Expected return will be calculated...",
            halign="center",
            size_hint_y=None,
            height=30,
            color=[0.8, 0.8, 0.8, 1],
        )
        content.add_widget(return_label)

        # Update expected return when price changes
        def update_expected_return(instance, text):
            try:
                sell_price = float(text) if text else 0
                buy_price_float = float(buy_price)
                quantity_float = float(quantity)
                if sell_price > 0 and buy_price_float > 0:
                    profit = (sell_price - buy_price_float) * quantity_float
                    profit_percent = ((sell_price / buy_price_float) - 1) * 100
                    return_label.text = (
                        f"Expected return: {profit:.2f} (+{profit_percent:.2f}%)"
                    )
                else:
                    return_label.text = "Expected return will be calculated..."
            except ValueError:
                return_label.text = "Invalid price entered"

        price_input.bind(text=update_expected_return)

        # Buttons
        button_layout = BoxLayout(
            orientation="horizontal", spacing=10, size_hint_y=None, height=50
        )

        cancel_btn = Button(text="Cancel", background_color=[0.5, 0.5, 0.5, 1])
        confirm_btn = Button(
            text="CREATE SELL ORDER", background_color=[0.2, 0.8, 0.2, 1]
        )

        button_layout.add_widget(cancel_btn)
        button_layout.add_widget(confirm_btn)
        content.add_widget(button_layout)

        popup = Popup(
            title=f"Sell HP Position {hp_id}",
            content=content,
            size_hint=(0.6, 0.6),
            auto_dismiss=False,
            title_color=[0.2, 0.8, 0.2, 1],
        )

        # Button actions
        cancel_btn.bind(on_release=popup.dismiss)
        confirm_btn.bind(
            on_release=lambda x: self._confirm_sell_hp(
                popup, hp_id, coin, quantity, buy_price, price_input.text
            )
        )

        popup.open()

    def _confirm_sell_hp(
        self, popup, hp_id, coin, quantity, buy_price, sell_price_text
    ):
        """Confirm and execute the sell order"""
        try:
            sell_price = float(sell_price_text) if sell_price_text else 0
            if sell_price <= 0:
                # Show error - could enhance with another popup
                print("Error: Sell price must be greater than 0")
                return

            popup.dismiss()

            # Create sell configuration and send to strategy executor
            coin_symbol = coin[:-3] if coin.endswith("USD") else coin
            symbol = f"{coin_symbol}USDC"

            logger.info(
                f"Creating sell order for HP {hp_id}: {quantity} {coin_symbol} at {sell_price}"
            )

            # Create proper sell configuration and send to config queue
            if symbol not in self.symbols_info:
                logger.error(f"Symbol info not found for {symbol}")
                return

            sell_config = HPSellData(
                config=HPSellConfig(
                    hp_id=hp_id,  # Use the same HP ID to create sell child
                    coin=coin_symbol,
                    buy_price=float(buy_price),
                    sell_price=sell_price,
                    quantity=float(quantity),
                    end_currency="USDC",
                    symbol_info=self.symbols_info[symbol],
                ),
                state_info=StateInfo(side=PositionSide.SHORT),
            )

            # Send to strategy executor
            self.config_queue.put_nowait(sell_config)
            logger.info(
                "Sell HP configuration sent to strategy executor: %s",
                sell_config.config,
            )

        except ValueError:
            print("Error: Invalid sell price")
        except Exception as e:
            logger.error(f"Error creating sell order: {e}")

    def cancel_sell(self, hp_id: str, coin: str):
        coin = coin[:-3] if coin.endswith("USD") else coin
        config = HPSellConfig(hp_id=hp_id, symbol_info=self.symbols_info[f"{coin}USDT"])
        state_info = StateInfo(
            side=PositionSide.SHORT, ui_state=UiState.CLOSED, state=State.CLOSED
        )

        self.config_queue.put_nowait(
            RemoveRecord(hp_id=config.hp_id, symbol=f"{coin}USDT", side=state_info.side)
        )

        logger.info("Cancel sell send to the config queue: %s", config)

    def _has_sell_child(self, hp_id: str) -> bool:
        """Check if HP has a sell child"""
        for item in self.hp_list_data:
            if item.get("hp_id") == f"{hp_id}_SELL":
                return True
        return False

    def _get_parent_realized_quantity(self, hp_id: str) -> float:
        """Get the realized buy quantity from parent HP"""
        for item in self.hp_list_data:
            if item.get("hp_id") == hp_id and item.get("side") == "PARENT":
                return float(item.get("quantity", "0.0"))
        return 0.0

    def _get_sell_child_realized_quantity(self, hp_id: str) -> float:
        """Get the realized sell quantity from sell child"""
        for item in self.hp_list_data:
            if item.get("hp_id") == f"{hp_id}_SELL":
                return float(item.get("realized_quantity", "0.0"))
        return 0.0

    def _determine_action_buttons(self, hp_data: dict) -> dict:
        """Determine which action buttons to show and their states"""
        hp_id = hp_data.get("hp_id", "")
        side = hp_data.get("side", "")
        is_child = hp_data.get("is_child", False)

        # Extract base HP ID for children
        base_hp_id = hp_id.split("_")[0] if is_child else hp_id

        buttons: Dict[str, Any] = {"buttons": [], "states": {}}

        if side == "PARENT":
            # Parent HP logic
            has_sell_child = self._has_sell_child(base_hp_id)
            realized_quantity = float(hp_data.get("quantity", "0.0"))

            # SELL button: Always show, but enabled only if no sell child and realized_quantity > 0
            buttons["buttons"].append("SELL")
            buttons["states"]["SELL"] = {
                "enabled": not has_sell_child and realized_quantity > 0,
                "text": "Sell",
            }

            # CANCEL button: Always show and enabled
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {"enabled": True, "text": "Cancel"}

        elif side == "BUY":
            # Buy child logic
            has_sell_child = self._has_sell_child(base_hp_id)

            # CANCEL button: Always show, but enabled only if no sell child
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {
                "enabled": not has_sell_child,
                "text": "Cancel",
            }

        elif side == "SELL":
            # Sell child logic
            realized_sell_quantity = float(hp_data.get("realized_quantity", "0.0"))

            # CANCEL button: Always show, but enabled only if realized_quantity == 0
            buttons["buttons"].append("CANCEL")
            buttons["states"]["CANCEL"] = {
                "enabled": realized_sell_quantity == 0,
                "text": "Cancel",
            }

        return buttons

    def _handle_cancel_button_click(
        self, hp_id: str, symbol: str, side_value: str
    ) -> None:
        """Handle cancel button click with enhanced logic"""
        # Determine if this is a parent, buy child, or sell child
        if "_" not in hp_id:
            # This is a parent HP
            self._cancel_parent_hp(hp_id, symbol)
        elif hp_id.endswith("_BUY"):
            # This is a buy child
            base_hp_id = hp_id.replace("_BUY", "")
            self._cancel_buy_child(base_hp_id, symbol, side_value)
        elif hp_id.endswith("_SELL"):
            # This is a sell child
            base_hp_id = hp_id.replace("_SELL", "")
            self._cancel_sell_child(base_hp_id, symbol)
        else:
            # Fallback to original logic
            self.show_cancel_confirmation(hp_id, symbol, side_value)

    def _cancel_parent_hp(self, hp_id: str, symbol: str) -> None:
        """Cancel parent HP - first cancel sell child (if exists), then buy child"""
        has_sell_child = self._has_sell_child(hp_id)

        if has_sell_child:
            # First cancel the sell child
            self._cancel_sell_child(hp_id, symbol)
            # Note: After sell child is cancelled, user can click cancel again to cancel buy
        else:
            # No sell child, proceed with buy cancellation
            self.show_cancel_confirmation(hp_id, symbol, "LONG")

    def _cancel_buy_child(self, base_hp_id: str, symbol: str, side_value: str) -> None:
        """Cancel buy child - same as parent cancel for buy position"""
        has_sell_child = self._has_sell_child(base_hp_id)

        if not has_sell_child:
            # Only allow buy cancellation if no sell child exists
            self.show_cancel_confirmation(base_hp_id, symbol, side_value)
        # If sell child exists, button should be disabled, so this shouldn't be called

    def _cancel_sell_child(self, base_hp_id: str, symbol: str) -> None:
        """Cancel sell child"""
        sell_realized_qty = self._get_sell_child_realized_quantity(base_hp_id)

        if sell_realized_qty == 0:
            # Only allow sell cancellation if no realized quantity
            # Use SHORT side for sell position cancellation
            self.show_cancel_confirmation(f"{base_hp_id}_SELL", symbol, "SHORT")
        # If realized quantity > 0, button should be disabled, so this shouldn't be called

    def fetch_hp_info(self, hp_id):
        """
        Fetches HP information for the new modal system.
        This method is kept for backward compatibility but now works with modals.

        Args:
        - hp_id: The HP ID to look up.
        """
        try:
            for item in self.hp_list_data:
                if int(item["hp_id"]) == int(hp_id):
                    logger.info(f"Found HP info for ID {hp_id}: {item}")
                    return item

            logger.error(f"HP ID {hp_id} not found in hp_list_data")
            return None

        except ValueError:
            logger.error(f"Invalid HP ID format: {hp_id}")
            return None

    def _calculate_trigger_price(self, data: HPBuyData) -> str:
        # For idle positions
        if data.state_info.side.value == PositionSide.LONG.value:
            base = data.config.price_high
            factor = 1 + (data.config.order_trigger / 100)
        else:
            base = data.config.price_low
            factor = 1 - (data.config.order_trigger / 100)
        return data.config.symbol_info.format_price(base * factor)

    def _calculate_cancel_price(self, data: HPBuyData) -> float:
        # For active positions; note the 2*order_trigger
        if data.state_info.side.value == PositionSide.LONG.value:
            base = data.config.price_high
            factor = 1 + (2 * data.config.order_trigger / 100)
        else:
            base = data.config.price_low
            factor = 1 - (2 * data.config.order_trigger / 100)
        return data.config.symbol_info.adjust_price(base * factor)

    def _record_exists(self, records: List[Dict], hp_id: str) -> bool:
        return any(record["hp_id"] == hp_id for record in records)

    def toggle_hp_expansion(self, hp_id: str):
        """Toggle the expansion state of a parent HP position"""
        logger.info(f"[EXPANSION] Toggling expansion for HP {hp_id}")

        # Count rows before expansion change
        total_rows_before = (
            len(self.hp_list_data) if hasattr(self, "hp_list_data") else 0
        )
        logger.info(f"[EXPANSION] Total rows BEFORE toggle: {total_rows_before}")

        if hp_id in self.expanded_hp_ids:
            logger.info(f"[EXPANSION] Collapsing HP {hp_id}")
            self.expanded_hp_ids.remove(hp_id)
        else:
            logger.info(f"[EXPANSION] Expanding HP {hp_id}")
            self.expanded_hp_ids.add(hp_id)

        logger.info(f"[EXPANSION] Current expanded HPs: {self.expanded_hp_ids}")

        # Check what children exist for this HP in hp_list_data
        children_for_hp = []
        for item in self.hp_list_data:
            if item.get("hp_id", "").startswith(f"{hp_id}_") and item.get("is_child", False):
                children_for_hp.append(item.get("hp_id"))
                logger.info(
                    f"[EXPANSION] Found child {item.get('hp_id')} with data: coin={item.get('coin', 'N/A')}, side={item.get('side', 'N/A')}, state={item.get('state', 'N/A')}"
                )
        logger.info(f"[EXPANSION] HP {hp_id} has children: {children_for_hp}")

        # Also check hp_list_data for children
        list_children = [
            item
            for item in self.hp_list_data
            if item.get("hp_id", "").startswith(f"{hp_id}_")
        ]
        logger.info(
            f"[EXPANSION] HP {hp_id} children in hp_list_data: {[c.get('hp_id') for c in list_children]}"
        )
        for child in list_children:
            logger.info(
                f"[EXPANSION] List child {child.get('hp_id')}: side={child.get('side')}, state={child.get('state')}, is_child={child.get('is_child')}"
            )

        # Trigger UI update
        self._update_hp_list_view()

        # Count rows after expansion change
        total_rows_after = (
            len(self.hp_list_data) if hasattr(self, "hp_list_data") else 0
        )
        logger.info(f"[EXPANSION] Total rows AFTER toggle: {total_rows_after}")
        logger.info(
            f"[EXPANSION] Row difference: {total_rows_after - total_rows_before}"
        )

    def _get_sorted_hp_list(self):
        logger.info(
            f"[SORT DEBUG] Starting _get_sorted_hp_list with {len(self.hp_list_data)} total items"
        )
        logger.info(f"[SORT DEBUG] Expanded HPs: {self.expanded_hp_ids}")

        # Apply state filtering first
        filtered_data = [
            hp
            for hp in self.hp_list_data
            if hp.get("state", "") in self.hp_state_filter
        ]
        logger.info(f"[SORT DEBUG] After state filtering: {len(filtered_data)} items")

        # Separate parents and children
        parents = [
            hp
            for hp in filtered_data
            if not hp.get("is_child", False) and hp.get("side", "") == "PARENT"
        ]
        logger.info(f"[SORT DEBUG] Found {len(parents)} parent items")

        multihop_children = [
            hp
            for hp in filtered_data
            if hp.get("is_child", False)
            and hp.get("hp_id", "")[-1:].isalpha()
            and "_" not in hp.get("hp_id", "")
        ]
        logger.info(f"[SORT DEBUG] Found {len(multihop_children)} multihop children")

        regular_children = [
            hp
            for hp in filtered_data
            if hp.get("is_child", False) and "_" in hp.get("hp_id", "")
        ]
        logger.info(f"[SORT DEBUG] Found {len(regular_children)} regular children")

        sorted_list = []
        for parent in sorted(parents, key=lambda x: int(x.get("hp_id", "0"))):
            # Find children for this parent
            parent_id = parent["hp_id"]
            logger.info(f"[SORT DEBUG] Processing parent {parent_id}")

            # Multihop children (1000a, 1000b)
            parent_multihop_children = [
                c
                for c in multihop_children
                if c.get("parent_hp_id") == parent_id
                or c.get("hp_id", "")[:-1] == parent_id
            ]

            # Regular children (same HP ID, different sides)
            parent_regular_children = [
                c
                for c in regular_children
                if c.get("parent_hp_id") == parent_id
                or c.get("hp_id", "").startswith(f"{parent_id}_")
            ]

            all_children = parent_multihop_children + parent_regular_children
            logger.info(
                f"[SORT DEBUG] Parent {parent_id} has {len(all_children)} children: {[c.get('hp_id') for c in all_children]}"
            )

            # Expansion button is always visible for parent rows since there are always children
            parent["has_children"] = True
            parent["is_expanded"] = parent["hp_id"] in self.expanded_hp_ids
            sorted_list.append(parent)
            logger.info(
                f"[SORT DEBUG] Added parent {parent_id} to sorted list (expanded: {parent['is_expanded']})"
            )

            # Only add children if parent is expanded
            if parent["hp_id"] in self.expanded_hp_ids:
                logger.info(
                    f"[SORT DEBUG] Parent {parent_id} is expanded, adding {len(all_children)} children"
                )
                # Sort children: multihop first, then regular by side
                for child in sorted(
                    all_children, key=lambda x: (x.get("hp_id", ""), x.get("side", ""))
                ):
                    sorted_list.append(child)
                    logger.info(
                        f"[SORT DEBUG] Added child {child.get('hp_id')} (side: {child.get('side')}) to sorted list"
                    )
            else:
                logger.info(
                    f"[SORT DEBUG] Parent {parent_id} is collapsed, skipping {len(all_children)} children"
                )

        logger.info(f"[SORT DEBUG] Final sorted list has {len(sorted_list)} items")
        return sorted_list

    def _update_hp_list_view(self, *args):
        """Update the HP list view with current data."""
        logger.debug(f"[BINDING DEBUG] _update_hp_list_view called with args: {args}")
        logger.debug(f"[BINDING DEBUG] hp_list_data length: {len(self.hp_list_data)}")

        # Prevent infinite sync loops
        if getattr(self, "_syncing_hp_data", False):
            logger.debug("Already syncing HP data, skipping to prevent loop")
            return

        # Check if we have the KV layout elements
        if not hasattr(self, "ids") or not hasattr(self.ids, "hp_list_container"):
            logger.warning("HP list container not available, skipping update")
            return

        self._syncing_hp_data = True
        try:
            # Clear existing rows
            self.ids.hp_list_container.clear_widgets()

            # Get sorted HP list data
            sorted_hp_data = self._get_sorted_hp_list()

            if not sorted_hp_data:
                # Show empty state
                from kivy.uix.label import Label

                empty_label = Label(
                    text='No HP positions yet. Click "New Buy HP" or "New Sell HP" to get started.',
                    size_hint_y=None,
                    height=100,
                    halign="center",
                    valign="middle",
                    color=[0.7, 0.7, 0.7, 1],
                )
                empty_label.bind(size=empty_label.setter("text_size"))
                self.ids.hp_list_container.add_widget(empty_label)
            else:
                # Add HP rows
                for hp_data in sorted_hp_data:
                    row_widget = self._create_hp_row_widget(hp_data)
                    self.ids.hp_list_container.add_widget(row_widget)

        finally:
            self._syncing_hp_data = False

    def _create_hp_row_widget(self, hp_data: Dict) -> Widget:
        """Create a widget for an HP row."""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.button import Button
        from kivy.uix.label import Label
        from kivy.graphics import Color, Rectangle, Line

        # Create the main row container
        row = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=40,
            spacing=2,
            padding=[5, 2, 5, 2],
        )

        # Determine styling based on row type
        is_child = hp_data.get("is_child", False)
        side = hp_data.get("side", "")

        # Set background color
        if not is_child and side == "PARENT":
            bg_color = [0.15, 0.25, 0.35, 0.8]  # Parent: Blue
        elif is_child and side == "BUY":
            bg_color = [0.15, 0.3, 0.2, 0.7]  # Buy child: Green
        elif is_child and side == "SELL":
            bg_color = [0.3, 0.15, 0.15, 0.7]  # Sell child: Red
        else:
            bg_color = [0.2, 0.2, 0.2, 0.5]  # Default: Gray

        # Add background
        with row.canvas.before:
            Color(*bg_color)
            rect = Rectangle(size=row.size, pos=row.pos)
            Color(1, 1, 1, 0.1)
            line = Line(width=1)

        def update_graphics(*args):
            rect.size = row.size
            rect.pos = row.pos
            line.points = [row.x, row.y, row.x + row.width, row.y]

        row.bind(size=update_graphics, pos=update_graphics)

        # Left padding for child rows
        if is_child:
            row.add_widget(Label(text="", size_hint_x=None, width=20))

        # Expand/collapse button (for parent rows with children)
        has_children = hp_data.get("has_children", False)
        is_expanded = hp_data.get("is_expanded", False)

        if has_children:
            expand_btn = Button(
                text="▼" if is_expanded else "▶", size_hint_x=None, width=30, height=30
            )
            hp_id = hp_data.get("hp_id", "")
            expand_btn.bind(on_release=lambda x: self.toggle_hp_expansion(hp_id))
            row.add_widget(expand_btn)
        else:
            row.add_widget(Label(text="", size_hint_x=None, width=30))

        # Data columns
        row.add_widget(self._create_column_label(side if is_child else "HP", 0.08))
        row.add_widget(self._create_column_label(hp_data.get("hp_id", ""), 0.1))
        row.add_widget(self._create_column_label(hp_data.get("coin", ""), 0.08))
        row.add_widget(self._create_column_label(hp_data.get("quantity", "0.0"), 0.12))
        row.add_widget(self._create_column_label(hp_data.get("buy_price", "0.0"), 0.1))
        row.add_widget(
            self._create_column_label(hp_data.get("current_price", "0.0"), 0.1)
        )

        # Progress column (show completeness or state info)
        progress_text = (
            f"{float(hp_data.get('realized_quantity', 0)):.3f}"
            if hp_data.get("realized_quantity")
            else "0.000"
        )
        row.add_widget(self._create_column_label(progress_text, 0.08))

        row.add_widget(self._create_column_label(hp_data.get("net", "0.0"), 0.1))
        row.add_widget(self._create_column_label(hp_data.get("state", ""), 0.1))

        # Action buttons
        action_layout = BoxLayout(orientation="horizontal", size_hint_x=0.18, spacing=2)
        action_buttons = hp_data.get("action_buttons", [])
        button_states = hp_data.get("button_states", {})

        if "SELL" in action_buttons:
            sell_btn = Button(text="Sell", size_hint_x=0.5)

            # Apply button state
            sell_state = button_states.get("SELL", {"enabled": True, "text": "Sell"})
            sell_btn.text = sell_state["text"]
            sell_btn.disabled = not sell_state["enabled"]

            if sell_state["enabled"]:
                hp_id = hp_data.get("hp_id", "")
                coin = hp_data.get("coin", "")
                quantity = hp_data.get("quantity", "0.0")
                buy_price = hp_data.get("buy_price", "0.0")
                sell_btn.bind(
                    on_release=lambda x: self.new_sell_hp_button(
                        hp_id, coin, quantity, buy_price
                    )
                )
            action_layout.add_widget(sell_btn)

        if "CANCEL" in action_buttons:
            cancel_btn = Button(text="Cancel", size_hint_x=0.5)

            # Apply button state
            cancel_state = button_states.get(
                "CANCEL", {"enabled": True, "text": "Cancel"}
            )
            cancel_btn.text = cancel_state["text"]
            cancel_btn.disabled = not cancel_state["enabled"]

            if cancel_state["enabled"]:
                hp_id = hp_data.get("hp_id", "")
                symbol = hp_data.get("coin", "")
                # Map side correctly to PositionSide enum values
                if hp_data.get("side") == "BUY":
                    side_value = "LONG"
                else:
                    side_value = "LONG"  # Default to LONG for buy positions
                cancel_btn.bind(
                    on_release=lambda x: self._handle_cancel_button_click(
                        hp_id, symbol, side_value
                    )
                )
            action_layout.add_widget(cancel_btn)

        # Fill remaining space if no buttons
        if not action_buttons:
            action_layout.add_widget(Label(text=""))

        row.add_widget(action_layout)
        return row

    def _create_column_label(self, text: str, width_hint: float) -> Label:
        """Create a standardized column label."""
        label = Label(
            text=str(text), size_hint_x=width_hint, halign="center", valign="middle"
        )
        label.bind(size=label.setter("text_size"))
        return label

    def auto_load_inventory_csv(self):
        """Automatically load inventory from 'inventory.csv' if it exists in current directory."""
        import os

        filename = "inventory.csv"
        if not os.path.exists(filename):
            logger.info(
                "No inventory.csv file found in current directory. Skipping auto-load."
            )
            return

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

            self.portfolio_queue.put_nowait(
                Event(name=EventName.PORTFOLIO_INVENTORY, content=inventory_items)
            )
            logger.info("Auto-loaded inventory from %s", filename)
        except Exception as e:
            logger.error("Failed to auto-load inventory CSV: %s", e)

    def update_hp_state_filter(self, selected_states):
        """Update the HP state filter and refresh the list"""
        self.hp_state_filter = selected_states
        self._update_hp_list_view()
        logger.info("HP state filter updated to: %s", selected_states)

    def on_hp_state_filter_change(self, filter_text):
        """Handle HP state filter dropdown selection"""
        if filter_text == "Active States (11)":
            # Default filter excluding CLOSED and SOLD
            self.hp_state_filter = [
                "NEW",
                "BUYING",
                "PARTIALLY_BOUGHT",
                "BOUGHT",
                "READY_TO_SELL",
                "SELLING",
                "PARTIALLY_SOLD",
                "SOLD_PART_BOUGHT",
                "WAITING_CHILD",
                "NONE",
            ]
            display_text = "Showing 11 states (excludes CLOSED, SOLD)"
        elif filter_text == "All States (13)":
            # Show all states
            self.hp_state_filter = [
                "NEW",
                "BUYING",
                "PARTIALLY_BOUGHT",
                "BOUGHT",
                "READY_TO_SELL",
                "SELLING",
                "PARTIALLY_SOLD",
                "SOLD",
                "PART_SOLD_PART_BOUGHT",
                "SOLD_PART_BOUGHT",
                "CLOSED",
                "WAITING_CHILD",
                "NONE",
            ]
            display_text = "Showing all 13 states"
        elif filter_text == "CLOSED Only":
            # Show only CLOSED states
            self.hp_state_filter = ["CLOSED"]
            display_text = "Showing only CLOSED states"
        elif filter_text == "SOLD Only":
            # Show only SOLD states
            self.hp_state_filter = ["SOLD"]
            display_text = "Showing only SOLD states"
        else:
            # For "Custom..." or other cases, keep current filter
            return

        self._update_hp_list_view()
        if not self.test_mode:
            self.ids.hp_state_filter_display.text = display_text
        logger.info("HP state filter changed to: %s", filter_text)

    def reset_hp_state_filter(self):
        """Reset HP state filter to default (excludes CLOSED and SOLD)"""
        self.hp_state_filter = [
            "NEW",
            "BUYING",
            "PARTIALLY_BOUGHT",
            "BOUGHT",
            "READY_TO_SELL",
            "SELLING",
            "PARTIALLY_SOLD",
            "SOLD_PART_BOUGHT",
            "WAITING_CHILD",
            "NONE",
        ]
        self._update_hp_list_view()
        if not self.test_mode:
            self.ids.hp_state_filter_spinner.text = "Active States (11)"
            self.ids.hp_state_filter_display.text = (
                "Showing 11 states (excludes CLOSED, SOLD)"
            )
        logger.info("HP state filter reset to default")

    def auto_remove_closed_sold_states(self):
        """Automatically remove CLOSED and SOLD states from filter if they exist"""
        current_filter = list(self.hp_state_filter)
        states_to_remove = ["CLOSED", "SOLD"]

        removed_any = False
        for state in states_to_remove:
            if state in current_filter:
                current_filter.remove(state)
                removed_any = True

        if removed_any:
            self.hp_state_filter = current_filter
            self._update_hp_list_view()
            # Update the spinner and display to reflect the change
            if not self.test_mode:
                self.ids.hp_state_filter_spinner.text = "Active States (11)"
                self.ids.hp_state_filter_display.text = (
                    "Showing 11 states (excludes CLOSED, SOLD)"
                )
