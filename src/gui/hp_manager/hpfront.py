import asyncio
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
from kivy.uix.widget import Widget
from src.database import Database
from src.gui.hp_manager.modal_configurators import BuyHPModal
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
from src.gui.hp_manager.hp_position_updater import HPPositionUpdater
from src.gui.hp_manager.hp_child_creator import HPChildCreator
from src.gui.hp_manager.hp_state_calculator import HPStateCalculator
from src.gui.hp_manager.hp_row_renderer import HPRowRenderer
from src.gui.hp_manager.hp_list_filter import HPListFilter


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
    available_symbols = ListProperty()

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

        # Initialize refactored components
        self.position_updater = HPPositionUpdater()
        self.state_calculator = HPStateCalculator(
            hp_list_data_getter=lambda: self.hp_list_data
        )
        self.child_creator = HPChildCreator(
            buy_state_getter_callback=self.state_calculator.get_buy_child_state,
            sell_state_getter_callback=self.state_calculator.get_sell_child_state_from_update,
            position_updater=self.position_updater,
        )
        self.row_renderer = HPRowRenderer(
            toggle_expansion_callback=self.toggle_hp_expansion,
            sell_callback=self.sell_hp_button,
            cancel_callback=self._handle_cancel_button_click,
        )
        self.list_filter = HPListFilter(expanded_hp_ids=self.expanded_hp_ids)

    def initialize(self):
        self.queue_task = asyncio.create_task(self.process_ui_queue())

        # Initialize the HP list view
        if hasattr(self, "ids") and hasattr(self.ids, "hp_list_container"):
            # Trigger initial HP list update
            self._update_hp_list_view()

        # Setup filter dropdown values
        self._setup_filter_dropdown()

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
        """Show Buy HP modal - directly instantiate and show modal."""

        if self.test_mode:
            logger.warning("Buy modal not available in test mode")
            return

        available_symbols = [
            symbol for symbol, _ in self.price_resolver.symbols.items()
        ]
        modal = BuyHPModal(
            callback=lambda config: self.create_hp("BUY", config),
            available_symbols=available_symbols,
            symbols=self.price_resolver.symbols,
            client=self.client,
        )
        modal.open()

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
        logger.info("Buy HP created from modal: %s", new_hp)

    def cancel_hp(self, hp_id: str, hp_type: str = "BUY"):
        """Cancel HP position - convenience method for tests and programmatic cancellation.

        Args:
            hp_id: The HP ID to cancel
            hp_type: "BUY" or "SELL" - used to determine position side
        """
        # Get actual position side from HP data
        side = self._get_position_side_from_hp_id(hp_id)
        symbol = self._get_symbol_from_hp_id(hp_id)

        if side and symbol:
            # Convert PositionSide to string format
            side_str = "SHORT" if side == PositionSide.SHORT else "LONG"
            logger.info(f"Cancelling HP {hp_id} with side: {side_str}")
            self.trigger_remove_record(hp_id, symbol, side_str)
        elif not side:
            logger.error(f"Could not determine position side for HP ID: {hp_id}")
        elif not symbol:
            logger.error(f"Could not find symbol for HP ID: {hp_id}")

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
        """Get appropriate state for buy child. Delegates to state_calculator."""
        return self.state_calculator.get_buy_child_state(update)

    def _get_sell_child_state_from_update(self, update: HPUpdate) -> str:
        """Get sell child state. Delegates to state_calculator."""
        return self.state_calculator.get_sell_child_state_from_update(update)

    def _get_sell_child_state(self, update: HPUpdate, sell_data=None) -> str:
        """Get appropriate state for sell child. Delegates to state_calculator."""
        return self.state_calculator.get_sell_child_state(update, sell_data)

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
        """Detect the type of position. Delegates to position updater."""
        return self.position_updater._detect_position_type(hp_id, update)

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
        self.child_creator.create_multihop_child_with_parent_update(hp_map, update, hp_id, parent_hp_id)

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
            self.child_creator.create_buy_child_with_parent_update(
                hp_map, update, hp_id, parent_hp_id, operation_side, quantity_usd
            )
        elif child_operation == "SELL":
            self.child_creator.create_sell_child_with_parent_update(
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
        self.child_creator.create_convert_child_with_parent_update(
            hp_map, update, hp_id, parent_hp_id, None, quantity_usd
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
        # Note: We use the non-updating version here because parent quantities are already updated above
        if is_sell_operation:
            child_hp_id = f"{hp_id}_SELL"
            self.child_creator.create_sell_child(
                hp_map, update, child_hp_id, hp_id, operation_side, quantity_usd
            )
        else:
            child_hp_id = f"{hp_id}_BUY"
            self.child_creator.create_buy_child(
                hp_map, update, child_hp_id, hp_id, operation_side, quantity_usd
            )

    def _is_sell_operation(self, update: HPUpdate, operation_side: str) -> bool:
        """Determine if this is a sell operation. Delegates to position updater."""
        return self.position_updater.is_sell_operation(update, operation_side)

    def _ensure_parent_container(
        self, hp_map: Dict[str, Dict], update: HPUpdate, parent_hp_id: str
    ) -> None:
        """Ensure parent container exists. Delegates to position updater."""
        self.position_updater.ensure_parent_container(hp_map, update, parent_hp_id)

    def _update_parent_buy_quantities(self, parent: Dict, update: HPUpdate) -> None:
        """Update parent quantities for buy operations. Delegates to position updater."""
        self.position_updater.update_parent_buy_quantities(parent, update)

    def _update_parent_sell_quantities(self, parent: Dict, update: HPUpdate) -> None:
        """Update parent quantities for sell operations. Delegates to position updater."""
        self.position_updater.update_parent_sell_quantities(parent, update)

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
        """Check if HP has an active sell child. Delegates to state_calculator."""
        return self.state_calculator.has_sell_child(hp_id)

    def _get_sell_child_realized_quantity(self, hp_id: str) -> float:
        """Get the realized sell quantity from sell child. Delegates to state_calculator."""
        return self.state_calculator.get_sell_child_realized_quantity(hp_id)

    def _determine_action_buttons(self, hp_data: dict) -> dict:
        """Determine which action buttons to show and their states. Delegates to state_calculator."""
        return self.state_calculator.determine_action_buttons(hp_data)

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
        """Get sorted HP list. Delegates to list filter."""
        return self.list_filter.get_sorted_hp_list(
            self.hp_list_data, self.hp_state_filter
        )

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
        """Create a widget for an HP row. Delegates to row renderer."""
        return self.row_renderer.create_hp_row_widget(hp_data)

    def on_hp_state_filter_change(self, filter_text):
        """Handle HP state filter dropdown selection. Delegates to list filter."""
        # Get filter preset
        self.hp_state_filter = HPListFilter.get_filter_preset(filter_text)

        # Determine display text
        display_text_map = {
            "Active States (11)": "Showing 11 states (excludes CLOSED, SOLD)",
            "All States (13)": "Showing all 13 states",
            "Show Only CLOSED": "Showing only CLOSED states",
            "Show Only SOLD": "Showing only SOLD states",
        }
        display_text = display_text_map.get(filter_text)

        if display_text is None:
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
