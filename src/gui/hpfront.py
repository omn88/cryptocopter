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
    ActivePositionBuy,
    ActivePositionSell,
    ArchivedPositionBuy,
    ArchivedPositionSell,
    HPGuiDataBuy,
    HPGuiDataSell,
    HPUpdate,
    IdlePositionBuy,
    IdlePositionSell,
)
from src.gui.searchable_drop_down import SearchableDropDown
from src.portfolio.usd_price_resolver import UsdPriceResolver


logger = logging.getLogger("HPFront")


class HpFront(BoxLayout):
    hp_list_data: List[Dict] = ListProperty([])
    expanded_hp_ids: Set[str] = set()  # Track which parent HPs are expanded
    active_records_buy: List[Dict] = ListProperty([])
    idle_records_buy: List[Dict] = ListProperty([])
    archived_records_buy: List[Dict] = ListProperty([])
    active_records_sell: List[Dict] = ListProperty([])
    idle_records_sell: List[Dict] = ListProperty([])
    archived_records_sell: List[Dict] = ListProperty([])
    filtered_active_records_buy: List[Dict] = ListProperty([])
    filtered_idle_records_buy: List[Dict] = ListProperty([])
    filtered_archived_records_buy: List[Dict] = ListProperty([])
    filtered_active_records_sell: List[Dict] = ListProperty([])
    filtered_idle_records_sell: List[Dict] = ListProperty([])
    filtered_archived_records_sell: List[Dict] = ListProperty([])
    active_filter_buy = StringProperty("All")
    idle_filter_buy = StringProperty("All")
    archive_filter_buy = StringProperty("All")
    active_filter_sell = StringProperty("All")
    idle_filter_sell = StringProperty("All")
    archive_filter_sell = StringProperty("All")

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
        self.bind(active_records_buy=self._update_active_symbols_buy)
        self.bind(idle_records_buy=self._update_idle_symbols_buy)
        self.bind(archived_records_buy=self._update_archive_symbols_buy)
        self.bind(active_records_sell=self._update_active_symbols_sell)
        self.bind(idle_records_sell=self._update_idle_symbols_sell)
        self.bind(archived_records_sell=self._update_archive_symbols_sell)
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

        # Suppress GUI initialization when in test mode
        if not self.test_mode:
            self.symbol_input = SearchableDropDown(
                client=self.client, options=self.symbols, symbols_info=self.symbols_info
            )
            # Add it to the layout where needed
            self.ids.symbol_container.add_widget(self.symbol_input)

    def initialize(self):
        if not self.test_mode:
            self.refresh_task = asyncio.create_task(self._refresh_ui())
        self.queue_task = asyncio.create_task(self.process_ui_queue())

    def trigger_add_record(self, *args) -> None:
        if not self._validate_buy_inputs():
            return

        symbol = self.symbol_input.selected_value
        new_hp = HPBuyData(
            config=HPBuyConfig(
                coin=self.symbols_info[symbol].extract_coin_from_symbol(symbol=symbol),
                symbol_info=self.symbols_info[symbol],
                price_low=float(self.symbol_input.price_low_input.text),
                price_high=float(self.symbol_input.price_high_input.text),
                budget=float(self.ids.budget_input.text),
                order_trigger=float(self.ids.order_trigger_input.text),
                mode=(
                    Mode.DCA
                    if self.ids.mode_input.text == Mode.DCA.value
                    else Mode.SINGLE
                ),
            ),
            state_info=StateInfo(),
        )
        self.config_queue.put_nowait(new_hp)
        logger.info("New HP added to the queue: %s", new_hp)

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

    async def process_ui_queue(self) -> None:
        logger.info("Ready to process UI queue")
        while not self.stop_event.is_set():
            try:
                while True:
                    data = self.ui_queue.get_nowait()
                    if isinstance(data, HPGuiDataBuy):
                        await self._process_buy_position_data(data)
                    if isinstance(data, HPGuiDataSell):
                        await self._process_sell_position_data(data)
                    elif isinstance(data, Event) and data.name == EventName.ALL_TICKERS:
                        assert isinstance(data.content, AllTickers)
                        self._process_all_tickers(data.content)
            except queue.Empty:
                await asyncio.sleep(0.1)
        self.ui_queue_closed = True

    async def _process_buy_position_data(self, data: HPGuiDataBuy) -> None:
        logger.info("UI received BUY position data: %s", data)
        # Update the HP list and DB
        self.hp_list_data = self.update_hp_list(
            update=data.hp_update, hp_list=self.hp_list_data
        )

        hp_id = str(data.data.config.hp_id)

        # Try to update the record in one of the lists
        if self._record_exists(self.active_records_buy, hp_id):
            logger.info("Record %s found in active records", hp_id)
            self.update_active_position_buy(data=data.data)
        elif self._record_exists(self.idle_records_buy, hp_id):
            logger.info("Record %s found in idle records", hp_id)
            self.update_idle_position_buy(data=data.data)
        elif self._archived_record_exists_buy(data.data):
            logger.info("Record %s already found in archived records", hp_id)
        else:
            self._add_new_record_buy(data.data)

        self._log_all_records_buy()

    async def _process_sell_position_data(self, data: HPGuiDataSell) -> None:
        logger.info("UI received SELL position data: %s", data)

        # Update the HP list and DB
        self.hp_list_data = self.update_hp_list(
            update=data.hp_update, hp_list=self.hp_list_data
        )

        logger.info("HP List updated with update: %s", data.hp_update)

        hp_id = str(data.data.config.hp_id)
        symbol_info = data.data.config.symbol_info

        if symbol_info.symbol.endswith("USDT") and not symbol_info.is_convert_only:
            logger.info(
                "No position add, hp_id: %s, symbol: %s, convert only: %s",
                data.data.config.hp_id,
                symbol_info.symbol,
                symbol_info.is_convert_only,
            )
            return  # Don't show this in idle/active/archive for other than for convert

        # Try to update the record in one of the lists
        if self._record_exists(self.active_records_sell, hp_id):
            logger.info("Record %s found in active records", hp_id)
            self.update_active_position_sell(data=data.data)
        elif self._record_exists(self.idle_records_sell, hp_id):
            logger.info("Record %s found in idle records", hp_id)
            self.update_idle_position_sell(data=data.data)
        elif self._archived_record_exists_sell(data.data):
            logger.info("Record %s already found in archived records", hp_id)
        else:
            self._add_new_record_sell(data.data)

        self._log_all_records_sell()

    def update_hp_list(self, update: HPUpdate, hp_list: List[Dict]) -> List[Dict]:
        hp_id = update.hp_id
        is_child = hp_id[-1].isalpha()  # True if ends with 'a', 'b', etc.
        is_parent = not is_child
        parent_id = hp_id[:-1] if is_child else hp_id

        hp_map: Dict[str, Dict] = {}
        new_record: Dict = {}

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

        # Prepare record
        new_record = {
            "hp_id": hp_id,
            "coin": f"{update.coin}USD" if is_parent else update.symbol_info.symbol,
            "buy_price": (
                str(update.symbol_info.format_price(update.buy_price))
                if update.buy_price is not None
                else "0.0"
            ),
            "quantity": (
                str(update.symbol_info.format_quantity(update.quantity))
                if update.quantity is not None
                else "0.0"
            ),
            "quantity_usd": quantity_usd,
            "sell_price": (
                str(update.symbol_info.format_price(update.sell_price))
                if update.sell_price is not None
                else "0.0"
            ),
            "expected_return": (
                str(update.symbol_info.format_price(update.expected_return))
                if update.expected_return is not None
                else "0.0"
            ),
            "current_price": (
                str(update.symbol_info.format_price(update.current_price))
                if update.current_price is not None
                else "0.0"
            ),
            "net": (
                str(update.symbol_info.format_price(update.net))
                if update.net is not None
                else "0.0"
            ),
            "net_percent": (
                str(update.net_percent) if update.net_percent is not None else "0.0"
            ),
            "state": update.state.value,
            "is_child": is_child,
        }

        # logger.info("NEw record w HP FRONT: %s", new_record)

        if is_child:
            new_record["parent_hp_id"] = parent_id
            # Add or update child
            hp_map[hp_id] = new_record

            # Make sure parent exists
            if parent_id not in hp_map:
                hp_map[parent_id] = {
                    "hp_id": parent_id,
                    "coin": update.coin,
                    "state": "CHILD_ACTIVE",  # Default state until updated
                    "buy_price": "0.0",
                    "quantity": "0.0",
                    "quantity_usd": "0.0",
                    "sell_price": "0.0",
                    "expected_return": "0.0",
                    "current_price": "0.0",
                    "net": "0.0",
                    "net_percent": "0.0",
                    "is_child": False,
                    "children": [hp_id],
                }
            else:
                # Add to children if not there
                parent = hp_map[parent_id]
                parent.setdefault("children", [])
                if hp_id not in parent["children"]:
                    parent["children"].append(hp_id)

        else:  # Add or update parent
            if hp_id in hp_map:
                hp_map[hp_id].update(new_record)
            else:
                new_record["children"] = []
                hp_map[hp_id] = new_record

        self.hp_list = list(hp_map.values())  # this is likely already present

        # Check if the HP position moved to CLOSED or SOLD state and auto-remove from filter if needed
        if update.state.value in ["CLOSED", "SOLD"]:
            self.auto_remove_closed_sold_states()

        # Trigger visual refresh
        self._update_hp_list_view()

        return self.hp_list

    def update_active_position_buy(
        self,
        data: HPBuyData,
    ) -> None:
        for position in self.active_records_buy:
            if (
                str(position["hp_id"]) == str(data.config.hp_id)
                and position["side"] == data.state_info.side.value
            ):
                logger.debug(
                    "Going to update active position %s %s",
                    position["hp_id"],
                    position["side"],
                )
                symbol_info = data.config.symbol_info
                position["completeness"] = str(data.state_info.completeness)
                position["state"] = str(data.state_info.ui_state)

                if data.state_info.ui_state == UiState.STAGNATED:
                    trigger_price = data.config.symbol_info.format_price(
                        (
                            (1 + (data.config.order_trigger / 100))
                            * data.config.price_high
                            if data.state_info.side.value == PositionSide.LONG.value
                            else (1 - (data.config.order_trigger / 100))
                            * data.config.price_low
                        )
                    )

                    self.active_records_buy.remove(position)
                    idle_position = IdlePositionBuy(
                        open_time=data.state_info.open_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=symbol_info.format_price(data.config.price_low),
                        price_high=symbol_info.format_price(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=f"{data.config.order_trigger},({trigger_price})",
                        state=str(data.state_info.ui_state),
                        completeness=str(data.state_info.completeness),
                    )
                    self.idle_records_buy.append(idle_position.to_dict())
                    logger.info(
                        "Price level stagnated(%s): %s",
                        data.config.hp_id,
                        idle_position,
                    )
                    self.filter_records("active", "All", side="BUY")
                    self.filter_records("idle", "All", side="BUY")
                    return

                if data.state_info.ui_state == UiState.CLOSED:
                    data.state_info.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.active_records_buy.remove(position)
                    archived_position = ArchivedPositionBuy(
                        open_time=data.state_info.open_time,
                        close_time=data.state_info.close_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=symbol_info.format_price(data.config.price_low),
                        price_high=symbol_info.format_price(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=str(data.config.order_trigger),
                        completeness=str(data.state_info.completeness),
                        sum_allocated=symbol_info.format_price(data.config.budget),
                        state=str(data.state_info.ui_state),
                    )
                    self.archived_records_buy.append(archived_position.to_dict())
                    logger.info(
                        "Closing price level(%s): %s",
                        data.config.hp_id,
                        archived_position,
                    )
                    self.filter_records("active", "All", side="BUY")
                    self.filter_records("archive", "All", side="BUY")
                    return

    def update_active_position_sell(
        self,
        data: HPSellData,
    ) -> None:
        for position in self.active_records_sell:
            if str(position["hp_id"]) == str(data.config.hp_id):
                symbol_info = data.config.symbol_info
                logger.debug(
                    "Going to update active position %s %s",
                    position["hp_id"],
                    position["side"],
                )
                symbol_info = data.config.symbol_info
                position["completeness"] = str(data.state_info.completeness)
                position["state"] = str(data.state_info.ui_state)

                if data.state_info.ui_state == UiState.STAGNATED:
                    self.active_records_sell.remove(position)
                    idle_position = IdlePositionSell(
                        open_time=data.state_info.open_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        buy_price=symbol_info.format_price(data.config.buy_price),
                        sell_price=symbol_info.format_price(data.config.sell_price),
                        quantity=symbol_info.format_quantity(data.config.quantity),
                        end_currency=str(data.config.end_currency),
                        state=str(data.state_info.ui_state),
                        completeness=str(data.state_info.completeness),
                    )
                    self.idle_records_sell.append(idle_position.to_dict())
                    logger.info(
                        "Sell position stagnated(%s): %s",
                        data.config.hp_id,
                        idle_position,
                    )
                    self.filter_records("active", "All", side="SELL")
                    self.filter_records("idle", "All", side="SELL")
                    return

                if data.state_info.ui_state == UiState.CLOSED:
                    data.state_info.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.active_records_sell.remove(position)
                    archived_position = ArchivedPositionSell(
                        open_time=data.state_info.open_time,
                        close_time=data.state_info.close_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        buy_price=symbol_info.format_price(data.config.buy_price),
                        sell_price=symbol_info.format_price(data.config.sell_price),
                        quantity=symbol_info.format_quantity(data.config.quantity),
                        end_currency=str(data.config.end_currency),
                        completeness=str(data.state_info.completeness),
                        state=str(data.state_info.ui_state),
                    )
                    self.archived_records_sell.append(archived_position.to_dict())
                    logger.info(
                        "Closing price level(%s): %s",
                        data.config.hp_id,
                        archived_position,
                    )
                    self.filter_records("active", "All", side="SELL")
                    self.filter_records("archive", "All", side="SELL")
                    return  # Update current price

    def update_idle_position_buy(
        self,
        data: HPBuyData,
    ) -> None:
        for position in self.idle_records_buy:
            if (
                position["hp_id"] == str(data.config.hp_id)
                and position["side"] == data.state_info.side.value
            ):
                logger.debug(
                    "Going to update idle position %s %s",
                    position["hp_id"],
                    position["side"],
                )
                symbol_info = data.config.symbol_info
                position["completeness"] = str(data.state_info.completeness)
                position["state"] = str(data.state_info.ui_state)
                # logger.info("Data state: %s", data.state_info.ui_state)
                if data.state_info.ui_state == UiState.OPEN:
                    self.idle_records_buy.remove(position)
                    cancel_price = data.config.symbol_info.format_price(
                        (
                            (1 + (2 * data.config.order_trigger / 100))
                            * data.config.price_high
                        )
                    )
                    active_position = ActivePositionBuy(
                        open_time=data.state_info.open_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=symbol_info.format_price(data.config.price_low),
                        price_high=symbol_info.format_price(data.config.price_high),
                        budget=str(data.config.budget),
                        order_cancel=f"{2 * data.config.order_trigger},({cancel_price})",
                        completeness=str(data.state_info.completeness),
                        state=str(data.state_info.ui_state),
                    )
                    self.active_records_buy.append(active_position.to_dict())
                    logger.info(
                        "Activating price level(%s): %s",
                        data.config.hp_id,
                        active_position,
                    )
                    self.filter_records("active", "All", side="BUY")
                    self.filter_records("idle", "All", side="BUY")
                    return
                if data.state_info.ui_state == UiState.CLOSED:
                    data.state_info.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.idle_records_buy.remove(position)
                    archived_position = ArchivedPositionBuy(
                        open_time=data.state_info.open_time,
                        close_time=data.state_info.close_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=symbol_info.format_price(data.config.price_low),
                        price_high=symbol_info.format_price(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=str(data.config.order_trigger),
                        completeness=str(data.state_info.completeness),
                        sum_allocated=symbol_info.format_price(data.config.budget),
                        state=str(data.state_info.ui_state),
                    )
                    self.archived_records_buy.append(archived_position.to_dict())
                    logger.info(
                        "Closing price level(%s): %s",
                        data.config.hp_id,
                        archived_position,
                    )
                    self.filter_records("archive", "All", side="BUY")
                    self.filter_records("idle", "All", side="BUY")
                    return

    def update_idle_position_sell(
        self,
        data: HPSellData,
    ) -> None:
        for position in self.idle_records_sell:
            if (
                position["hp_id"] == str(data.config.hp_id)
                and position["side"] == data.state_info.side.value
            ):
                symbol_info = data.config.symbol_info
                logger.debug(
                    "Going to update idle position %s %s",
                    position["hp_id"],
                    position["side"],
                )
                position["completeness"] = str(data.state_info.completeness)
                position["state"] = str(data.state_info.ui_state)
                # logger.info("Data state: %s", data.state_info.ui_state)
                if data.state_info.ui_state == UiState.OPEN:
                    self.idle_records_sell.remove(position)
                    active_position = ActivePositionSell(
                        open_time=data.state_info.open_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        buy_price=symbol_info.format_price(data.config.buy_price),
                        sell_price=symbol_info.format_price(data.config.sell_price),
                        quantity=symbol_info.format_quantity(data.config.quantity),
                        end_currency=str(data.config.end_currency),
                        completeness=str(data.state_info.completeness),
                        state=str(data.state_info.ui_state),
                    )
                    self.active_records_sell.append(active_position.to_dict())
                    logger.info(
                        "Activating price level(%s): %s",
                        data.config.hp_id,
                        active_position,
                    )
                    self.filter_records("active", "All", side="SELL")
                    self.filter_records("idle", "All", side="SELL")
                    return
                if data.state_info.ui_state == UiState.CLOSED:
                    data.state_info.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.idle_records_sell.remove(position)
                    archived_position = ArchivedPositionSell(
                        open_time=data.state_info.open_time,
                        close_time=data.state_info.close_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        buy_price=symbol_info.format_price(data.config.buy_price),
                        sell_price=symbol_info.format_price(data.config.sell_price),
                        quantity=symbol_info.format_quantity(data.config.quantity),
                        end_currency=str(data.config.end_currency),
                        completeness=str(data.state_info.completeness),
                        state=str(data.state_info.ui_state),
                    )
                    self.archived_records_sell.append(archived_position.to_dict())
                    logger.info(
                        "Closing price level(%s): %s",
                        data.config.hp_id,
                        archived_position,
                    )
                    self.filter_records("archive", "All", side="SELL")
                    self.filter_records("idle", "All", side="SELL")
                    return

    def _process_all_tickers(self, tickers: AllTickers) -> None:
        for strategy in (
            self.active_records_buy
            + self.idle_records_buy
            + self.active_records_sell
            + self.idle_records_sell
        ):
            for ticker in tickers.msg:
                symbol = ticker.get("s")
                if symbol == strategy["symbol"]:
                    strategy["current_price"] = self.symbols_info[symbol].format_price(
                        price=float(ticker["c"])
                    )

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
        if not self._validate_sell_inputs():
            return

        coin = str(self.ids.coin_input.text).strip().upper()
        coin = coin[:-3] if coin.endswith("USD") else coin

        sell_config = HPSellData(
            config=HPSellConfig(
                hp_id=str(self.ids.hp_id_input.text).strip(),
                coin=coin,
                buy_price=float(str(self.ids.buy_price_input.text).strip()),
                sell_price=float(str(self.ids.sell_price_input.text).strip()),
                quantity=float(str(self.ids.quantity_input.text).strip()),
                end_currency=self.ids.end_currency_spinner.text,
                symbol_info=self.symbols_info[f"{coin}USDT"],
            ),
            state_info=StateInfo(side=PositionSide.SHORT),
        )
        self.config_queue.put_nowait(sell_config)
        logger.info("Sell config added to the queue: %s", sell_config.config)

        self.filter_records("idle", "All", side="SELL")

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
            self.ids.sell_price_input.text = ""  # Optional: Clear any sell price input
            # self.ids.quantity_usd_label.text = "---"
            # self.ids.expected_gain_label.text = "---"
            # self.ids.expected_gain_percent_label.text = "---"
            # self.ids.total_usd_value_label.text = ""

    def filter_records(self, tab: str, symbol_filter, side: str) -> None:
        if side == PositionSide.LONG.value:
            if tab == "active":
                self.active_filter_buy = symbol_filter
                self.filtered_active_records_buy = [
                    record
                    for record in self.active_records_buy
                    if side == record["side"]
                    and symbol_filter in ("All", record["symbol"])
                ]
            elif tab == "idle":
                self.idle_filter_buy = symbol_filter
                self.filtered_idle_records_buy = [
                    record
                    for record in self.idle_records_buy
                    if side == record["side"]
                    and symbol_filter in ("All", record["symbol"])
                ]
            elif tab == "archive":
                self.archive_filter_buy = symbol_filter
                self.filtered_archived_records_buy = [
                    record
                    for record in self.archived_records_buy
                    if side == record["side"]
                    and symbol_filter in ("All", record["symbol"])
                ]

        if side == PositionSide.SHORT.value:
            if tab == "active":
                self.active_filter_sell = symbol_filter
                self.filtered_active_records_sell = [
                    record
                    for record in self.active_records_sell
                    if side == record["side"]
                    and (symbol_filter == "All" or record["symbol"] == symbol_filter)
                ]
            elif tab == "idle":
                self.idle_filter_sell = symbol_filter
                self.filtered_idle_records_sell = [
                    record
                    for record in self.idle_records_sell
                    if side == record["side"]
                    and (symbol_filter == "All" or record["symbol"] == symbol_filter)
                ]
            elif tab == "archive":
                self.archive_filter_sell = symbol_filter
                self.filtered_archived_records_sell = [
                    record
                    for record in self.archived_records_sell
                    if side == record["side"]
                    and (symbol_filter == "All" or record["symbol"] == symbol_filter)
                ]

        if not self.test_mode:
            self.ids.buy_active_records_list.refresh_from_data()
            self.ids.sell_active_records_list.refresh_from_data()
            self.ids.buy_idle_records_list.refresh_from_data()
            self.ids.sell_idle_records_list.refresh_from_data()
            self.ids.buy_archive_records_list.refresh_from_data()
            self.ids.sell_archive_records_list.refresh_from_data()

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

    def _archived_record_exists_buy(self, data: HPBuyData) -> bool:
        hp_id = str(data.config.hp_id)
        side = data.state_info.side.value
        return any(
            record["hp_id"] == hp_id
            and record["side"] == side
            and record["completeness"] == "1"
            for record in self.archived_records_buy
        )

    def _archived_record_exists_sell(self, data: HPSellData) -> bool:
        hp_id = str(data.config.hp_id)
        side = data.state_info.side.value
        return any(
            record["hp_id"] == hp_id
            and record["side"] == side
            and record["completeness"] == "1"
            for record in self.archived_records_sell
        )

    def _add_new_record_buy(self, data: HPBuyData) -> None:
        hp_id = str(data.config.hp_id)
        symbol_info = data.config.symbol_info
        if data.state_info.ui_state in [UiState.NEW, UiState.STAGNATED]:
            logger.info("New position added to Idle, system id: %s", hp_id)
            self.idle_records_buy.append(
                IdlePositionBuy(
                    open_time=data.state_info.open_time,
                    hp_id=str(data.config.hp_id),
                    symbol=data.config.symbol_info.symbol,
                    side=str(data.state_info.side.value),
                    mode=str(data.config.mode.value),
                    price_low=symbol_info.format_price(data.config.price_low),
                    price_high=symbol_info.format_price(data.config.price_high),
                    budget=str(data.config.budget),
                    order_trigger=f"{data.config.order_trigger},({self._calculate_trigger_price(data=data)})",
                    state=str(data.state_info.ui_state),
                    completeness=str(data.state_info.completeness),
                ).to_dict()
            )
        self.filter_records("idle", "All", side="BUY")
        if data.state_info.ui_state == UiState.OPEN:
            logger.info("New position added to Active, system id: %s", hp_id)
            self.active_records_buy.append(
                ActivePositionBuy(
                    open_time=data.state_info.open_time,
                    hp_id=str(data.config.hp_id),
                    symbol=data.config.symbol_info.symbol,
                    side=str(data.state_info.side.value),
                    mode=str(data.config.mode.value),
                    price_low=symbol_info.format_price(data.config.price_low),
                    price_high=symbol_info.format_price(data.config.price_high),
                    budget=str(data.config.budget),
                    order_cancel=f"{2 * data.config.order_trigger},({self._calculate_cancel_price(data=data)})",
                    completeness=str(data.state_info.completeness),
                    state=str(data.state_info.ui_state),
                ).to_dict()
            )
            self.filter_records("active", "All", side="BUY")

        if data.state_info.ui_state == UiState.CLOSED:
            if data.config.hp_id not in [
                item["hp_id"] for item in self.archived_records_buy
            ]:
                logger.info("New position added to Archive, system id: %s", hp_id)
                data.state_info.close_time = datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                self.archived_records_buy.append(
                    ArchivedPositionBuy(
                        open_time=data.state_info.open_time,
                        close_time=data.state_info.close_time,
                        hp_id=str(data.config.hp_id),
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.state_info.side.value),
                        mode=str(data.config.mode.value),
                        price_low=symbol_info.format_price(data.config.price_low),
                        price_high=symbol_info.format_price(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=str(data.config.order_trigger),
                        completeness=str(data.state_info.completeness),
                        sum_allocated=symbol_info.format_price(data.config.budget),
                        state=str(data.state_info.ui_state),
                    ).to_dict()
                )
                self.filter_records("archive", "All", side="BUY")
                self.filter_records("archive", "All", side="SELL")

    def _add_new_record_sell(self, data: HPSellData) -> None:
        logger.info("Going to add new IdlePositionSell")
        hp_id = str(data.config.hp_id)
        symbol_info = data.config.symbol_info

        if data.state_info.state == State.WAITING_CHILD:
            logger.warning("Skipping WAITING_CHILD record %s", hp_id)
            return

        if data.state_info.ui_state in [UiState.NEW, UiState.STAGNATED]:
            logger.info("New position added to Idle, system id: %s", hp_id)
            self.idle_records_sell.append(
                IdlePositionSell(
                    open_time=data.state_info.open_time,
                    hp_id=str(data.config.hp_id),
                    symbol=data.config.symbol_info.symbol,
                    side=str(data.state_info.side.value),
                    buy_price=symbol_info.format_price(data.config.buy_price),
                    sell_price=symbol_info.format_price(data.config.sell_price),
                    quantity=symbol_info.format_quantity(data.config.quantity),
                    end_currency=str(data.config.end_currency),
                    state=str(data.state_info.ui_state),
                    completeness=str(data.state_info.completeness),
                ).to_dict()
            )
        self.filter_records("idle", "All", side="SELL")
        if data.state_info.ui_state == UiState.OPEN:
            logger.info("New position added to Active, system id: %s", hp_id)
            self.active_records_sell.append(
                ActivePositionSell(
                    open_time=data.state_info.open_time,
                    hp_id=str(data.config.hp_id),
                    symbol=data.config.symbol_info.symbol,
                    side=str(data.state_info.side.value),
                    buy_price=symbol_info.format_price(data.config.buy_price),
                    sell_price=symbol_info.format_price(data.config.sell_price),
                    quantity=symbol_info.format_quantity(data.config.quantity),
                    end_currency=str(data.config.end_currency),
                    completeness=str(data.state_info.completeness),
                    state=str(data.state_info.ui_state),
                ).to_dict()
            )
            self.filter_records("active", "All", side="SELL")

        if data.state_info.ui_state == UiState.CLOSED:
            logger.info("New position added to Archive, system id: %s", hp_id)
            data.state_info.close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.archived_records_buy.append(
                ArchivedPositionSell(
                    open_time=data.state_info.open_time,
                    close_time=data.state_info.close_time,
                    hp_id=str(data.config.hp_id),
                    symbol=data.config.symbol_info.symbol,
                    side=str(data.state_info.side.value),
                    buy_price=symbol_info.format_price(data.config.buy_price),
                    sell_price=symbol_info.format_price(data.config.sell_price),
                    quantity=symbol_info.format_quantity(data.config.quantity),
                    end_currency=str(data.config.end_currency),
                    completeness=str(data.state_info.completeness),
                    state=str(data.state_info.ui_state),
                ).to_dict()
            )
            self.filter_records("archive", "All", side="SELL")
        logger.info("New record added to sell")

    def _log_all_records_buy(self) -> None:
        logger.info(
            "\nRecords active:\n%s\nIdle\n%s\nArchive\n%s",
            self.active_records_buy,
            self.idle_records_buy,
            self.archived_records_buy,
        )
        logger.info("HP LIST: %s", self.hp_list_data)

    def _log_all_records_sell(self) -> None:
        logger.info(
            "\nRecords active:\n%s\nIdle\n%s\nArchive\n%s",
            self.active_records_sell,
            self.idle_records_sell,
            self.archived_records_sell,
        )
        logger.info("HP LIST: %s", self.hp_list_data)

    async def _refresh_ui(self):
        while True:
            # Update all records, but NOT hp_list_view (it is updated elsewhere manually)
            if "buy_active_records_list" in self.ids:
                self.ids.buy_active_records_list.refresh_from_data()
            if "sell_active_records_list" in self.ids:
                self.ids.sell_active_records_list.refresh_from_data()
            if "buy_idle_records_list" in self.ids:
                self.ids.buy_idle_records_list.refresh_from_data()
            if "sell_idle_records_list" in self.ids:
                self.ids.sell_idle_records_list.refresh_from_data()
            if "buy_archive_records_list" in self.ids:
                self.ids.buy_archive_records_list.refresh_from_data()
            if "sell_archive_records_list" in self.ids:
                self.ids.sell_archive_records_list.refresh_from_data()
            await asyncio.sleep(0.1)

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

    def _update_active_symbols_buy(self, *args) -> None:
        symbols = {"All"}
        for record in self.active_records_buy:
            symbols.add(record.get("symbol", ""))
        if not self.test_mode:
            self.ids.active_filter_input_buy.values = sorted(list(symbols))

    def _update_idle_symbols_buy(self, *args) -> None:
        symbols = {"All"}
        for record in self.idle_records_buy:
            symbols.add(record.get("symbol", ""))
        if not self.test_mode:
            self.ids.idle_filter_input_buy.values = sorted(list(symbols))

    def _update_archive_symbols_buy(self, *args) -> None:
        symbols = {"All"}
        for record in self.archived_records_buy:
            symbols.add(record.get("symbol", ""))
        if not self.test_mode:
            self.ids.archive_filter_input_buy.values = sorted(list(symbols))

    def _update_active_symbols_sell(self, *args) -> None:
        symbols = {"All"}
        for record in self.active_records_sell:
            symbols.add(record.get("symbol", ""))
        if not self.test_mode:
            self.ids.active_filter_input_sell.values = sorted(list(symbols))

    def _update_idle_symbols_sell(self, *args) -> None:
        symbols = {"All"}
        for record in self.idle_records_sell:
            symbols.add(record.get("symbol", ""))
        if not self.test_mode:
            self.ids.idle_filter_input_sell.values = sorted(list(symbols))

    def _update_archive_symbols_sell(self, *args) -> None:
        symbols = {"All"}
        for record in self.archived_records_sell:
            symbols.add(record.get("symbol", ""))
        if not self.test_mode:
            self.ids.archive_filter_input_sell.values = sorted(list(symbols))

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

        parents = [hp for hp in filtered_data if not hp.get("is_child", False)]
        children = [hp for hp in filtered_data if hp.get("is_child", False)]

        sorted_list = []
        for parent in sorted(parents, key=lambda x: int(x["hp_id"])):
            # Add has_children property to parent for UI rendering
            parent_children = [
                c for c in children if c.get("parent_hp_id") == parent["hp_id"]
            ]
            parent["has_children"] = len(parent_children) > 0
            parent["is_expanded"] = parent["hp_id"] in self.expanded_hp_ids
            sorted_list.append(parent)

            # Only add children if parent is expanded
            if parent["hp_id"] in self.expanded_hp_ids:
                for child in sorted(parent_children, key=lambda x: x["hp_id"]):
                    sorted_list.append(child)
        return sorted_list

    def _update_hp_list_view(self, *args):
        if "hp_list_view" not in self.ids:
            logger.warning(
                "Tried to update hp_list_view, but it's not yet initialized."
            )
            return

        valid_keys = {
            "hp_id",
            "coin",
            "buy_price",
            "quantity",
            "quantity_usd",
            "sell_price",
            "expected_return",
            "current_price",
            "net",
            "net_percent",
            "state",
            "is_child",
            "has_children",
            "is_expanded",
        }

        cleaned_data = []
        for item in self._get_sorted_hp_list():
            filtered = {k: item.get(k, "") for k in valid_keys}
            # Kivy's RecycleView needs everything as strings or primitives
            filtered["is_child"] = bool(item.get("is_child", False))
            filtered["has_children"] = bool(item.get("has_children", False))
            filtered["is_expanded"] = bool(item.get("is_expanded", False))
            filtered["hp_manager"] = self
            cleaned_data.append(filtered)

        self.ids.hp_list_view.data = cleaned_data
        self.ids.hp_list_view.refresh_from_data()

    def load_positions_from_csv(self):
        filename = self.ids.filenameinput.text.strip()
        if not filename:
            logger.warning("No filename provided. Load aborted.")
            return

        path = f"{filename}.csv"
        try:
            with open(path, "r") as f:
                reader = csv.DictReader(f)
                parsed = [row for row in reader]

            inventory_items = []
            for row in parsed:
                try:
                    item = InventoryItem(
                        id=row.get("id") or str(uuid.uuid4()),
                        coin=row["coin"],
                        buy_price=float(row["buy_price"]),
                        quantity=float(row["quantity"]),
                        available_quantity=float(
                            row.get("available_quantity", row["quantity"])
                        ),
                        locked_quantity=float(row.get("locked_quantity", 0)),
                        source=row.get("source", "import"),
                        timestamp=(
                            datetime.datetime.fromisoformat(row["timestamp"])
                            if "timestamp" in row and row["timestamp"]
                            else datetime.datetime.now()
                        ),
                        notes=row.get("notes"),
                    )
                    inventory_items.append(item)
                except Exception as e:
                    logger.error("Failed to parse inventory row: %s error: %s", row, e)

            self.portfolio_queue.put_nowait(
                Event(name=EventName.PORTFOLIO_INVENTORY, content=inventory_items)
            )
            logger.info("Queued LoadConfig from %s", path)
        except Exception as e:
            logger.error("Failed to load CSV: %s", e)

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
            logger.info("Automatically removed CLOSED and SOLD states from filter")

    # def calculate_expected_gain(self, sell_price):
    #     """
    #     Calculate the expected gain and gain percentage based on the sell price.

    #     Args:
    #     - sell_price: The entered sell price.
    #     """
    #     try:
    #         sell_price_float = float(sell_price)
    #         quantity_float = float(self.ids.quantity_label.text)
    #         quantity_usd_float = float(self.ids.quantity_usd_label.text)
    #         buy_price_float = float(self.ids.buy_price_label.text)

    #         # Total USD value calculation
    #         total_usd_value = sell_price_float * quantity_float

    #         # Expected gain calculations
    #         expected_gain_usd = total_usd_value - quantity_usd_float
    #         expected_gain_percent = ((sell_price_float / buy_price_float) - 1) * 100

    #         # Update labels
    #         self.ids.expected_gain_label.text = f"{expected_gain_usd:.2f}"
    #         self.ids.expected_gain_percent_label.text = f"{expected_gain_percent:.2f}%"
    #         self.ids.total_usd_value_label.text = f"{total_usd_value:.2f}"

    #     except ValueError:
    #         # Handle potential conversion errors (e.g., if the inputs are not valid floats)
    #         logger.error("Error in calculating expected gain. Invalid input detected.")
    #         self.ids.expected_gain_label.text = "---"
    #         self.ids.expected_gain_percent_label.text = "---"
