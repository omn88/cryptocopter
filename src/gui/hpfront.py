import asyncio
import csv
from datetime import datetime
import os
import queue
import logging
from typing import Dict, List, Set, Optional
import uuid
from kivy.properties import (
    ListProperty,
    ObjectProperty,
    StringProperty,
)

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
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
from src.gui.searchable_drop_down import SearchableDropDown
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.gui.unified import UnifiedHPManager, HPConfiguration


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
        self.refresh_task: Optional[asyncio.Task] = None
        self.queue_task: Optional[asyncio.Task] = None
        self._syncing_unified_data = False  # Prevent sync loops

        # Suppress GUI initialization when in test mode
        if not self.test_mode:
            self.symbol_input = SearchableDropDown(
                client=self.client, options=self.symbols, symbols_info=self.symbols_info
            )
            # Note: symbol_input will be used by unified HP manager modals
            # No need to add to layout here as unified manager handles this

            # Initialize Unified HP Manager (will be set by KV file)
            self.unified_hp_manager = None

    def initialize(self):
        self.queue_task = asyncio.create_task(self.process_ui_queue())

        # Setup unified HP manager if available
        if hasattr(self, "ids") and hasattr(self.ids, "unified_hp_manager"):
            self.setup_unified_hp_manager()

        # Note: CSV auto-loading is now handled by portfolio_gui.py in proper priority order

    def trigger_add_record(self, *args) -> None:
        # This method is deprecated - HP creation now handled by unified HP manager
        logger.warning(
            "trigger_add_record called but deprecated - use unified HP manager"
        )
        return

    def trigger_remove_record(
        self,
        hp_id: str,
        symbol: str,
        side: str,
        *args,
    ) -> None:
        record = RemoveRecord(hp_id=hp_id, symbol=symbol, side=PositionSide(side))
        self.config_queue.put_nowait(record)
        logger.info("Remove record added to the queue. %s", record)

    # Unified HP Manager callback methods
    def setup_unified_hp_manager(self):
        """Setup the unified HP manager with callbacks."""
        # Get the unified HP manager from the KV file
        if hasattr(self, "ids") and hasattr(self.ids, "unified_hp_manager"):
            self.unified_hp_manager = self.ids.unified_hp_manager

            # Set up callbacks
            self.unified_hp_manager.create_hp_callback = self.on_unified_create_hp
            self.unified_hp_manager.cancel_hp_callback = self.on_unified_cancel_hp
            self.unified_hp_manager.remove_hp_callback = self.on_unified_remove_hp

            # Set symbols_info and client for SearchableDropDown integration
            self.unified_hp_manager.symbols_info = self.symbols_info
            self.unified_hp_manager.client = self.client

            # Update with current data
            self.unified_hp_manager.update_symbols(self.symbols)
            self._sync_unified_hp_data()
        else:
            logger.warning("Unified HP manager not found in KV file")

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

    def _sync_unified_hp_data(self):
        """Sync current HP data with unified manager."""
        if not self.unified_hp_manager:
            logger.warning("No unified HP manager available for sync")
            return

        # Prevent sync loops
        if getattr(self, "_syncing_unified_data", False):
            return

        self._syncing_unified_data = True
        try:
            logger.info(
                f"Syncing {len(self.hp_list_data)} HP positions to unified manager"
            )

            # Preserve expansion state before clearing
            expanded_hp_ids = self.unified_hp_manager.hp_data.expanded_hp_ids.copy()

            # Clear existing data
            self.unified_hp_manager.clear_all_positions()

            # Restore expansion state
            self.unified_hp_manager.hp_data.expanded_hp_ids = expanded_hp_ids

            # Directly add positions without complex categorization - this is dev data
            for hp_data in self.hp_list_data:
                try:
                    hp_id = hp_data.get("hp_id", "")
                    is_child = hp_data.get("is_child", False)

                    if is_child:
                        # Determine child type based on side
                        side = hp_data.get("side", "BUY")
                        child_type = "BUY" if side in ["BUY", "LONG"] else "SELL"
                        self.unified_hp_manager.add_hp_position(
                            child_type, hp_id, hp_data
                        )
                        logger.debug(f"Added child: {hp_id} (type: {child_type})")
                    else:
                        # Parent container
                        self.unified_hp_manager.add_hp_position("HP", hp_id, hp_data)
                        logger.debug(f"Added parent: {hp_id}")

                except Exception as e:
                    logger.error(f"Error adding HP position {hp_data}: {e}")

            logger.info("Unified HP sync completed")
        finally:
            self._syncing_unified_data = False

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
        logger.info(
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
                    logger.info(
                        f"[PROCESS_UI_QUEUE] Received data type: {type(data)}, isinstance HPGuiDataBuy: {isinstance(data, HPGuiDataBuy)}, isinstance HPGuiDataSell: {isinstance(data, HPGuiDataSell)}"
                    )
                    if isinstance(data, HPGuiDataBuy):
                        # Update the HP list with buy position data
                        logger.info("UI received BUY position data: %s", data)
                        # Add side information to the update
                        data.hp_update.side = data.data.state_info.side.value
                        self.hp_list_data = self.update_hp_list(
                            update=data.hp_update, hp_list=self.hp_list_data
                        )
                    elif isinstance(data, HPGuiDataSell):
                        # Update the HP list with sell position data
                        logger.info("UI received SELL position data: %s", data)
                        logger.info(
                            f"Data type check: {type(data)}, isinstance result: {isinstance(data, HPGuiDataSell)}"
                        )
                        # Add side information to the update
                        data.hp_update.side = data.data.state_info.side.value
                        # Add sell completeness information for collapse logic
                        data.hp_update.sell_completeness = (
                            data.data.state_info.completeness
                        )
                        logger.info(
                            f"[DEBUG SELL STATE] Before assignment - data.data.state_info={data.data.state_info}"
                        )
                        logger.info(
                            f"[DEBUG SELL STATE] data.data.state_info.state={data.data.state_info.state}"
                        )
                        logger.info(
                            f"[DEBUG SELL STATE] data.data.state_info.state.value={data.data.state_info.state.value}"
                        )
                        data.hp_update.sell_state = data.data.state_info.state.value
                        logger.info(
                            f"[DEBUG SELL STATE] After assignment - data.hp_update.sell_state={data.hp_update.sell_state}"
                        )
                        logger.info(
                            f"Assigned sell_completeness={data.hp_update.sell_completeness}, sell_state={data.hp_update.sell_state}"
                        )
                        logger.info(
                            f"Original data completeness: {data.data.state_info.completeness}"
                        )
                        self.hp_list_data = self.update_hp_list(
                            update=data.hp_update, hp_list=self.hp_list_data
                        )
                    elif isinstance(data, Event) and data.name == EventName.ALL_TICKERS:
                        assert isinstance(data.content, AllTickers)
                        self._process_all_tickers(data.content)
                    else:
                        # Debug: Check what data type we received that doesn't match any expected type
                        logger.info(
                            f"[UNMATCHED DATA TYPE] Received data of type: {type(data)}"
                        )
                        if hasattr(data, "__class__"):
                            logger.info(
                                f"[UNMATCHED DATA TYPE] Class name: {data.__class__.__name__}"
                            )
                            logger.info(
                                f"[UNMATCHED DATA TYPE] Module: {data.__class__.__module__}"
                            )
                        if hasattr(data, "hp_update") and hasattr(data, "data"):
                            logger.info(
                                f"[UNMATCHED DATA TYPE] Looks like HPGuiDataSell but isinstance failed"
                            )
                            logger.info(
                                f"[UNMATCHED DATA TYPE] HPGuiDataSell class: {HPGuiDataSell}"
                            )
                            logger.info(
                                f"[UNMATCHED DATA TYPE] HPGuiDataSell module: {HPGuiDataSell.__module__}"
                            )
                            logger.info(
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
                                logger.info(
                                    f"[FORCED SELL STATE] Assigned sell_state={data.hp_update.sell_state}"
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
        - Buy HP: Parent container + Buy child (both with Sell action)
        - Sell HP: Parent container + Dummy Buy child + Sell child

        Multihop (1000a, 1000b) only handled for existing exchange positions.
        """
        hp_id = update.hp_id
        is_multihop_child = hp_id[
            -1
        ].isalpha()  # True if ends with 'a', 'b', etc. (existing multihop)
        base_hp_id = hp_id[:-1] if is_multihop_child else hp_id

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

        logger.info(
            f"Processing HP update: {hp_id}, side: {operation_side}, state: {update.state.value}"
        )

        if is_multihop_child:
            # Handle existing multihop children (1000a, 1000b) - no new multihop created
            self._handle_existing_multihop_child(
                hp_map, update, hp_id, base_hp_id, operation_side
            )
        else:
            # Handle new runtime positions - always create container structure
            self._handle_container_position(
                hp_map, update, hp_id, operation_side, quantity_usd
            )

        # Check if we need to collapse children for completed positions
        self._collapse_completed_positions(hp_map, update)

        self.hp_list = list(hp_map.values())

        # Check if the HP position moved to CLOSED or SOLD state and auto-remove from filter if needed
        if update.state.value in ["CLOSED", "SOLD"]:
            self.auto_remove_closed_sold_states()

        # Trigger visual refresh
        self._update_hp_list_view()

        return self.hp_list

    def _handle_existing_multihop_child(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        parent_id: str,
        operation_side: str,
    ) -> None:
        """Handle existing multihop children (1000a, 1000b) - legacy positions only."""
        quantity_usd = (
            update.symbol_info.format_price(update.quantity_usd)
            if update.quantity_usd is not None
            else "0.0"
        )

        # Create child record
        child_record = {
            "hp_id": hp_id,
            "coin": update.symbol_info.symbol,
            "buy_price": (
                str(update.symbol_info.format_price(update.buy_price))
                if update.buy_price
                else "0.0"
            ),
            "quantity": (
                str(update.symbol_info.format_quantity(update.quantity))
                if update.quantity
                else "0.0"
            ),
            "quantity_usd": quantity_usd,
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
            "net_percent": str(update.net_percent) if update.net_percent else "0.0",
            "state": update.state.value,
            "is_child": True,
            "side": operation_side,
            "parent_hp_id": parent_id,
        }

        hp_map[hp_id] = child_record

        # Ensure parent container exists for legacy multihop
        if parent_id not in hp_map:
            hp_map[parent_id] = {
                "hp_id": parent_id,
                "coin": f"{update.coin}USD",
                "state": "CHILD_ACTIVE",
                "buy_price": "0.0",
                "quantity": "0.0",
                "quantity_usd": "0.0",
                "sell_price": "0.0",
                "expected_return": "0.0",
                "current_price": "0.0",
                "net": "0.0",
                "net_percent": "0.0",
                "is_child": False,
                "side": "PARENT",
                "children": [hp_id],
                "is_expanded": True,
            }
        else:
            parent = hp_map[parent_id]
            parent.setdefault("children", [])
            if hp_id not in parent["children"]:
                parent["children"].append(hp_id)

    def _handle_container_position(
        self,
        hp_map: Dict[str, Dict],
        update: HPUpdate,
        hp_id: str,
        operation_side: str,
        quantity_usd: str,
    ) -> None:
        """Handle new runtime positions with container structure. No multihop creation."""

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

        logger.info(
            f"Container position {hp_id}: is_buy={is_buy_operation}, is_sell={is_sell_operation}"
        )

        # Always ensure parent container exists
        if hp_id not in hp_map or hp_map[hp_id].get("is_child", True):
            # Create parent container
            hp_map[hp_id] = {
                "hp_id": hp_id,
                "coin": f"{update.coin}USD",
                "state": update.state.value,
                "buy_price": "0.0",
                "quantity": "0.0",
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
                "action_buttons": ["SELL", "CANCEL"],  # Parent can sell and cancel
            }

        parent = hp_map[hp_id]
        parent.setdefault("children", [])

        if is_buy_operation:
            # Buy HP: Create buy child only (no multihop)
            buy_child_key = f"{hp_id}_BUY"
            buy_child = {
                "hp_id": buy_child_key,
                "coin": update.symbol_info.symbol,
                "buy_price": (
                    str(update.symbol_info.format_price(update.buy_price))
                    if update.buy_price
                    else "0.0"
                ),
                "quantity": (
                    str(update.symbol_info.format_quantity(update.quantity))
                    if update.quantity
                    else "0.0"
                ),
                "quantity_usd": quantity_usd,
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
                "parent_hp_id": hp_id,
                "action_buttons": ["SELL", "CANCEL"],  # Buy child can sell and cancel
            }

            hp_map[buy_child_key] = buy_child
            if buy_child_key not in parent["children"]:
                parent["children"].append(buy_child_key)

            # Update parent with buy data
            parent["quantity"] = buy_child["quantity"]
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
                    logger.info(
                        f"[SELL CHILD UPDATE] Updated existing sell child state to: {existing_sell_child['state']} for parent state: {update.state.value}"
                    )

        elif is_sell_operation:
            # Sell HP: Create sell child, keeping existing buy child if present

            # Check if there's already a real buy child
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

                # Update buy child quantities if needed
                if update.quantity:
                    # For selling operations, the quantity might be different (e.g., partially sold)
                    # Update buy child to reflect total original buy quantity, not remaining quantity
                    pass  # Keep existing quantity for now

            # Create dummy buy child only if no real buy child exists
            dummy_buy_key = f"{hp_id}_DUMMY_BUY"
            if not has_real_buy_child and dummy_buy_key not in hp_map:
                # Get average buy price from portfolio (placeholder for now)
                avg_buy_price = "0.0"  # TODO: Get from portfolio
                dummy_buy_quantity = (
                    str(update.symbol_info.format_quantity(update.quantity))
                    if update.quantity
                    else "0.0"
                )

                dummy_buy_child = {
                    "hp_id": dummy_buy_key,
                    "coin": update.symbol_info.symbol,
                    "buy_price": avg_buy_price,
                    "quantity": dummy_buy_quantity,
                    "quantity_usd": "0.0",  # Calculate based on avg price
                    "current_price": (
                        str(update.symbol_info.format_price(update.current_price))
                        if update.current_price
                        else "0.0"
                    ),
                    "net": "0.0",
                    "net_percent": "0.0",
                    "state": "DUMMY",
                    "is_child": True,
                    "side": "DUMMY_BUY",
                    "parent_hp_id": hp_id,
                    "action_buttons": [],  # Dummy has no actions
                }

                hp_map[dummy_buy_key] = dummy_buy_child
                if dummy_buy_key not in parent["children"]:
                    parent["children"].append(dummy_buy_key)

            # Create single sell child (no multihop for new positions)
            sell_child_key = f"{hp_id}_SELL"

            sell_child = {
                "hp_id": sell_child_key,
                "coin": update.symbol_info.symbol,
                "buy_price": (
                    str(update.symbol_info.format_price(update.buy_price))
                    if update.buy_price
                    else "0.0"
                ),
                "quantity": (
                    str(update.symbol_info.format_quantity(update.quantity))
                    if update.quantity
                    else "0.0"
                ),
                "quantity_usd": quantity_usd,
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
                "net_percent": str(update.net_percent) if update.net_percent else "0.0",
                "state": self._get_sell_child_state_from_update(update),
                "is_child": True,
                "side": "SELL",
                "parent_hp_id": hp_id,
                "action_buttons": ["CANCEL"],  # Sell child can cancel
            }

            hp_map[sell_child_key] = sell_child
            if sell_child_key not in parent["children"]:
                parent["children"].append(sell_child_key)

            # Update parent with sell data
            parent["sell_price"] = sell_child["sell_price"]
            parent["expected_return"] = sell_child["expected_return"]
            parent["action_buttons"] = ["CANCEL"]  # Parent with sell can cancel

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
        # Trigger visual refresh
        self._update_hp_list_view()

    def trigger_sell_position(self, *args) -> None:
        # This method is deprecated - HP creation now handled by unified HP manager
        logger.warning(
            "trigger_sell_position called but deprecated - use unified HP manager"
        )
        return

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

        self.filter_records("active", "All", side="BUY")
        self.filter_records("idle", "All", side="BUY")
        self.filter_records("archive", "All", side="BUY")
        self.filter_records("active", "All", side="SELL")
        self.filter_records("idle", "All", side="SELL")
        self.filter_records("archive", "All", side="SELL")

    def fetch_hp_info(self, hp_id):
        """
        Fetches and populates the HP information into the Sell tab based on the provided hp_id.
        If hp_id is not found, resets all fields to '---'.

        Args:
        - hp_id: The HP ID entered by the user.
        """
        try:
            for item in self.hp_list_data:
                if int(item["hp_id"]) == int(hp_id):
                    # Populate the fields in the Sell tab
                    self.ids.hp_id_input.text = str(hp_id)
                    self.ids.coin_input.text = (
                        item["coin"][:-3]
                        if item["coin"].endswith("USD")
                        else item["coin"]
                    )
                    self.ids.quantity_input.text = item["quantity"]
                    self.ids.buy_price_input.text = item["buy_price"]

                    # self.ids.quantity_usd_label.text = str(
                    #     round(float(item["quantity"]) * float(item["buy_price"]), 2)
                    # )

                    # Clear or reset the sell price field
                    self.ids.sell_price_input.text = ""  # Clear any previous sell price

                    # Optional: Set focus on the sell price input field
                    self.ids.sell_price_input.focus = True

                    return

            # If hp_id is not found in hp_list_data, raise ValueError to reset fields
            raise ValueError("HP ID not found")

        except ValueError:
            # Reset all fields to '---' if HP ID is not found or any error occurs
            logger.error(f"HP ID {hp_id} not found in hp_list_data, resetting fields.")
            self.ids.coin_input.text = "---"
            self.ids.quantity_input.text = "---"
            self.ids.buy_price_input.text = "---"
            self.ids.sell_price_input.text = ""

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

    def _validate_buy_inputs(self) -> bool:
        symbol = self.symbol_input.selected_value
        price_low = self.symbol_input.price_low_input.text
        price_high = self.symbol_input.price_high_input.text
        budget = self.ids.budget_input.text
        order_trigger = self.ids.order_trigger_input.text
        mode = self.ids.mode_input.text

        validation_message = ""
        if not symbol:
            validation_message += "Symbol is required. "
        if not price_low or not price_high:
            validation_message += "Price range is required. "
        if not budget:
            validation_message += "Budget is required. "
        if not order_trigger:
            validation_message += "Order trigger is required. "
        if mode not in [Mode.DCA.value, Mode.SINGLE.value]:
            validation_message += "Mode has to be selected."
        if price_low > price_high:
            validation_message += "Price low is bigger than price high. "

        self.ids.buy_validation_label.text = validation_message

        return not validation_message

    def _validate_sell_inputs(self) -> bool:
        coin = self.ids.coin_input.text
        buy_price = self.ids.buy_price_input.text
        sell_price = self.ids.sell_price_input.text
        quantity = self.ids.quantity_input.text
        # total_usd = self.ids.total_usd_value_label.text

        validation_message = ""
        if not coin:
            validation_message += "Coin is required. "
        if not buy_price:
            validation_message += "Buy price is required. "
        if not sell_price:
            validation_message += "Sell price is required. "
        if not quantity:
            validation_message += "Quantity is required. "
        # if not total_usd:
        #     validation_message += "Total USD price is required. "

        self.ids.sell_validation_label.text = validation_message

        return not validation_message

    def on_sell_tab_open(self):
        """Ensure the correct UI is displayed immediately when Sell tab is opened."""
        self.ids.dynamic_sell_container.clear_widgets()

        # Ensure "New HP" is default when opening the tab
        self.ids.hp_mode_new.state = "down"
        self.ids.hp_mode_existing.state = "normal"

        self._create_new_hp_ui()  # Load the default "New HP" UI

        # Force UI refresh
        self.ids.dynamic_sell_container.do_layout()

    def on_tab_switch(self, tab_name):
        """Ensures the Sell tab always loads the correct UI layout when opened."""
        if tab_name == "Sell":
            self.on_sell_tab_open()

    def _on_hp_id_text_change(self, instance, value):
        """Triggers fetch_hp_info when the HP ID input changes."""
        if value.strip():  # Only fetch when there's actual input
            self.fetch_hp_info(value)

    def update_hp_mode(self, state):
        """Dynamically update UI based on HP mode selection."""
        self.ids.dynamic_sell_container.clear_widgets()

        if state == "existing":
            logger.info("Changing to exitign HP GUI")
            self._create_existing_hp_ui()
            # Bind fetch_hp_info to hp_id_input.text
            self.ids.hp_id_input.bind(text=self._on_hp_id_text_change)
        else:
            logger.info("Changing to new HP GUI")
            self._create_new_hp_ui()
            # Unbind fetch_hp_info to prevent unnecessary calls
            self.ids.hp_id_input.unbind(text=self._on_hp_id_text_change)

    def _create_existing_hp_ui(self):
        """Creates UI for existing HP mode"""
        self.ids.dynamic_sell_container.clear_widgets()

        # Main container with padding
        main_layout = BoxLayout(
            orientation="vertical",
            spacing=10,  # Ensure spacing within the main layout
            size_hint_y=1,
            padding=[40, 20, 40, 0],  # Padding on sides for elegant spacing
        )

        # **Row 1: HP ID, coin, Quantity**
        row1 = BoxLayout(
            orientation="horizontal",
            spacing=25,
            size_hint_y=0.3,
            height="50dp",
            padding=[10, 0, 10, 0],
        )
        row1.add_widget(
            self._create_labeled_input_with_hint("HP ID:", "hp_id_input", "")
        )
        row1.add_widget(
            self._create_labeled_input_with_hint("coin:", "coin_input", "BTC")
        )
        row1.add_widget(
            self._create_labeled_input_with_hint("Quantity:", "quantity_input", "0.0")
        )

        # **Row 2: Buy Price, Sell Price, End Currency**
        row2 = BoxLayout(
            orientation="horizontal",
            spacing=25,
            size_hint_y=0.3,
            height="50dp",
            padding=[10, 0, 10, 0],
        )
        row2.add_widget(
            self._create_labeled_input_with_hint("Buy Price:", "buy_price_input", "0.0")
        )
        row2.add_widget(
            self._create_labeled_input_with_hint(
                "Sell Price:", "sell_price_input", "0.0"
            )
        )
        row2.add_widget(
            self._create_spinner(
                "End Currency:", "end_currency_spinner", ["USDC", "PLN"]
            )
        )

        # **Lower spacer to push content upward slightly**
        lower_spacer = Widget(size_hint_y=0.4)

        # Add everything to the dynamic container
        # main_layout.add_widget(spacer_row)  # Adds spacing above inputs
        main_layout.add_widget(row1)
        main_layout.add_widget(row2)
        main_layout.add_widget(lower_spacer)  # Ensures inputs don’t stick to bottom

        self.ids.dynamic_sell_container.add_widget(main_layout)
        self.ids.dynamic_sell_container.do_layout()

    def _create_new_hp_ui(self):
        """Creates UI for New HP mode with proper spacing using a dedicated spacer."""
        self.ids.dynamic_sell_container.clear_widgets()

        # Main container with padding
        main_layout = BoxLayout(
            orientation="vertical",
            spacing=10,  # Ensure spacing within the main layout
            size_hint_y=1,
            padding=[40, 20, 40, 0],  # Padding on sides for elegant spacing
        )

        # **Row 1: HP ID, coin, Quantity**
        row1 = BoxLayout(
            orientation="horizontal",
            spacing=25,
            size_hint_y=0.3,
            height="50dp",
            padding=[10, 0, 10, 0],
        )
        row1.add_widget(
            self._create_labeled_input_with_hint(
                "HP ID:", "hp_id_input", "", editable=False
            )
        )
        row1.add_widget(
            self._create_labeled_input_with_hint("coin:", "coin_input", "", "AXL")
        )
        row1.add_widget(
            self._create_labeled_input_with_hint(
                "Quantity:", "quantity_input", "", "10.0"
            )
        )

        # **Row 2: Buy Price, Sell Price, End Currency**
        row2 = BoxLayout(
            orientation="horizontal",
            spacing=25,
            size_hint_y=0.3,
            height="50dp",
            padding=[10, 0, 10, 0],
        )
        row2.add_widget(
            self._create_labeled_input_with_hint(
                "Buy Price:", "buy_price_input", "", "0.28"
            )
        )
        row2.add_widget(
            self._create_labeled_input_with_hint(
                "Sell Price:", "sell_price_input", "", "1.14"
            )
        )
        row2.add_widget(
            self._create_spinner(
                "End Currency:", "end_currency_spinner", ["USDC", "PLN"]
            )
        )

        # **Lower spacer to push content upward slightly**
        lower_spacer = Widget(size_hint_y=0.4)

        # Add everything to the dynamic container
        # main_layout.add_widget(spacer_row)  # Adds spacing above inputs
        main_layout.add_widget(row1)
        main_layout.add_widget(row2)
        main_layout.add_widget(lower_spacer)  # Ensures inputs don’t stick to bottom

        self.ids.dynamic_sell_container.add_widget(main_layout)
        self.ids.dynamic_sell_container.do_layout()

    def _create_labeled_input_with_hint(
        self, label_text, input_name, hint_text, default_text="", editable=True
    ):
        """Creates a label with a TextInput that stays aligned towards the top."""
        box = BoxLayout(orientation="vertical", spacing=4, size_hint_x=0.33)

        label = Label(text=label_text, size_hint_y=0.4, halign="left", valign="middle")
        label.bind(size=label.setter("text_size"))

        input_widget = TextInput(
            text=default_text,
            size_hint_y=0.6,
            multiline=False,
            hint_text=hint_text,
            foreground_color=(0, 0, 0, 1),
            hint_text_color=(0.6, 0.6, 0.6, 1),
            padding=[8, 5, 8, 5],
            disabled=not editable,
        )

        self.ids[input_name] = input_widget
        box.add_widget(label)
        box.add_widget(input_widget)

        return box

    def _create_spinner(self, label_text, spinner_name, options):
        """Creates a label and a dropdown spinner for selection, aligned to the top."""
        box = BoxLayout(orientation="vertical", spacing=4, size_hint_x=0.33)

        label = Label(text=label_text, size_hint_y=0.4, halign="left", valign="middle")
        label.bind(size=label.setter("text_size"))

        spinner = Spinner(
            text=options[0],
            values=options,
            size_hint_y=0.6,
        )

        self.ids[spinner_name] = spinner
        box.add_widget(label)
        box.add_widget(spinner)

        return box

    def toggle_hp_expansion(self, hp_id: str):
        """Toggle the expansion state of a parent HP position"""
        if hp_id in self.expanded_hp_ids:
            self.expanded_hp_ids.remove(hp_id)
        else:
            self.expanded_hp_ids.add(hp_id)
        # Trigger UI update
        self._update_hp_list_view()

    def _get_sorted_hp_list(self):
        # Apply state filtering first
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
            if hp.get("is_child", False) and hp.get("hp_id", "")[-1:].isalpha()
        ]
        regular_children = [
            hp
            for hp in filtered_data
            if hp.get("is_child", False) and not hp.get("hp_id", "")[-1:].isalpha()
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
                if c.get("parent_hp_id") == parent_id or c.get("hp_id") == parent_id
            ]

            all_children = parent_multihop_children + parent_regular_children

            # Add has_children property to parent for UI rendering
            parent["has_children"] = len(all_children) > 0
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
        # Updated for unified HP manager - no longer uses hp_list_view widget
        logger.info(
            f"_update_hp_list_view called with hp_list_data length: {len(self.hp_list_data)}"
        )

        # Prevent infinite sync loops
        if getattr(self, "_syncing_unified_data", False):
            logger.debug("Already syncing unified data, skipping to prevent loop")
            return

        if hasattr(self, "unified_hp_manager") and self.unified_hp_manager:
            logger.info("Syncing unified HP data...")
            self._sync_unified_hp_data()
        else:
            # Still initializing, skip update
            logger.warning("Unified HP manager not available, skipping sync")
            return

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

    def _collapse_completed_positions(
        self, hp_map: Dict[str, Dict], update: HPUpdate
    ) -> None:
        """Collapse parent containers when positions are fully completed (SOLD, CLOSED).

        In the new container-based approach:
        - Only parent containers collapse when reaching final states
        - Children are updated to show their latest state, not removed
        """
        logger.info(
            f"[COLLAPSE] Processing update for {update.hp_id}: state={update.state.value}, sell_completeness={getattr(update, 'sell_completeness', 'None')}"
        )

        # Only collapse parent containers, not children
        hp_id = update.hp_id
        is_child = "_" in hp_id and not hp_id.endswith("_PARENT")

        if is_child:
            # Children are just updated, not collapsed
            logger.info(f"[COLLAPSE] Skipping child {hp_id}")
            return

        # Check if parent should be collapsed (final completion states)
        # For selling positions, only collapse when sell operation has made progress
        is_selling_completed = (
            update.state.value == "SELLING"
            and update.expected_return is not None
            and update.expected_return > 0
            and update.sell_completeness is not None
            and update.sell_completeness > 0.0  # Only collapse when selling has started
        )
        is_parent_completed = (
            update.state.value in ["SOLD", "CLOSED", "SOLD_PART_BOUGHT"]
            or is_selling_completed
        )

        logger.info(
            f"[COLLAPSE] Sell completion check: selling={update.state.value == 'SELLING'}, expected_return={update.expected_return}, sell_completeness={getattr(update, 'sell_completeness', 'None')}"
        )
        logger.info(
            f"[COLLAPSE] is_selling_completed={is_selling_completed}, is_parent_completed={is_parent_completed}"
        )

        if not is_parent_completed:
            logger.info(f"[COLLAPSE] Not collapsing {hp_id} - not completed")
            return

        # Find parent container
        parent_key = hp_id
        if parent_key not in hp_map:
            logger.info(f"[COLLAPSE] Parent {parent_key} not found in hp_map")
            return

        parent = hp_map[parent_key]

        logger.info(f"[COLLAPSE] Collapsing parent {parent_key}")

        # Remove all children and collapse to just parent
        children_to_remove = []
        for child_key in list(hp_map.keys()):
            if child_key.startswith(f"{hp_id}_"):
                children_to_remove.append(child_key)

        # Update parent with final completed state data
        parent.update(
            {
                "buy_price": (
                    str(update.symbol_info.format_price(update.buy_price))
                    if update.buy_price
                    else parent.get("buy_price", "0.0")
                ),
                "quantity": (
                    str(update.symbol_info.format_quantity(update.quantity))
                    if update.quantity is not None
                    else "0.0"
                ),
                "quantity_usd": (
                    str(update.symbol_info.format_price(update.quantity_usd))
                    if update.quantity_usd is not None
                    else "0.0"
                ),
                "sell_price": (
                    str(update.symbol_info.format_price(update.sell_price))
                    if update.sell_price
                    else parent.get("sell_price", "0.0")
                ),
                "expected_return": (
                    str(update.symbol_info.format_price(update.expected_return))
                    if update.expected_return
                    else parent.get("expected_return", "0.0")
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
                "net_percent": str(update.net_percent) if update.net_percent else "0.0",
                "state": update.state.value,
                "children": [],  # Remove all children - collapsed to parent only
                "action_buttons": [],  # No actions for completed positions
            }
        )

        # Remove children from hp_map
        for child_key in children_to_remove:
            hp_map.pop(child_key, None)

        logger.info(
            f"Collapsed completed parent {parent_key} - removed {len(children_to_remove)} children"
        )
