import asyncio
import csv
import os
import queue
import logging
import time
from typing import Any, Dict, List, Set, Optional
from kivy.properties import (
    ListProperty,
    ObjectProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, Rectangle, Line
from kivy.uix.widget import Widget
from src.database import Database
from src.identifiers import (
    HPBuyConfig,
    HPBuy,
    HPSellConfig,
    AllTickers,
    Event,
    EventName,
    HPSell,
    RemoveRecord,
    State,
    StateInfo,
    UiState,
    BinanceClient,
    Mode,
    PositionSide,
)
from src.gui.identifiers import (
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
    available_symbols = ListProperty()

    config_dir = os.path.join("src", "strategies", "spot")

    def __init__(
        self,
        client: BinanceClient,
        config_queue: queue.Queue,
        ui_queue: queue.Queue,
        db: Database,
        price_resolver: UsdPriceResolver,
        portfolio_queue: queue.Queue,
        test_mode=False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.client = client
        self.ui_queue = ui_queue
        self.config_queue = config_queue
        self.db = db
        self.price_resolver = price_resolver
        self.portfolio_queue = portfolio_queue
        self.bind(hp_list_data=self._update_hp_list_view)
        self.test_mode = test_mode
        self.stop_event: asyncio.Event = asyncio.Event()
        self.ui_queue_closed = False

        # Initialize task references for proper cleanup
        self.queue_task: Optional[asyncio.Task] = None

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

        # Setup filter dropdown values
        self._setup_filter_dropdown()

        # Setup the unified HP manager
        self.setup_hp_manager()

    def _setup_filter_dropdown(self):
        """Setup the HP state filter dropdown with available options."""
        if (
            not self.test_mode
            and hasattr(self, "ids")
            and hasattr(self.ids, "hp_state_filter_spinner")
        ):
            self.ids.hp_state_filter_spinner.values = [
                "Active States (11)",
                "All States (13)",
                "SOLD Only",
                "CLOSED Only",
            ]

    def show_buy_modal(self):
        """Show Buy HP modal - delegates to HP manager."""
        if hasattr(self, "hp_manager") and self.hp_manager:
            self.hp_manager.show_buy_modal()
        else:
            logger.warning("HP manager not available for buy modal")

    def show_cancel_confirmation(self, hp_id: str, symbol: str, side: str) -> None:
        """Show confirmation dialog for canceling HP position."""

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
        elif side == "SHORT":
            position_side = PositionSide.SHORT
        else:
            position_side = PositionSide.LONG  # Default to LONG for buy positions

        record = RemoveRecord(hp_id=hp_id, symbol=symbol, side=position_side)
        self.config_queue.put_nowait(record)
        logger.info("Remove record added to the queue. %s", record)

        # For multihop positions (sell positions with children), immediately mark parent as CLOSED
        # This ensures the HP gets removed from display after cancellation
        if side == "SHORT" and hasattr(self, "hp_list") and self.hp_list:
            for hp_item in self.hp_list:
                if hp_item.get("hp_id") == hp_id and hp_item.get("children"):
                    logger.info(
                        f"Marking multihop parent {hp_id} as CLOSED after cancellation"
                    )
                    hp_item["state"] = "CLOSED"
                    # Trigger UI refresh to remove the closed item
                    self.auto_remove_closed_sold_states()
                    break

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
            self.hp_manager.create_hp_callback = self.create_hp
            self.hp_manager.cancel_hp_callback = self.cancel_hp
            self.hp_manager.remove_hp_callback = self.remove_hp

            # Set symbols and client for HP manager integration
            self.hp_manager.symbols = self.price_resolver.symbols
            self.hp_manager.client = self.client

            # Update with current data
            self.hp_manager.available_symbols = [
                symbol for symbol, _ in self.price_resolver.symbols.items()
            ]
        else:
            logger.warning("HP manager not found in KV file")

    def create_hp(self, hp_type: str, config: HPConfiguration):
        """Handle HP creation from unified manager."""
        try:
            if hp_type == "BUY":
                self._create_buy_hp_from_config(config)
            else:
                logger.error(
                    f"Unsupported HP type: {hp_type}. Only BUY operations are supported from HP list."
                )
        except Exception as e:
            logger.error(f"Error creating {hp_type} HP: {e}")

    def _create_buy_hp_from_config(self, config: HPConfiguration):
        """Create Buy HP from unified configuration."""
        if not self.price_resolver.symbols.get(config.symbol):
            logger.error(f"Symbol info not found for {config.symbol}")
            return

        new_hp = HPBuy(
            config=HPBuyConfig(
                coin=config.coin,
                symbol=self.price_resolver.symbols[config.symbol],
                price_low=config.price_low or 0.0,
                price_high=config.price_high or 0.0,
                budget=config.budget or 1000.0,
                order_trigger=config.order_trigger if config.order_trigger else 1.0,
                mode=Mode.DCA if config.mode == "DCA" else Mode.SINGLE,
            ),
            state_info=StateInfo(),
        )
        self.config_queue.put_nowait(new_hp)
        logger.info("Buy HP created from unified manager: %s", new_hp)

    def cancel_hp(self, hp_id: str, hp_type: str):
        """Handle HP cancellation from unified manager."""
        try:
            # Get actual position side from HP data instead of relying on hp_type parameter
            side = self._get_position_side_from_hp_id(hp_id)
            symbol = self._get_symbol_from_hp_id(hp_id)

            if side and symbol:
                logger.info(f"Cancelling HP {hp_id} with actual side: {side.value}")
                # Convert PositionSide to the string format expected by trigger_remove_record
                side_str = "SHORT" if side == PositionSide.SHORT else "LONG"
                self.trigger_remove_record(hp_id, symbol, side_str)
            elif not side:
                logger.error(f"Could not determine position side for HP ID: {hp_id}")
            elif not symbol:
                logger.error(f"Could not find symbol for HP ID: {hp_id}")
        except Exception as e:
            logger.error(f"Error cancelling HP {hp_id}: {e}")

    def remove_hp(self, hp_id: str, hp_type: str):
        """Handle HP removal from unified manager."""
        # For now, use same logic as cancel
        self.cancel_hp(hp_id, hp_type)

    def _get_symbol_from_hp_id(self, hp_id: str) -> Optional[str]:
        """Get symbol from HP ID by searching HP list data."""
        for hp_data in self.hp_list_data:
            if hp_data.get("hp_id") == hp_id:
                coin = hp_data.get("coin")
                logger.debug(f"Found HP {hp_id}: coin='{coin}'")
                return coin
        return None

    def _get_position_side_from_hp_id(self, hp_id: str) -> Optional[PositionSide]:
        """Get the position side for a given HP ID by analyzing HP data structure"""
        logger.debug(f"Looking for position side for HP {hp_id}")

        # Look for the HP in hp_list_data
        for hp_data in self.hp_list_data:
            if hp_data.get("hp_id") == hp_id:
                logger.debug(f"Found HP data for {hp_id}: {hp_data}")

                # Check if this HP has multihop children (e.g., 1000a, 1000b) - these are SELL positions
                children = hp_data.get("children", [])
                has_multihop_children = any(
                    isinstance(child, str)
                    and len(child) > 1
                    and child[:-1].isdigit()
                    and child[-1].isalpha()
                    for child in children
                )
                if has_multihop_children:
                    logger.debug(
                        f"HP {hp_id} has multihop children {children}, inferring SHORT position"
                    )
                    return PositionSide.SHORT

                # Check if this HP has explicit sell children (including convert)
                has_sell_child = any(
                    (
                        isinstance(child, str)
                        and (child.endswith("_SELL") or child.endswith("_CONVERT"))
                    )
                    or (
                        isinstance(child, dict)
                        and (
                            child.get("hp_id", "").endswith("_SELL")
                            or child.get("hp_id", "").endswith("_CONVERT")
                            or child.get("side") == "SELL"
                            or "SELL" in child.get("state", "")
                        )
                    )
                    for child in children
                )
                if has_sell_child:
                    logger.debug(
                        f"HP {hp_id} has sell/convert children {children}, inferring SHORT position"
                    )
                    return PositionSide.SHORT

                # Check the state to infer position side
                state = hp_data.get("state", "")
                if "SELL" in state or state in [
                    "SELLING",
                    "SOLD",
                    "SOLD_PART_BOUGHT",
                ]:
                    logger.debug(f"Inferred SHORT position from state: {state}")
                    return PositionSide.SHORT

                # Check if HP ID indicates multihop (e.g., "1000a", "1000b")
                if len(hp_id) > 1 and hp_id[-1].isalpha() and hp_id[:-1].isdigit():
                    logger.debug(
                        f"HP {hp_id} appears to be multihop, inferring SHORT position"
                    )
                    return PositionSide.SHORT

                # Default to LONG for buy positions
                logger.debug(f"HP {hp_id} appears to be BUY position, inferring LONG")
                return PositionSide.LONG

        logger.debug(f"HP {hp_id} not found in hp_list_data")

        return None

    def _check_and_close_parent_if_all_children_closed(
        self, update: HPUpdate, hp_map: Dict[str, Dict]
    ) -> None:
        """Check if this closed HP is a multihop child, and if all its siblings are closed, close the parent."""
        hp_id = update.hp_id

        # Check if this is a multihop child (e.g., "1000a", "1000b")
        if len(hp_id) > 1 and hp_id[-1].isalpha() and hp_id[:-1].isdigit():
            parent_hp_id = hp_id[:-1]  # Extract parent ID (e.g., "1000")
            logger.info(f"Child {hp_id} got CLOSED, checking parent {parent_hp_id}")

            if parent_hp_id in hp_map:
                parent = hp_map[parent_hp_id]
                children = parent.get("children", [])
                logger.info(f"Parent {parent_hp_id} has children: {children}")

                # Check if all children are in CLOSED or SOLD state
                all_children_closed = True
                children_states = []
                for child_id in children:
                    if isinstance(child_id, str) and child_id in hp_map:
                        child_state = hp_map[child_id].get("state", "")
                        children_states.append(f"{child_id}:{child_state}")
                        if child_state not in ["CLOSED", "SOLD"]:
                            all_children_closed = False

                logger.info(
                    f"Children states: {children_states}, all_closed: {all_children_closed}"
                )

                # If all children are closed, mark the parent as closed
                if all_children_closed and children:  # Ensure there are children
                    logger.info(
                        f"All children of parent {parent_hp_id} are CLOSED/SOLD, marking parent as CLOSED"
                    )
                    parent["state"] = "CLOSED"
                    # Trigger another filter update since the parent state changed
                    self.auto_remove_closed_sold_states()
                else:
                    logger.info(
                        f"Not all children closed yet for parent {parent_hp_id}"
                    )

    def _get_buy_child_state(self, update: HPUpdate) -> str:
        """Get appropriate state for buy child based on actual buy operation state.

        Architecture: Children should primarily show the actual operation state (from buy_operation_state)
        when available, falling back to parent-derived states.
        """

        # First priority: Use actual buy operation state if available
        # This comes from the HPGuiDataBuy.data.state_info.state and represents the actual buy operation state
        if hasattr(update, "buy_operation_state") and update.buy_operation_state:
            actual_state = update.buy_operation_state
            return actual_state

        # Fallback: Use parent state to determine child state
        parent_state = update.state.value

        # When parent is actively operating (BUYING/SELLING), child shows operational state
        if parent_state in ["BUYING", "SELLING"]:
            return "BUYING"  # Buy child shows BUYING when parent is actively operating

        # When parent is stable/idle, child shows completion state based on quantities
        total_qty = getattr(update, "total_quantity", 0) or 0
        realized_qty = getattr(update, "realized_quantity", 0) or 0
        current_qty = getattr(update, "quantity", 0) or 0

        # Use the maximum quantity to determine if we have any bought quantity
        bought_qty = max(total_qty, realized_qty, current_qty)

        if parent_state == "NEW":
            return "NEW"
        elif bought_qty > 0:
            # Check if fully bought
            if current_qty >= bought_qty or abs(current_qty - bought_qty) < 0.00001:
                return "BOUGHT"  # Fully bought
            else:
                return "PARTIALLY_BOUGHT"  # Partially bought
        else:
            return "NEW"  # No quantities, still new

    def _get_sell_child_state_from_update(self, update: HPUpdate) -> str:
        """Get sell child state, prioritizing sell operation state from update."""
        # Check if we have specific sell state information in the update
        if hasattr(update, "sell_state") and update.sell_state:
            sell_state = update.sell_state
            if sell_state in ["NEW"]:
                # For NEW state, check the overall strategy state to determine if this is
                # initial setup (idle) or active selling
                if update.state.value == "SELLING":
                    # Strategy is actively selling - show as SELLING
                    return "SELLING"
                else:
                    # Initial setup or other states - show as idle
                    return "NEW"
            elif sell_state in ["PARTIALLY_SOLD"]:
                return "PARTIALLY_SOLD"
            elif sell_state in ["SOLD", "FILLED"]:
                return "SOLD"

        # Fall back to parent state logic
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
        elif parent_state in ["SOLD_PART_BOUGHT"]:
            # Position was sold partially, but the sell operation is complete
            return "SOLD"
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
                        # Only log ticker events every 30 seconds (increased from 10)
                        if current_time - self._last_ticker_log_time > 30.0:
                            logger.debug("[PROCESS_UI_QUEUE] Processing ticker updates")
                            self._last_ticker_log_time = current_time

                    if isinstance(data, HPGuiDataBuy):
                        # Update the HP list with buy position data
                        # Add side information to the update
                        data.hp_update.side = data.data.state_info.side.value
                        # Add actual buy operation state for proper child state determination
                        buy_state = data.data.state_info.state.value
                        data.hp_update.buy_operation_state = buy_state

                        # Update HP list data (KV binding will handle UI updates)
                        self.hp_list_data = self.update_hp_list(
                            update=data.hp_update, hp_list=self.hp_list_data
                        )
                    elif isinstance(data, HPGuiDataSell):
                        # Update the HP list with sell position data
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
                        # Check for data types that might need processing
                        if hasattr(data, "hp_update") and hasattr(data, "data"):
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
                        else:
                            logger.warning(
                                "Unknown data type received in UI queue: %s", type(data)
                            )
            except queue.Empty:
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error("Exception in UI queue processing: %s", e, exc_info=True)
        self.ui_queue_closed = True

    def update_hp_list(self, update: HPUpdate, hp_list: List[Dict]) -> List[Dict]:
        """Update HP list with new container-based approach.

        Every position creates:
        - Parent: Pure numeric ID (e.g., "1000")
        - Regular Buy+Sell: Parent + {parent_id}_BUY + {parent_id}_SELL
        - Two-hop Sell: Parent + {parent_id}a + {parent_id}b
        - Convert Sell: Parent + {parent_id}_CONVERT
        """
        hp_id = update.hp_id

        # Create a map for fast lookup
        hp_map = {item["hp_id"]: item for item in hp_list}

        quantity_usd = (
            update.symbol.format_price(
                update.quantity_usd * self.price_resolver.latest_prices["BTCUSDC"]
            )
            if update.quantity_usd is not None and update.symbol.name.endswith("BTC")
            else (
                update.symbol.format_price(update.quantity_usd)
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

        # Handle position using the new refactored approach
        self._handle_container_position(
            hp_map,
            update,
            hp_id,
            operation_side,
            quantity_usd,
        )

        self.hp_list = list(hp_map.values())

        # Check if the HP position moved to CLOSED or SOLD state and auto-remove from filter if needed
        if update.state.value in ["CLOSED", "SOLD"]:
            self.auto_remove_closed_sold_states()
            # Check if this is a multihop child that got closed, and if all siblings are closed, close the parent
            self._check_and_close_parent_if_all_children_closed(update, hp_map)

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
                        str(update.symbol.format_price(total_invested_amount))
                        if hasattr(update.symbol, "format_price")
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

    def _handle_container_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle new runtime positions with container structure using clean position type detection."""

        # Determine position type
        position_type = self._detect_position_type(hp_id, update)

        logger.debug(f"Processing position {hp_id} as type: {position_type}")

        # Route to appropriate handler based on position type
        if position_type == "parent":
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "regular_parent":
            # For regular operations: create parent + child
            self._handle_regular_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "multihop":
            self._handle_multihop_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "regular":
            self._handle_regular_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        elif position_type == "convert":
            self._handle_convert_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )
        else:
            logger.warning(f"Unknown position type for {hp_id}, treating as parent")
            self._handle_parent_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )

    def _detect_position_type(self, hp_id: str, update: HPUpdate) -> str:
        """Detect the type of position based on HP ID pattern and operation context."""
        # Convert position: numeric + "_CONVERT" (e.g., "1000_CONVERT")
        if "_CONVERT" in hp_id:
            parts = hp_id.split("_CONVERT")
            if len(parts) == 2 and parts[0].isdigit() and parts[1] == "":
                return "convert"

        # Regular position: numeric + "_" + operation (e.g., "1000_BUY", "1000_SELL")
        if "_" in hp_id:
            parts = hp_id.split("_")
            if len(parts) == 2 and parts[0].isdigit() and parts[1] in ["BUY", "SELL"]:
                return "regular"

        # Multihop position: numeric + single letter (e.g., "1000a", "1000b")
        if len(hp_id) >= 2 and hp_id[-1].isalpha() and hp_id[:-1].isdigit():
            return "multihop"

        # Pure numeric (e.g., "1000"): needs context to determine if parent-only or parent+child
        if hp_id.isdigit():
            # For regular BUY/SELL operations, we need to create parent + child
            # For true parent positions (like in multihop), we create parent only
            # We can distinguish by checking if this is a child-creating operation
            if update.side in ["BUY", "SELL"] and not getattr(
                update, "is_child", False
            ):
                return "regular_parent"  # Create parent + child
            else:
                return "parent"  # Create parent only

        return "parent"

    def _handle_parent_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle parent position updates."""
        # Ensure parent container exists
        self._ensure_parent_container(hp_map, update, hp_id)

        # Update parent data based on operation
        parent = hp_map[hp_id]
        parent["state"] = update.state.value

        # Update core price data from the update
        if update.buy_price is not None:
            parent["buy_price"] = (
                str(update.symbol.format_price(update.buy_price))
                if update.symbol
                else str(update.buy_price)
            )
        if update.sell_price is not None:
            parent["sell_price"] = (
                str(update.symbol.format_price(update.sell_price))
                if update.symbol
                else str(update.sell_price)
            )
        if update.expected_return is not None:
            parent["expected_return"] = (
                str(update.symbol.format_price(update.expected_return))
                if update.symbol
                else str(update.expected_return)
            )

        # Update quantity from update data
        if update.quantity is not None:
            # For parent positions, use total_quantity if available, otherwise use quantity
            quantity_to_use = (
                update.total_quantity
                if update.total_quantity is not None
                else update.quantity
            )
            formatted_quantity = (
                str(update.symbol.format_quantity(float(quantity_to_use)))
                if update.symbol
                else str(quantity_to_use)
            )
            parent["quantity"] = formatted_quantity
            print(
                f"HP Manager Frontend: [_handle_regular_parent_position] Set parent quantity to {formatted_quantity} (from {'total_quantity' if update.total_quantity is not None else 'quantity'}) for HP {update.hp_id}"
            )
            parent["realized_quantity"] = (
                formatted_quantity  # For parent, both are the same initially
            )

        # Update quantity_usd if provided
        if quantity_usd and quantity_usd != "0.0":
            parent["quantity_usd"] = quantity_usd

        # Determine operation type
        is_sell_operation = self._is_sell_operation(update, operation_side)

        if is_sell_operation:
            # Update parent quantities for sell operations
            self._update_parent_sell_quantities(parent, update)
        else:
            # Update parent quantities for buy operations
            self._update_parent_buy_quantities(parent, update)

    def _handle_multihop_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle multihop position updates (e.g., '1000a', '1000b')."""
        # Extract parent ID
        parent_hp_id = hp_id[:-1]  # Remove letter suffix

        # Ensure parent container exists
        self._ensure_parent_container(hp_map, update, parent_hp_id)

        # Multihop positions are always sell operations (never buy)
        self._create_multihop_sell_child(hp_map, update, hp_id, parent_hp_id)

    def _handle_regular_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle regular position updates (e.g., '1000_BUY', '1000_SELL')."""
        # Extract parent ID and operation type
        parent_hp_id, child_operation = hp_id.split("_")

        # Ensure parent container exists
        self._ensure_parent_container(hp_map, update, parent_hp_id)

        # Update parent state for sell operations to reflect overall operation state
        if child_operation == "SELL":
            hp_map[parent_hp_id]["state"] = update.state.value

        if child_operation == "BUY":
            self._create_buy_child(
                hp_map, update, hp_id, parent_hp_id, operation_side, quantity_usd
            )
        elif child_operation == "SELL":
            self._create_sell_child(
                hp_map, update, hp_id, parent_hp_id, operation_side, quantity_usd
            )

    def _handle_convert_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle convert position updates (e.g., '1000_CONVERT')."""
        # Extract parent ID
        parent_hp_id = hp_id.split("_CONVERT")[0]

        logger.info("Handling convert position for HP ID: %s", hp_id)

        # Ensure parent container exists
        self._ensure_parent_container(hp_map, update, parent_hp_id)

        logger.info("Parent container ensured for convert position: %s", parent_hp_id)

        # Convert positions create a single sell row (like regular sell but without prior buy)
        self._create_convert_sell_child(
            hp_map, update, hp_id, parent_hp_id, quantity_usd
        )

        logger.info("Convert sell child created for HP ID: %s", hp_id)

    def _handle_regular_parent_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle regular parent position that needs both parent container and child position."""
        # Create parent container
        self._ensure_parent_container(hp_map, update, hp_id)

        # Update parent data based on operation
        parent = hp_map[hp_id]
        parent["state"] = update.state.value

        # Update core price data from the update
        if update.buy_price is not None:
            parent["buy_price"] = (
                str(update.symbol.format_price(update.buy_price))
                if update.symbol
                else str(update.buy_price)
            )
        if update.sell_price is not None:
            parent["sell_price"] = (
                str(update.symbol.format_price(update.sell_price))
                if update.symbol
                else str(update.sell_price)
            )
        if update.expected_return is not None:
            parent["expected_return"] = (
                str(update.symbol.format_price(update.expected_return))
                if update.symbol
                else str(update.expected_return)
            )

        # Update quantity_usd if provided
        if quantity_usd and quantity_usd != "0.0":
            parent["quantity_usd"] = quantity_usd

        # Determine operation type and update parent quantities
        is_sell_operation = self._is_sell_operation(update, operation_side)

        if is_sell_operation:
            # Update parent quantities for sell operations
            self._update_parent_sell_quantities(parent, update)
            # Also update parent quantity_usd from the HPUpdate
            if hasattr(update, "quantity_usd") and update.quantity_usd:
                parent["quantity_usd"] = str(update.quantity_usd)
        else:
            # Update parent quantities for buy operations
            self._update_parent_buy_quantities(parent, update)

        # Determine child HP ID and create child position
        if is_sell_operation:
            child_hp_id = f"{hp_id}_SELL"
            self._create_sell_child(
                hp_map, update, child_hp_id, hp_id, operation_side, quantity_usd
            )
        else:
            child_hp_id = f"{hp_id}_BUY"
            self._create_buy_child(
                hp_map, update, child_hp_id, hp_id, operation_side, quantity_usd
            )

    def _is_sell_operation(self, update: HPUpdate, operation_side: str) -> bool:
        """Determine if this is a sell operation."""
        return (
            operation_side in ["SHORT", "SELL"]
            or update.state.value in ["SELLING", "SOLD", "SOLD_PART_BOUGHT"]
            or "SELL" in update.state.value
        )

    def _ensure_parent_container(
        self, hp_map: Dict[str, Dict], update: HPUpdate, parent_hp_id: str
    ) -> None:
        """Ensure parent container exists with proper initialization."""
        if parent_hp_id not in hp_map or hp_map[parent_hp_id].get("is_child", True):
            # Check if we already have quantity_usd from the original HPUpdate
            # This happens when parent is processed before children
            original_quantity_usd = "0.0"
            if hasattr(update, "quantity_usd") and update.quantity_usd is not None:
                # For multihop positions, update is for the child, but we need parent's quantity_usd
                # Only use update.quantity_usd if this is being called for the actual parent
                if parent_hp_id == update.hp_id:
                    original_quantity_usd = str(update.quantity_usd)

            # For sell-only positions (like inventory sells), initialize with the sell quantity
            initial_quantity = "0.0"
            if hasattr(update, "quantity") and update.quantity is not None:
                initial_quantity = (
                    str(update.symbol.format_quantity(float(update.quantity)))
                    if update.symbol
                    else str(update.quantity)
                )

            hp_map[parent_hp_id] = {
                "hp_id": parent_hp_id,
                "coin": f"{update.coin}USD",
                "state": update.state.value,
                "buy_price": "0.0",
                "quantity": initial_quantity,  # Use quantity from update for sell positions
                "realized_quantity": "0.0",  # Total realized sell quantity
                "quantity_usd": original_quantity_usd,
                "sell_price": "0.0",
                "expected_return": "0.0",
                "current_price": "0.0",
                "net": "0.0",
                "net_percent": "0.0",
                "is_child": False,
                "side": "PARENT",
                "children": [],
                "is_expanded": True,  # Start expanded so children are visible
                "action_buttons": ["SELL", "CANCEL"],
            }
        else:
            # Parent already exists, preserve existing quantity_usd
            # This handles the case where parent was already processed and we're now adding children
            pass

        # Ensure children list exists
        hp_map[parent_hp_id].setdefault("children", [])

    def _update_parent_buy_quantities(self, parent: Dict, update: HPUpdate) -> None:
        """Update parent quantities for buy operations."""
        # Parent should show realized quantity (what has actually been filled/bought)
        if update.total_quantity is not None:
            total_bought = float(update.total_quantity)
            print(
                f"HP Manager Frontend: Using total_quantity={total_bought} for parent position"
            )
        else:
            total_bought = (
                float(update.quantity) if update.quantity is not None else 0.0
            )
            print(
                f"HP Manager Frontend: Using current quantity={total_bought} for parent position"
            )

        parent["quantity"] = str(update.symbol.format_quantity(total_bought))
        print(
            f"HP Manager Frontend: [_update_parent_buy_quantities] Set parent quantity to {parent['quantity']} (total_bought={total_bought}) for HP {update.hp_id}"
        )

        # Ensure realized_quantity exists
        if "realized_quantity" not in parent:
            parent["realized_quantity"] = "0.0"

    def _update_parent_sell_quantities(self, parent: Dict, update: HPUpdate) -> None:
        """Update parent quantities for sell operations."""
        # For convert-only positions, use the quantity from the update since there's no actual buying
        if (
            update.symbol
            and hasattr(update.symbol, "is_convert_only")
            and update.symbol.is_convert_only
        ):
            total_bought_qty = float(update.quantity) if update.quantity else 0.0
        else:
            # Use total_quantity from update if available, otherwise fall back to existing parent data
            total_bought_qty = (
                float(update.total_quantity)
                if hasattr(update, "total_quantity")
                and update.total_quantity is not None
                else float(parent.get("quantity", "0.0"))
            )

        # Calculate sold quantity based on remaining quantity
        remaining_qty = float(update.quantity) if update.quantity else 0.0
        sold_qty = max(0.0, total_bought_qty - remaining_qty)

        # Update parent quantities
        parent["quantity"] = str(update.symbol.format_quantity(total_bought_qty))

        # Parent realized_quantity should use the update's realized_quantity when available
        if update.realized_quantity is not None:
            # Use the realized_quantity from the update (this is what was actually sold)
            parent["realized_quantity"] = str(
                update.symbol.format_quantity(float(update.realized_quantity))
            )
        else:
            # Fallback: try to get from sell child data
            sell_child_realized_qty = self._get_sell_child_realized_quantity(
                update.hp_id
            )
            parent["realized_quantity"] = str(
                update.symbol.format_quantity(sell_child_realized_qty)
            )

    def _create_multihop_sell_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
    ) -> None:
        """Create multihop sell child."""
        parent = hp_map[parent_hp_id]

        # When adding the first multihop child, remove any regular sell child (_SELL)
        # that may have been created when the parent was initially processed
        regular_sell_child_id = f"{parent_hp_id}_SELL"
        if regular_sell_child_id in parent.get("children", []):
            parent["children"].remove(regular_sell_child_id)
            if regular_sell_child_id in hp_map:
                del hp_map[regular_sell_child_id]

        # Get quantities from parent, but for multihop, use update quantity if parent is still 0
        parent_qty = float(parent.get("quantity", "0.0"))

        # Check if this is a regular sell child (e.g., "1000_SELL") vs actual multihop child (e.g., "1000a")
        is_regular_sell_child = hp_id.endswith("_SELL")

        if parent_qty == 0.0 and update.quantity and not is_regular_sell_child:
            # This is likely the first multihop child, use the original quantity
            total_bought_qty = float(update.quantity)
            # Update parent with the correct quantity and quantity_usd
            parent["quantity"] = str(update.symbol.format_quantity(total_bought_qty))
            # Calculate quantity_usd for parent using parent's buy price (not multihop child's)
            parent_buy_price = float(parent.get("buy_price", "0.0"))
            parent_quantity_usd = total_bought_qty * parent_buy_price
            parent["quantity_usd"] = (
                str(update.symbol.format_price(parent_quantity_usd))
                if update.symbol
                else f"{parent_quantity_usd:.2f}"
            )
        else:
            total_bought_qty = parent_qty

        # For multihop children, determine the correct quantity to display
        if not is_regular_sell_child:
            # For multihop children, use current remaining quantity (update.quantity)
            # for ongoing positions, and total_quantity only for initial setup
            if update.quantity is not None:
                child_qty = float(update.quantity)
            elif hasattr(update, "total_quantity") and update.total_quantity:
                child_qty = float(update.total_quantity)
            else:
                child_qty = total_bought_qty
        else:
            child_qty = total_bought_qty

        # Store the parent's quantity_usd AFTER potentially setting it above
        # so it doesn't get overwritten by _update_parent_sell_quantities
        parent_quantity_usd_saved = parent.get("quantity_usd", "0.0")

        # Calculate actually sold quantity from sell completion if available
        if (
            hasattr(update, "realized_quantity")
            and update.realized_quantity is not None
        ):
            # Use actual realized quantity from sell order if available
            actually_sold_qty = update.realized_quantity
        elif (
            hasattr(update, "sell_completeness")
            and update.sell_completeness is not None
        ):
            # Fallback: Use sell completeness to calculate realized quantity for sell operations
            actually_sold_qty = child_qty * update.sell_completeness
        else:
            actually_sold_qty = float(parent.get("realized_quantity", "0.0"))

        # Calculate quantity_usd based on remaining quantity for multihop children
        sell_child_quantity_usd = child_qty * (
            update.buy_price if update.buy_price else 0.0
        )
        sell_child_quantity_usd_str = (
            str(update.symbol.format_price(sell_child_quantity_usd))
            if update.symbol
            else f"{sell_child_quantity_usd:.2f}"
        )

        sell_child = {
            "hp_id": hp_id,
            "coin": update.symbol.name,
            "buy_price": (
                str(update.symbol.format_price(update.buy_price))
                if update.buy_price
                else "0.0"
            ),
            "quantity": str(update.symbol.format_quantity(child_qty)),
            "realized_quantity": str(update.symbol.format_quantity(actually_sold_qty)),
            "quantity_usd": sell_child_quantity_usd_str,
            "sell_price": (
                str(update.symbol.format_price(update.sell_price))
                if update.sell_price
                else "0.0"
            ),
            "expected_return": (
                str(update.symbol.format_price(update.expected_return))
                if update.expected_return
                else "0.0"
            ),
            "current_price": (
                str(update.symbol.format_price(update.current_price))
                if update.current_price
                else "0.0"
            ),
            "net": (
                str(update.symbol.format_price(update.net)) if update.net else "0.0"
            ),
            "net_percent": str(update.net_percent) if update.net_percent else "0.0",
            "state": self._get_sell_child_state_from_update(update),
            "sell_completeness": str(getattr(update, "sell_completeness", 0.0)),
            "is_child": True,
            "side": "SELL",
            "parent_hp_id": parent_hp_id,
            "action_buttons": ["CANCEL"],
        }

        hp_map[hp_id] = sell_child
        if hp_id not in parent["children"]:
            parent["children"].append(hp_id)

        # Update parent quantities
        self._update_parent_sell_quantities(parent, update)

        # Restore the parent's quantity_usd after _update_parent_sell_quantities
        # to prevent it from being overwritten by child processing
        parent["quantity_usd"] = parent_quantity_usd_saved

    def _create_buy_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Create regular buy child (e.g., '1000_BUY')."""
        # Get total quantity for buy child display - use expected_quantity if available
        total_bought_qty_raw = getattr(update, "total_quantity", None)
        update.total_quantity
        total_bought_qty = (
            float(total_bought_qty_raw)
            if total_bought_qty_raw
            else (float(update.quantity) if update.quantity else 0.0)
        )

        # Get orders total quantity (sum of all buy order quantities)
        orders_total_qty_raw = getattr(update, "orders_total_quantity", None)
        orders_total_qty = float(orders_total_qty_raw) if orders_total_qty_raw else 0.0

        # Get expected quantity (total quantity that should be bought based on budget)
        expected_qty_raw = getattr(update, "expected_quantity", None)
        expected_qty = float(expected_qty_raw) if expected_qty_raw else total_bought_qty

        # Calculate quantity_usd
        buy_child_quantity_usd = total_bought_qty * (update.buy_price or 0.0)
        buy_child_quantity_usd_str = (
            str(update.symbol.format_price(buy_child_quantity_usd))
            if update.symbol
            else f"{buy_child_quantity_usd:.2f}"
        )

        buy_child = {
            "hp_id": hp_id,
            "coin": update.symbol.name,
            "buy_price": (
                str(update.symbol.format_price(update.buy_price))
                if update.buy_price
                else "0.0"
            ),
            "quantity": str(
                update.symbol.format_quantity(orders_total_qty)
            ),  # Use sum of all buy order quantities (total to be bought)
            "realized_quantity": str(
                update.symbol.format_quantity(total_bought_qty)  # Use actual progress
            ),
            "quantity_usd": buy_child_quantity_usd_str,
            "current_price": (
                str(update.symbol.format_price(update.current_price))
                if update.current_price
                else "0.0"
            ),
            "net": (
                str(update.symbol.format_price(update.net)) if update.net else "0.0"
            ),
            "net_percent": str(update.net_percent) if update.net_percent else "0.0",
            "state": self._get_buy_child_state(update),
            "is_child": True,
            "side": "BUY",
            "parent_hp_id": parent_hp_id,
            "action_buttons": ["CANCEL"],
        }

        hp_map[hp_id] = buy_child
        parent = hp_map[parent_hp_id]
        if hp_id not in parent["children"]:
            parent["children"].append(hp_id)

        # Update parent with buy data
        parent["buy_price"] = buy_child["buy_price"]
        parent["net"] = buy_child["net"]
        parent["net_percent"] = buy_child["net_percent"]
        parent["state"] = update.state.value

        # Update parent expected_return if available in the update
        if update.expected_return is not None:
            parent["expected_return"] = (
                str(update.symbol.format_price(update.expected_return))
                if update.symbol
                else str(update.expected_return)
            )

        # Update parent quantities
        self._update_parent_buy_quantities(parent, update)

    def _create_sell_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Create regular sell child (e.g., '1000_SELL')."""

        # Create sell child
        self._create_multihop_sell_child(hp_map, update, hp_id, parent_hp_id)

        # Update parent with sell data
        parent = hp_map[parent_hp_id]
        sell_child = hp_map[hp_id]
        parent["buy_price"] = sell_child["buy_price"]
        parent["sell_price"] = sell_child["sell_price"]
        parent["expected_return"] = sell_child["expected_return"]

    def _create_convert_sell_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_hp_id: str,
        quantity_usd: str,
    ) -> None:
        """Create convert sell child (e.g., '1000_CONVERT')."""
        # Convert positions create a single sell row similar to regular sell
        # but without a prior buy operation

        # Calculate quantity for display
        quantity = float(update.quantity) if update.quantity else 0.0

        convert_sell_child = {
            "hp_id": hp_id,
            "coin": update.symbol.name,
            "buy_price": (
                str(update.symbol.format_price(update.buy_price))
                if update.buy_price
                else "0.0"
            ),
            "quantity": str(update.symbol.format_quantity(quantity)),
            "realized_quantity": str(update.symbol.format_quantity(quantity)),
            "quantity_usd": quantity_usd,
            "sell_price": (
                str(update.symbol.format_price(update.sell_price))
                if update.sell_price
                else "0.0"
            ),
            "expected_return": (
                str(update.symbol.format_price(update.expected_return))
                if update.expected_return
                else "0.0"
            ),
            "current_price": (
                str(update.symbol.format_price(update.current_price))
                if update.current_price
                else "0.0"
            ),
            "net": (
                str(update.symbol.format_price(update.net)) if update.net else "0.0"
            ),
            "net_percent": str(update.net_percent) if update.net_percent else "0.0",
            "state": update.state.value,
            "sell_completeness": str(getattr(update, "sell_completeness", 0.0)),
            "is_child": True,
            "side": "SELL",
            "parent_hp_id": parent_hp_id,
            "action_buttons": ["CANCEL"],
        }

        hp_map[hp_id] = convert_sell_child
        parent = hp_map[parent_hp_id]
        if hp_id not in parent["children"]:
            parent["children"].append(hp_id)

        # Update parent with convert sell data
        parent["buy_price"] = convert_sell_child["buy_price"]
        parent["quantity_usd"] = convert_sell_child["quantity_usd"]
        parent["sell_price"] = convert_sell_child["sell_price"]
        parent["expected_return"] = convert_sell_child["expected_return"]

        # For convert positions, handle realized_quantity based on state
        if update.state.value == State.SOLD.value:
            # After completion, parent should show the actual realized quantity
            parent["realized_quantity"] = convert_sell_child["realized_quantity"]
        # else: During initialization and processing, keep parent realized_quantity as is (0.0)

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
                        current_price = self.price_resolver.symbols[
                            symbol
                        ].format_price(price=float(ticker["c"]))
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
                            strategy["net"] = self.price_resolver.symbols[
                                symbol
                            ].format_price(net_usd)
                            strategy["net_percent"] = str(net_percent)
                    # Handle direct symbol matches (e.g., BTCUSDT)
                    elif symbol == strategy["coin"]:
                        current_price = self.price_resolver.symbols[
                            symbol
                        ].format_price(price=float(ticker["c"]))
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
                            strategy["net"] = self.price_resolver.symbols[
                                symbol
                            ].format_price(net_usd)
                            strategy["net_percent"] = str(net_percent)
        # Only trigger visual refresh if significant changes occurred
        # Use throttling to ensure 1-second refresh interval for prices
        if getattr(self, "test_mode", False):
            self._update_hp_list_view()
        else:
            # Throttle HP list view updates to 1 second maximum frequency
            current_time = time.time()
            if current_time - self._last_view_update_time > 1.0:
                self._update_hp_list_view()
                self._last_view_update_time = current_time

    def sell_hp_button(self, hp_id, coin, quantity, buy_price):
        """Show confirmation dialog for selling HP position."""

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

            if symbol not in self.price_resolver.symbols:
                fallback_symbol = f"{coin_symbol}USDT"
                if fallback_symbol in self.price_resolver.symbols:
                    logger.info(
                        f"Using fallback symbol {fallback_symbol} instead of {symbol}"
                    )
                    symbol = fallback_symbol
                else:
                    logger.error(
                        f"Symbol info not found for {symbol} or fallback {fallback_symbol}"
                    )
                    return

            sell_config = HPSell(
                config=HPSellConfig(
                    hp_id=hp_id,  # Use the same HP ID to create sell child
                    coin=coin_symbol,
                    buy_price=float(buy_price),
                    sell_price=sell_price,
                    quantity=float(quantity),
                    end_currency="USDC",
                    symbol=self.price_resolver.symbols[symbol],
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
        config = HPSellConfig(
            hp_id=hp_id, symbol=self.price_resolver.symbols[f"{coin}USDT"]
        )
        state_info = StateInfo(
            side=PositionSide.SHORT, ui_state=UiState.CLOSED, state=State.CLOSED
        )

        self.config_queue.put_nowait(
            RemoveRecord(hp_id=config.hp_id, symbol=f"{coin}USDT", side=state_info.side)
        )

        logger.info("Cancel sell send to the config queue: %s", config)

    def _has_sell_child(self, hp_id: str) -> bool:
        """Check if HP has an active sell child (excludes cancelled/closed positions)"""
        for item in self.hp_list_data:
            if item.get("hp_id") == f"{hp_id}_SELL":
                # Check if the sell child is in an active state
                state = item.get("state", "")
                # Count as "has sell child" for clearly active states
                if state in ["SELLING", "PARTIALLY_SOLD"]:
                    return True
                # For NEW state, assume it's active (legitimate new sell position)
                # The main issue was with the list filtering, not this check
                elif state == "NEW":
                    return True
                # Only exclude clearly inactive states
                elif state in ["CLOSED", "CANCELLED", "SOLD"]:
                    return False
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
        """Cancel parent HP - determine actual position side instead of assuming BUY"""
        has_sell_child = self._has_sell_child(hp_id)

        if has_sell_child:
            # First cancel the sell child
            self._cancel_sell_child(hp_id, symbol)
            # Note: After sell child is cancelled, user can click cancel again to cancel buy
        else:
            # No sell child, determine the actual position side from HP data
            actual_side = self._get_position_side_from_hp_id(hp_id)
            if actual_side:
                side_str = "SHORT" if actual_side == PositionSide.SHORT else "LONG"
                logger.info(
                    f"Cancelling parent HP {hp_id} with determined side: {side_str}"
                )
                self.show_cancel_confirmation(hp_id, symbol, side_str)
            else:
                # Fallback to LONG if we can't determine the side
                logger.warning(
                    f"Could not determine side for HP {hp_id}, defaulting to LONG"
                )
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
            if item.get("hp_id", "").startswith(f"{hp_id}_") and item.get(
                "is_child", False
            ):
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

        filtered_data = [
            hp
            for hp in self.hp_list_data
            if hp.get("state", "") in self.hp_state_filter
        ]

        # Separate parents and children
        parents = [
            hp
            for hp in filtered_data
            if not hp.get("is_child", False) and hp.get("side", "") == "PARENT"
        ]

        multihop_children = [
            hp
            for hp in filtered_data
            if hp.get("is_child", False)
            and hp.get("hp_id", "")[-1:].isalpha()
            and "_" not in hp.get("hp_id", "")
        ]

        regular_children = [
            hp
            for hp in filtered_data
            if hp.get("is_child", False) and "_" in hp.get("hp_id", "")
        ]

        sorted_list = []
        for parent in sorted(parents, key=lambda x: int(x.get("hp_id", "0"))):
            # Find children for this parent
            parent_id = parent["hp_id"]

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

            # Expansion button is always visible for parent rows since there are always children
            parent["has_children"] = True
            parent["is_expanded"] = parent["hp_id"] in self.expanded_hp_ids
            sorted_list.append(parent)

            # Only add children if parent is expanded
            if parent["hp_id"] in self.expanded_hp_ids:
                # Sort children: multihop first, then regular by side
                for child in sorted(
                    all_children, key=lambda x: (x.get("hp_id", ""), x.get("side", ""))
                ):
                    sorted_list.append(child)

        return sorted_list

    def _update_hp_list_view(self, *args):
        """Update the HP list view with current data."""

        # Check if we have the KV layout elements
        if not hasattr(self, "ids") or not hasattr(self.ids, "hp_list_container"):
            logger.warning("HP list container not available, skipping update")
            # In test environments, the KV container may not be available
            # but we should still allow the data to be processed
            return

        # Clear existing rows
        self.ids.hp_list_container.clear_widgets()

        # Get sorted HP list data
        sorted_hp_data = self._get_sorted_hp_list()

        if not sorted_hp_data:
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

    def _create_hp_row_widget(self, hp_data: Dict) -> Widget:
        """Create a widget for an HP row."""

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
        row.add_widget(self._create_column_label(hp_data.get("buy_price", "0.0"), 0.09))
        row.add_widget(self._create_column_label(hp_data.get("sell_price", "—"), 0.09))
        row.add_widget(
            self._create_column_label(hp_data.get("current_price", "0.0"), 0.09)
        )

        # Progress column (show completeness percentage or state info)
        progress_value = 0.0
        if hp_data.get("sell_completeness"):
            # For SELL positions, use sell_completeness as percentage
            try:
                progress_value = float(hp_data.get("sell_completeness", 0.0)) * 100
            except (ValueError, TypeError):
                progress_value = 0.0
        elif hp_data.get("realized_quantity") and hp_data.get("quantity"):
            # For other positions, calculate based on realized vs total quantity
            try:
                realized = float(hp_data.get("realized_quantity", 0))
                total = float(hp_data.get("quantity", 1))  # Avoid division by zero
                progress_value = (realized / total) * 100 if total > 0 else 0.0
            except (ValueError, TypeError):
                progress_value = 0.0

        progress_text = f"{progress_value:.1f}%"
        row.add_widget(self._create_column_label(progress_text, 0.07))

        row.add_widget(self._create_column_label(hp_data.get("net", "0.0"), 0.09))
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
                    on_release=lambda x: self.sell_hp_button(
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
        if (
            not self.test_mode
            and hasattr(self, "ids")
            and hasattr(self.ids, "hp_state_filter_display")
        ):
            try:
                self.ids.hp_state_filter_display.text = display_text
            except Exception as e:
                logger.error(f"Error updating filter display text: {e}")
        logger.info("HP state filter changed to: %s", filter_text)

    def reset_hp_state_filter(self):
        """Reset HP state filter to default (excludes CLOSED and SOLD)"""
        try:
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
            if not self.test_mode and hasattr(self, "ids"):
                if hasattr(self.ids, "hp_state_filter_spinner"):
                    self.ids.hp_state_filter_spinner.text = "Active States (11)"
                if hasattr(self.ids, "hp_state_filter_display"):
                    self.ids.hp_state_filter_display.text = (
                        "Showing 11 states (excludes CLOSED, SOLD)"
                    )
            logger.info("HP state filter reset to default")
        except Exception as e:
            logger.error(f"Error resetting HP state filter: {e}")
            # At minimum, update the filter data even if UI update fails
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
            if not self.test_mode and hasattr(self, "ids"):
                try:
                    if hasattr(self.ids, "hp_state_filter_spinner"):
                        self.ids.hp_state_filter_spinner.text = "Active States (11)"
                    if hasattr(self.ids, "hp_state_filter_display"):
                        self.ids.hp_state_filter_display.text = (
                            "Showing 11 states (excludes CLOSED, SOLD)"
                        )
                except Exception as e:
                    logger.error(f"Error updating filter UI after auto-remove: {e}")
