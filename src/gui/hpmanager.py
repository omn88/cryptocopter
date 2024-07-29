import asyncio
import csv
from datetime import datetime
import os
from typing import Dict, List, Optional
import uuid
from binance import BinanceSocketManager
from kivy.properties import (
    ListProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.boxlayout import BoxLayout
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, Mode, PositionSide
from src.common.identifiers.spot import (
    AccountPosition,
    CsvConfig,
    Event,
    EventName,
    State,
    StrategyConfig,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.gui.searchable_drop_down import SearchableDropDown
from src.trading_system.spot import TradingSystem
from src.workers.strategy_executor import StrategyExecutor


class HpManager(BoxLayout):
    active_records: List[Dict] = ListProperty([])
    idle_records: List[Dict] = ListProperty([])
    archive_records: List[Dict] = ListProperty([])
    filtered_active_records: List[Dict] = ListProperty([])
    filtered_idle_records: List[Dict] = ListProperty([])
    filtered_archive_records: List[Dict] = ListProperty([])
    active_filter = StringProperty("All")
    idle_filter = StringProperty("All")
    archive_filter = StringProperty("All")

    log_display = ObjectProperty(None)
    file_name_input = ObjectProperty(None)
    symbols = ListProperty()

    config_dir = os.path.join("src", "strategies", "spot")

    def __init__(
        self,
        client: BinanceClient,
        db: Database,
        strategy_logger: StrategyLogger,
        strategy_id: str,
        usdt_balance: float,
        symbols_info: Dict[str, SymbolInfo],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.symbols_info = symbols_info
        self.client = client
        self.db = db
        self.strategy_id = strategy_id
        self.gui_handler: asyncio.Queue = asyncio.Queue()
        self.socket_manager = BinanceSocketManager(client=client)
        self.strategy_logger = strategy_logger
        self.usdt_balance = usdt_balance
        self.strategy_executor = StrategyExecutor(
            client=client, logger=strategy_logger, gui_handler=self.gui_handler, db=db
        )
        self.bind(active_records=self.update_active_symbols)
        self.bind(idle_records=self.update_idle_symbols)
        self.bind(archive_records=self.update_archive_symbols)
        self.symbols = [symbol for symbol, info in self.symbols_info.items()]
        asyncio.create_task(self.strategy_executor.run())
        asyncio.create_task(self.update_ui())

        # Create the SearchableDropDown instance with the client
        self.symbol_input = SearchableDropDown(client=self.client, options=self.symbols)
        # Add it to the layout where needed
        self.ids.symbol_container.add_widget(self.symbol_input)

    def update_label(self, instance, value) -> None:
        self.selected_label.text = value

    def update_active_symbols(self, *args) -> None:
        symbols = {"All"}
        for record in self.active_records:
            symbols.add(record.get("symbol", ""))
        self.ids.active_filter_input.values = sorted(list(symbols))

    def update_idle_symbols(self, *args) -> None:
        symbols = {"All"}
        for record in self.idle_records:
            symbols.add(record.get("symbol", ""))
        self.ids.idle_filter_input.values = sorted(list(symbols))

    def update_archive_symbols(self, *args) -> None:
        symbols = {"All"}
        for record in self.archive_records:
            symbols.add(record.get("symbol", ""))
        self.ids.archive_filter_input.values = sorted(list(symbols))

    def validate_inputs(self) -> bool:
        symbol = self.symbol_input.selected_value
        price_low = self.symbol_input.price_low_input.text
        price_high = self.symbol_input.price_high_input.text
        side = self.ids.side_input.text
        budget = self.ids.budget_input.text
        order_trigger = self.ids.order_trigger_input.text
        mode = self.ids.mode_input.text

        validation_message = ""
        if not symbol:
            validation_message += "Symbol is required. "
        if not price_low or not price_high:
            validation_message += "Price range is required. "
        if not side or side == "SIDE":
            validation_message += "Side is required. "
        if not budget:
            validation_message += "Budget is required. "
        if not order_trigger:
            validation_message += "Order trigger is required. "
        if mode not in [Mode.DCA.value, Mode.SINGLE.value]:
            validation_message += "Mode has to be selected."
        if price_low > price_high:
            validation_message += "Price low is bigger than price high. "

        self.ids.validation_label.text = validation_message

        return not validation_message

    def trigger_add_record(self, *args) -> None:
        if not self.validate_inputs():
            return
        asyncio.create_task(
            self.add_record(
                open_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol=self.symbol_input.selected_value,
                price_low=float(self.symbol_input.price_low_input.text),
                price_high=float(self.symbol_input.price_high_input.text),
                side=PositionSide.LONG
                if self.ids.side_input.text == PositionSide.LONG.value
                else PositionSide.SHORT,
                budget=float(self.ids.budget_input.text),
                order_trigger=float(self.ids.order_trigger_input.text),
                mode=Mode.DCA
                if self.ids.mode_input.text == Mode.DCA.value
                else Mode.SINGLE,
            )
        )

    async def add_record(
        self,
        symbol: str,
        side: PositionSide,
        price_low: float,
        price_high: float,
        budget: float,
        order_trigger: float,
        mode: Mode,
        stagnation_counter: int = 0,
        next_monitor_time: str = "",
        open_time: Optional[str] = None,
        last_state: Optional[State] = None,
        system_id: Optional[str] = None,
    ) -> None:
        if system_id is None:
            system_id = str(uuid.uuid4())

        config = StrategyConfig(
            open_time=open_time,
            system_id=system_id,
            symbol_info=self.symbols_info[symbol],
            side=side,
            price_low=price_low,
            price_high=price_high,
            budget=budget,
            order_trigger=order_trigger,
            mode=mode,
        )
        self.strategy_logger.info(f"Adding new record with config: {config}")
        await self.strategy_executor.config_queue.put(
            [last_state, config, stagnation_counter, next_monitor_time]
        )

        if (
            last_state is None
        ):  # inserting level only if there is no last known status, recovery will
            state = State.NEW
            await self.gui_handler.put(
                PositionData(
                    config=config,
                    orders_opened=0,
                    orders_filled=0,
                    orders_total=0,
                    state=state,
                )
            )
            await self.db.insert_price_level(config=config, state=state)

        self.filter_records(tab="idle", symbol_filter="All")

    def trigger_remove_record(
        self,
        system_id,
        *args,
    ) -> None:
        asyncio.create_task(self.remove_record(system_id=system_id))

    async def remove_record(self, system_id) -> None:
        # Send a command to the strategy executor to stop the trading process
        await self.strategy_executor.remove_record(system_id=system_id)

    def save_config(self) -> None:
        file_name = self.file_name_input.text.strip()
        if not file_name:
            # Provide feedback to the user if the file name is empty
            print("Please enter a file name.")
            return

        # Ensure the directory exists
        os.makedirs(self.config_dir, exist_ok=True)

        file_path = os.path.join(self.config_dir, f"{file_name}.csv")

        config_data = self.get_current_configuration()

        self.strategy_logger.info("Trying to write to: %s", file_path)
        with open(file_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            # Write the headers
            writer.writerow(
                [
                    "Symbol",
                    "Side",
                    "Price Low",
                    "Price High",
                    "Budget",
                    "Order Trigger",
                    "Mode",
                ]
            )  # Adjust according to your actual parameters
            # Write the data
            writer.writerows(
                [
                    [
                        cd.symbol,
                        cd.side,
                        cd.price_low,
                        cd.price_high,
                        cd.budget,
                        cd.order_trigger,
                        cd.mode,
                    ]
                    for cd in config_data
                ]
            )

    def load_config(self) -> None:
        file_name = self.file_name_input.text.strip()
        if not file_name:
            # Provide feedback to the user if the file name is empty
            print("Please enter a file name.")
            return

        file_path = os.path.join(self.config_dir, f"{file_name}.csv")

        try:
            with open(file_path, "r", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)
                headers = next(reader)  # Skip the headers
                config_data = list(reader)
                self.apply_configuration(
                    [
                        CsvConfig(
                            symbol=cd[0],
                            side=cd[1],
                            price_low=float(cd[2]),
                            price_high=float(cd[3]),
                            budget=float(cd[4]),
                            order_trigger=float(cd[5]),
                            mode=cd[6],
                        )
                        for cd in config_data
                    ]
                )
        except FileNotFoundError:
            # Provide feedback to the user if the file is not found
            print(f"File {file_name}.csv not found.")

    def get_current_configuration(self) -> List[CsvConfig]:
        hp_config = []
        for info, item in self.strategy_executor.id_to_system.items():
            self.strategy_logger.info("Item to: %s, typ: %s", item, type(item))
            assert isinstance(item, TradingSystem)
            hp_config.append(
                CsvConfig(
                    symbol=item.config.symbol_info.symbol,
                    side=item.config.side.value,
                    price_low=item.config.price_low,
                    price_high=item.config.price_high,
                    budget=item.config.budget,
                    order_trigger=item.config.order_trigger,
                    mode=item.config.mode.value,
                )
            )
        return hp_config

    def apply_configuration(self, config_data: List[CsvConfig]) -> None:
        for data in config_data:
            asyncio.create_task(
                self.add_record(
                    open_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    symbol=data.symbol,
                    price_low=data.price_low,
                    price_high=data.price_high,
                    side=PositionSide.LONG
                    if data.side == PositionSide.LONG.value
                    else PositionSide.SHORT,
                    budget=data.budget,
                    order_trigger=data.order_trigger,
                    mode=Mode.DCA if data.mode == Mode.DCA.value else Mode.SINGLE,
                )
            )

    async def update_ui(self) -> None:
        while True:
            if self.gui_handler.qsize() == 0:
                await asyncio.sleep(1)
                continue
            data = await self.gui_handler.get()
            if isinstance(data, Event) and data.name == EventName.SENTINEL:
                self.strategy_logger.info("Received sentinel event, exiting")
                return

            if isinstance(data, AccountPosition):
                pass  # handle account update

            if isinstance(data, PositionData):
                self.strategy_logger.debug("Received position data: %s", data)
                if data.recovering:
                    if data.state == State.OPEN:
                        self.strategy_logger.logger.debug(
                            "Recovering position to active tab in GUI: %s", data
                        )
                        self.recovery_to_active(data=data)
                    if data.state == State.NEW:
                        self.strategy_logger.logger.debug(
                            "Recovering position to idle tab in GUI: %s", data
                        )
                        self.recovery_to_idle(data=data)

                elif any(
                    record["system_id"] == data.config.system_id
                    for record in self.active_records
                ):
                    self.strategy_logger.debug(
                        "Record %s found in active records", data.config.system_id
                    )
                    self.update_active_position(data=data)
                elif any(
                    record["system_id"] == data.config.system_id
                    for record in self.idle_records
                ):
                    self.strategy_logger.debug(
                        "Record %s found in idle records", data.config.system_id
                    )
                    self.update_idle_position(data=data)
                else:
                    self.strategy_logger.debug(
                        "New position added to Idle, system id: %s",
                        data.config.system_id,
                    )
                    self.add_new_position(data=data)
                self.strategy_logger.debug(
                    "Records active:\n%s\nIdle\n%s\nArchive\n%s",
                    self.active_records,
                    self.idle_records,
                    self.archive_records,
                )

    def add_new_position(self, data: PositionData) -> None:
        new_position = {
            "open_time": data.config.open_time,
            "system_id": data.config.system_id,
            "symbol": data.config.symbol_info.symbol,
            "side": str(data.config.side.value),
            "mode": str(data.config.mode.value),
            "price_low": str(data.config.price_low),
            "price_high": str(data.config.price_high),
            "budget": str(data.config.budget),
            "order_trigger": str(data.config.order_trigger),
            "orders_opened": str(data.orders_opened),
            "orders_total": str(data.orders_total),
            "orders_filled": str(data.orders_filled),
            "state": str(data.state),
        }

        self.idle_records.append(new_position)
        self.filter_records("idle", "All")

    def recovery_to_active(self, data: PositionData) -> None:
        new_position = {
            "open_time": data.config.open_time,
            "system_id": data.config.system_id,
            "symbol": data.config.symbol_info.symbol,
            "side": str(data.config.side.value),
            "price_low": str(data.config.price_low),
            "price_high": str(data.config.price_high),
            "budget": str(data.config.budget),
            "order_trigger": str(data.config.order_trigger),
            "orders_opened": str(data.orders_opened),
            "orders_total": str(data.orders_total),
            "orders_filled": str(data.orders_filled),
            "mode": str(data.config.mode.value),
            "state": str(data.state),
        }

        self.active_records.append(new_position)
        self.filter_records("active", "All")

    def recovery_to_idle(self, data: PositionData) -> None:
        new_position = {
            "open_time": data.config.open_time,
            "system_id": data.config.system_id,
            "symbol": data.config.symbol_info.symbol,
            "side": str(data.config.side.value),
            "price_low": str(data.config.price_low),
            "price_high": str(data.config.price_high),
            "budget": str(data.config.budget),
            "order_trigger": str(data.config.order_trigger),
            "orders_opened": str(data.orders_opened),
            "orders_total": str(data.orders_total),
            "orders_filled": str(data.orders_filled),
            "mode": str(data.config.mode.value),
            "state": str(data.state),
        }

        self.idle_records.append(new_position)
        self.filter_records("idle", "All")

    # ToDO: Recovery to stagnated and update stagnated position to be added?!!!
    def update_active_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.active_records:
            if position["system_id"] == data.config.system_id:
                position.update(
                    {
                        "orders_opened": str(data.orders_opened),
                        "orders_total": str(data.orders_total),
                        "orders_filled": str(data.orders_filled),
                        "state": str(data.state),
                    }
                )
                if data.state == State.CLOSED:
                    self.active_records.remove(position)
                    self.archive_records.append(position)
                    self.strategy_logger.debug("Archiving price level: %s", position)
                    if data.orders_total == data.orders_filled:
                        asyncio.create_task(
                            self.remove_record(system_id=data.config.system_id)
                        )

        self.filter_records("active", "All")
        self.filter_records("archive", "All")

    def update_idle_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.idle_records:
            if position["system_id"] == data.config.system_id:
                self.strategy_logger.debug("Will update position")
                position.update(
                    {
                        "orders_opened": str(data.orders_opened),
                        "orders_total": str(data.orders_total),
                        "orders_filled": str(data.orders_filled),
                        "state": str(data.state),
                    }
                )
                if data.state == State.OPEN:
                    self.idle_records.remove(position)
                    self.active_records.append(position)
                    self.strategy_logger.debug("Activating price level: %s", position)
                if data.state == State.CLOSED:
                    self.idle_records.remove(position)
                    self.archive_records.append(position)
                    self.strategy_logger.debug("Archiving price level: %s", position)

        self.filter_records("idle", "All")
        self.filter_records("active", "All")
        self.filter_records("archive", "All")

    def filter_records(self, tab, symbol_filter) -> None:
        if tab == "active":
            self.active_filter = symbol_filter
            self.filtered_active_records = [
                record
                for record in self.active_records
                if symbol_filter == "All" or record["symbol"] == symbol_filter
            ]
        elif tab == "idle":
            self.idle_filter = symbol_filter
            self.filtered_idle_records = [
                record
                for record in self.idle_records
                if symbol_filter == "All" or record["symbol"] == symbol_filter
            ]
        elif tab == "archive":
            self.archive_filter = symbol_filter
            self.filtered_archive_records = [
                record
                for record in self.archive_records
                if symbol_filter == "All" or record["symbol"] == symbol_filter
            ]

        self.ids.active_records_list.refresh_from_data()
        self.ids.idle_records_list.refresh_from_data()
        self.ids.archive_records_list.refresh_from_data()
