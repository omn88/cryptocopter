import asyncio
import csv
import os
import queue
import logging
from typing import Dict, List, Set, Optional
import uuid
from kivy.properties import (
    ListProperty,
    ObjectProperty,
)

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
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
from src.portfolio.usd_price_resolver import UsdPriceResolver
from src.gui.hp_manager import HPManager, HPConfiguration


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
                "action_buttons": ["SELL", "CANCEL"],  # Parent can sell and cancel
            }

        parent = hp_map[hp_id]
        parent.setdefault("children", [])

        if is_buy_operation:
            # Buy HP: Create buy child only (no multihop)
            buy_child_key = f"{hp_id}_BUY"

            # Buy children according to new specification:
            # - quantity: Total trade quantity (use total_quantity if available)
            # - realized_quantity: Actually realized quantity (use total_quantity if available)

            # Get total quantity for buy child display
            total_bought_qty = getattr(update, "total_quantity", None)
            if total_bought_qty is None:
                # Fallback to current quantity for buy child display
                total_bought_qty = update.quantity or 0.0

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
                "parent_hp_id": hp_id,
                "action_buttons": ["SELL", "CANCEL"],  # Buy child can sell and cancel
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
            logger.info(
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
                logger.info(
                    f"[PARENT BUY] Set parent total bought quantity: {parent['quantity']}"
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
                    total_bought_qty = getattr(update, "total_quantity", None)
                    logger.info(
                        f"[BUY CHILD DEBUG] update.quantity={update.quantity}, total_quantity={total_bought_qty}"
                    )
                    if total_bought_qty is None:
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

            # Sell children according to new specification:
            # - quantity: Total buy quantity (the amount that should be sold - same as total bought)
            # - realized_quantity: Actually sold quantity (how much was actually sold)

            # Get total bought quantity from parent
            total_bought_qty = float(parent.get("quantity", "0.0"))
            actually_sold_qty = float(parent.get("realized_quantity", "0.0"))

            # For sell child, calculate quantity_usd same as buy child (total bought value)
            # This represents the total value of money invested in the position
            total_bought_qty = float(parent.get("quantity", "0.0"))
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
                "quantity": (str(update.symbol_info.format_quantity(total_bought_qty))),
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

            # Update parent quantity using same logic as buy operation
            # This ensures parent quantity shows remaining vs total based on state
            operation_side = getattr(update, "side", "BUY")
            short_condition = operation_side == "SHORT"
            sell_condition = "SELL" in update.state.value
            combined_condition = short_condition or sell_condition

            logger.info(
                f"[PARENT SELL CONDITION] operation_side={operation_side}, state={update.state.value}, short_condition={short_condition}, sell_condition={sell_condition}"
            )
            logger.info(
                f"[PARENT SELL CONDITION DEBUG] state type: {type(update.state)}, state value type: {type(update.state.value)}"
            )
            logger.info(
                f"[PARENT SELL CONDITION DEBUG] repr(state.value): {repr(update.state.value)}"
            )
            logger.info(
                f"[PARENT SELL CONDITION DEBUG] 'SELL' in repr: {'SELL' in update.state.value}"
            )
            logger.info(
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
                logger.info(
                    f"[PARENT SELL] Total bought: {parent['quantity']}, Sold: {parent['realized_quantity']} (remaining: {remaining_qty})"
                )

            else:
                # For sell operations without SELL in state, show total bought
                parent["quantity"] = str(
                    update.symbol_info.format_quantity(total_bought_qty)
                )
                logger.info(
                    f"[PARENT SELL BUY] Set parent total bought quantity: {parent['quantity']}"
                )

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
        """Update the HP list view with current data."""
        logger.info(
            f"_update_hp_list_view called with hp_list_data length: {len(self.hp_list_data)}"
        )

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
        row.add_widget(self._create_column_label(hp_data.get("buy_price", "0.0"), 0.12))

        # Progress column (show completeness or state info)
        progress_text = (
            f"{float(hp_data.get('realized_quantity', 0)):.3f}"
            if hp_data.get("realized_quantity")
            else "0.000"
        )
        row.add_widget(self._create_column_label(progress_text, 0.1))

        row.add_widget(self._create_column_label(hp_data.get("net", "0.0"), 0.12))
        row.add_widget(self._create_column_label(hp_data.get("state", ""), 0.1))

        # Action buttons
        action_layout = BoxLayout(orientation="horizontal", size_hint_x=0.18, spacing=2)
        action_buttons = hp_data.get("action_buttons", [])

        if "SELL" in action_buttons:
            sell_btn = Button(text="Sell", size_hint_x=0.5)
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
            hp_id = hp_data.get("hp_id", "")
            symbol = hp_data.get("coin", "")
            side_value = "LONG" if hp_data.get("side") == "BUY" else "SHORT"
            cancel_btn.bind(
                on_release=lambda x: self.trigger_remove_record(
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
            update.state.value in ["SOLD", "CLOSED"] or is_selling_completed
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
