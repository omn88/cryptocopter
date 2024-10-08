import asyncio
from datetime import datetime
import os
import queue
import logging
from typing import Dict, List
import uuid
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
    AllTickers,
    CsvConfig,
    Event,
    EventName,
    LoadConfig,
    PositionSetup,
    RemoveRecord,
    SaveConfig,
    State,
    StateInfo,
    StrategyConfig,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import (
    ActivePosition,
    ArchivedPosition,
    IdlePosition,
    PositionData,
)
from src.gui.searchable_drop_down import SearchableDropDown


logger = logging.getLogger("HP_GUI")


class HpManager(BoxLayout):
    hp_list_data: List[Dict] = ListProperty([])
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
        strategy_logger: StrategyLogger,
        strategy_id: str,
        config_queue: queue.Queue,
        ui_queue: queue.Queue,
        symbols_info: Dict[str, SymbolInfo],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.symbols_info = symbols_info
        self.client = client
        self.strategy_id = strategy_id
        self.ui_queue = ui_queue
        self.strategy_logger = strategy_logger
        self.config_queue = config_queue
        self.bind(active_records=self.update_active_symbols)
        self.bind(idle_records=self.update_idle_symbols)
        self.bind(archive_records=self.update_archive_symbols)
        self.symbols = [symbol for symbol, info in self.symbols_info.items()]
        asyncio.create_task(self.update_ui())
        asyncio.create_task(self.refresh_ui())

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

        config = StrategyConfig(
            open_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            system_id=str(uuid.uuid4()),
            symbol_info=self.symbols_info[self.symbol_input.selected_value],
            side=PositionSide.LONG
            if self.ids.side_input.text == PositionSide.LONG.value
            else PositionSide.SHORT,
            price_low=float(self.symbol_input.price_low_input.text),
            price_high=float(self.symbol_input.price_high_input.text),
            budget=float(self.ids.budget_input.text),
            order_trigger=float(self.ids.order_trigger_input.text),
            mode=Mode.DCA
            if self.ids.mode_input.text == Mode.DCA.value
            else Mode.SINGLE,
        )

        state_info = StateInfo()

        self.config_queue.put_nowait(
            PositionSetup(
                config=config,
                state_info=state_info,
            )
        )
        self.ui_queue.put_nowait(
            PositionData(config=config, state_info=state_info, completeness=0)
        )

        self.filter_records(tab="idle", symbol_filter="All")

    def trigger_remove_record(
        self,
        system_id,
        symbol,
        *args,
    ) -> None:
        record = RemoveRecord(system_id=system_id, symbol=symbol)
        self.config_queue.put_nowait(record)
        logger.info("Remove record: %s sent to backend.", record)

    def save_config(self) -> None:
        file_name = self.file_name_input.text.strip()
        if not file_name:
            # Provide feedback to the user if the file name is empty
            print("Please enter a file name.")
            return

        # Put the SaveConfig NamedTuple into the config_queue
        self.config_queue.put(SaveConfig(file_name=file_name))
        logger.info("Saving configuration request for %s sent to backend.", file_name)

    def load_config(self) -> None:
        file_name = self.file_name_input.text.strip()
        if not file_name:
            # Provide feedback to the user if the file name is empty
            print("Please enter a file name.")
            return

        # Put the LoadConfig NamedTuple into the config_queue
        self.config_queue.put(LoadConfig(file_name=file_name))
        logger.info("Loading configuration request for %s sent to backend.", file_name)

    async def update_ui(self) -> None:
        logger.info("Ready to receive UI updates")
        while True:
            try:
                data = self.ui_queue.get_nowait()

                if isinstance(data, Event) and data.name == EventName.SENTINEL:
                    logger.info("Received sentinel event, exiting")
                    return

                if isinstance(data, AccountPosition):
                    pass  # handle account update

                if isinstance(data, PositionData):
                    logger.info("Received position data: %s", data)
                    if data.recovering:
                        if data.state_info.last_state == State.OPEN:
                            logger.info(
                                "Recovering position to active tab in GUI: %s", data
                            )
                            self.recovery_to_active(data=data)
                        if data.state_info.last_state == State.NEW:
                            logger.info(
                                "Recovering position to idle tab in GUI: %s", data
                            )
                            self.recovery_to_idle(data=data)

                    elif any(
                        record["system_id"] == data.config.system_id
                        for record in self.active_records
                    ):
                        logger.info(
                            "Record %s found in active records", data.config.system_id
                        )
                        self.update_active_position(data=data)
                    elif any(
                        record["system_id"] == data.config.system_id
                        for record in self.idle_records
                    ):
                        logger.info(
                            "Record %s found in idle records", data.config.system_id
                        )
                        self.update_idle_position(data=data)
                    else:
                        if data.state_info.last_state in [State.NEW, None]:
                            logger.info(
                                "New position added to Idle, system id: %s",
                                data.config.system_id,
                            )
                            self.add_new_position_to_idle(data=data)
                        if data.state_info.last_state == State.OPEN:
                            logger.info(
                                "New position added to Active, system id: %s",
                                data.config.system_id,
                            )
                            self.add_new_position_to_active(data=data)
                    logger.info(
                        "Records active:\n%s\nIdle\n%s\nArchive\n%s",
                        self.active_records,
                        self.idle_records,
                        self.archive_records,
                    )

                if isinstance(data, Event) and data.name == EventName.ALL_TICKERS:
                    for strategy in self.active_records:
                        assert isinstance(data.content, AllTickers)
                        for ticker in data.content.msg:
                            symbol = ticker.get("s")
                            if symbol == strategy["symbol"]:
                                price = str(
                                    self.symbols_info[symbol].adjust_price(
                                        price=float(ticker["c"])
                                    )
                                )
                                strategy["current_price"] = price

                    for strategy in self.idle_records:
                        assert isinstance(data.content, AllTickers)
                        for ticker in data.content.msg:
                            symbol = ticker.get("s")
                            if symbol == strategy["symbol"]:
                                price = str(
                                    self.symbols_info[symbol].adjust_price(
                                        price=float(ticker["c"])
                                    )
                                )
                                strategy["current_price"] = price
            except queue.Empty:
                await asyncio.sleep(0.1)

    async def refresh_ui(self):
        while True:
            # Reassign the data to trigger the UI update
            self.ids.active_records_list.refresh_from_data()
            self.ids.idle_records_list.refresh_from_data()
            self.ids.archive_records_list.refresh_from_data()
            await asyncio.sleep(1)

    def add_new_position_to_idle(self, data: PositionData) -> None:
        trigger_price = data.config.symbol_info.adjust_price(
            (
                (1 + (data.config.order_trigger / 100)) * data.config.price_high
                if data.config.side.value == PositionSide.LONG.value
                else (1 - (data.config.order_trigger / 100)) * data.config.price_low
            )
        )

        self.idle_records.append(
            IdlePosition(
                open_time=data.config.open_time,
                system_id=data.config.system_id,
                symbol=data.config.symbol_info.symbol,
                side=str(data.config.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_trigger=f"{data.config.order_trigger},({trigger_price})",
                state=str(data.state_info.last_state),
                completeness=str(data.completeness),
            ).to_dict()
        )
        self.filter_records("idle", "All")

    def add_new_position_to_active(self, data: PositionData) -> None:
        cancel_price = data.config.symbol_info.adjust_price(
            (
                (1 + (2 * data.config.order_trigger / 100)) * data.config.price_high
                if data.config.side.value == PositionSide.LONG.value
                else (1 - (2 * data.config.order_trigger / 100)) * data.config.price_low
            )
        )

        self.active_records.append(
            ActivePosition(
                open_time=data.config.open_time,
                system_id=data.config.system_id,
                symbol=data.config.symbol_info.symbol,
                side=str(data.config.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_cancel=f"{2 * data.config.order_trigger},({cancel_price})",
                stagnation=f"{data.state_info.stagnation_counter}/{data.stagnation_limit}",
                completeness=str(data.completeness),
                state=str(data.state_info.last_state),
            ).to_dict()
        )
        self.filter_records("active", "All")

    def add_position_to_archive(self, data: PositionData) -> None:
        data.config.close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.archive_records.append(
            ArchivedPosition(
                open_time=data.config.open_time,
                close_time=data.config.close_time,
                system_id=data.config.system_id,
                symbol=data.config.symbol_info.symbol,
                side=str(data.config.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_trigger=str(data.config.order_trigger),
                completeness=str(data.completeness),
            ).to_dict()
        )
        self.filter_records("archive", "All")

    def recovery_to_active(self, data: PositionData) -> None:
        cancel_price = data.config.symbol_info.adjust_price(
            (
                (1 + (2 * data.config.order_trigger / 100)) * data.config.price_high
                if data.config.side.value == PositionSide.LONG.value
                else (1 - (2 * data.config.order_trigger / 100)) * data.config.price_low
            )
        )

        self.active_records.append(
            ActivePosition(
                open_time=data.config.open_time,
                system_id=data.config.system_id,
                symbol=data.config.symbol_info.symbol,
                side=str(data.config.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_cancel=f"{2 * data.config.order_trigger},({cancel_price})",
                stagnation=f"{data.state_info.stagnation_counter}/{data.stagnation_limit}",
                completeness=str(data.completeness),
                state=str(data.state_info.last_state),
            ).to_dict()
        )
        self.filter_records("active", "All")

    def recovery_to_idle(self, data: PositionData) -> None:
        trigger_price = data.config.symbol_info.adjust_price(
            (
                (1 + (data.config.order_trigger / 100)) * data.config.price_high
                if data.config.side.value == PositionSide.LONG.value
                else (1 - (data.config.order_trigger / 100)) * data.config.price_low
            )
        )

        self.idle_records.append(
            IdlePosition(
                open_time=data.config.open_time,
                system_id=data.config.system_id,
                symbol=data.config.symbol_info.symbol,
                side=str(data.config.side.value),
                mode=str(data.config.mode.value),
                price_low=str(data.config.price_low),
                price_high=str(data.config.price_high),
                budget=str(data.config.budget),
                order_trigger=f"{data.config.order_trigger},({trigger_price})",
                state=str(data.state_info.last_state),
                completeness=str(data.completeness),
            ).to_dict()
        )
        self.filter_records("idle", "All")

    def update_active_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.active_records:
            if position["system_id"] == data.config.system_id:
                position["stagnation_counter"] = str(data.state_info.stagnation_counter)
                position["stagnation_limit"] = str(data.stagnation_limit)
                position["completeness"] = str(data.completeness)
                position["state"] = str(data.state_info.last_state)

                if data.state_info.last_state == State.CLOSED:
                    data.config.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.active_records.remove(position)
                    archived_position = ArchivedPosition(
                        open_time=data.config.open_time,
                        close_time=data.config.close_time,
                        system_id=data.config.system_id,
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.config.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=str(data.config.order_trigger),
                        completeness=str(data.completeness),
                    )
                    self.archive_records.append(archived_position.to_dict())
                    logger.info("Archiving price level: %s", archived_position)
                    if data.completeness == 1.0:
                        self.config_queue.put_nowait(
                            RemoveRecord(
                                system_id=data.config.system_id,
                                symbol=data.config.symbol_info.symbol,
                            )
                        )

                        self.filter_records("archive", "All")
                if data.state_info.last_state == State.STAGNATED:
                    trigger_price = data.config.symbol_info.adjust_price(
                        (
                            (1 + (data.config.order_trigger / 100))
                            * data.config.price_high
                            if data.config.side.value == PositionSide.LONG.value
                            else (1 - (data.config.order_trigger / 100))
                            * data.config.price_low
                        )
                    )

                    self.active_records.remove(position)
                    idle_position = IdlePosition(
                        open_time=data.config.open_time,
                        system_id=data.config.system_id,
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.config.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=f"{data.config.order_trigger},({trigger_price})",
                        state=str(data.state_info.last_state),
                        completeness=str(data.completeness),
                    )
                    self.idle_records.append(idle_position.to_dict())
                    logger.info("Price level stagnated: %s", idle_position)
                    self.filter_records("idle", "All")
        self.filter_records("active", "All")

    def update_idle_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.idle_records:
            if position["system_id"] == data.config.system_id:
                position["stagnation_counter"] = str(data.state_info.stagnation_counter)
                position["stagnation_limit"] = str(data.stagnation_limit)
                position["completeness"] = str(data.completeness)
                position["state"] = str(data.state_info.last_state)
                logger.info("Data state: %s", data.state_info.last_state)
                if data.state_info.last_state == State.OPEN:
                    self.idle_records.remove(position)
                    cancel_price = data.config.symbol_info.adjust_price(
                        (
                            (1 + (2 * data.config.order_trigger / 100))
                            * data.config.price_high
                            if data.config.side.value == PositionSide.LONG.value
                            else (1 - (2 * data.config.order_trigger / 100))
                            * data.config.price_low
                        )
                    )
                    active_position = ActivePosition(
                        open_time=data.config.open_time,
                        system_id=data.config.system_id,
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.config.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_cancel=f"{2 * data.config.order_trigger},({cancel_price})",
                        stagnation=f"{data.state_info.stagnation_counter}/{data.stagnation_limit}",
                        completeness=str(data.completeness),
                        state=str(data.state_info.last_state),
                    )
                    self.active_records.append(active_position.to_dict())
                    logger.info("Activating price level: %s", active_position)
                if data.state_info.last_state == State.CLOSED:
                    data.config.close_time = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    self.idle_records.remove(position)
                    archived_position = ArchivedPosition(
                        open_time=data.config.open_time,
                        close_time=data.config.close_time,
                        system_id=data.config.system_id,
                        symbol=data.config.symbol_info.symbol,
                        side=str(data.config.side.value),
                        mode=str(data.config.mode.value),
                        price_low=str(data.config.price_low),
                        price_high=str(data.config.price_high),
                        budget=str(data.config.budget),
                        order_trigger=str(data.config.order_trigger),
                        completeness=str(data.completeness),
                    )
                    self.archive_records.append(archived_position.to_dict())
                    logger.info("Archiving price level: %s", archived_position)

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
