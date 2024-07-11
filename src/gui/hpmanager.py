import asyncio
from typing import Dict, List, Optional
import uuid
from binance import BinanceSocketManager
from kivy.properties import (
    ListProperty,
    NumericProperty,
    ObjectProperty,
    StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.dropdown import DropDown
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import (
    BinanceClient,
    Order,
    PositionSide,
    PositionStatus,
)
from src.common.identifiers.spot import (
    AccountPosition,
    Event,
    EventName,
    StrategyConfig,
)
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.futures import AccountData
from src.gui.identifiers.spot import PositionData
from src.gui.searchable_drop_down import SearchableDropDown
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
    symbols = ListProperty()

    def __init__(
        self,
        client: BinanceClient,
        db: Database,
        strategy_logger: StrategyLogger,
        strategy_id: str,
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
        self.strategy_executor = StrategyExecutor(
            client=client, logger=strategy_logger, gui_handler=self.gui_handler, db=db
        )
        self.symbols = [symbol for symbol, info in self.symbols_info.items()]
        asyncio.create_task(self.strategy_executor.run())
        asyncio.create_task(self.update_ui())

        # Create the SearchableDropDown instance with the client
        self.symbol_input = SearchableDropDown(client=self.client, options=self.symbols)
        # Add it to the layout where needed
        self.ids.symbol_container.add_widget(self.symbol_input)

    def update_label(self, instance, value):
        self.selected_label.text = value

    def trigger_add_record(self, *args):
        asyncio.create_task(self.add_record(*args))

    async def add_record(
        self,
        symbol,
        side,
        price_low,
        price_high,
        budget,
        order_trigger,
        last_known_status=None,
        system_id: Optional[str] = None,
    ):
        if system_id is None:
            system_id = str(uuid.uuid4())

        config = StrategyConfig(
            system_id=system_id,
            symbol_info=self.symbols_info[symbol],
            side=PositionSide.LONG
            if side == PositionSide.LONG.value
            else PositionSide.SHORT,
            price_low=float(price_low),
            price_high=float(price_high),
            budget=float(budget),
            order_trigger=float(order_trigger),
            status=last_known_status,
        )
        self.strategy_logger.info(f"Adding new record with config: {config}")
        await self.strategy_executor.config_queue.put(config)

        if (
            not last_known_status
        ):  # inserting level only if there is no last known status, recovery will
            status = PositionStatus.NEW

            await self.gui_handler.put(
                PositionData(
                    system_id=config.system_id,
                    symbol=config.symbol_info.symbol,
                    side=config.side,
                    price_low=config.price_low,
                    price_high=config.price_high,
                    budget=config.budget,
                    order_trigger=config.order_trigger,
                    orders_opened=0,
                    orders_filled=0,
                    orders_total=0,
                    status=status,
                )
            )
            await self.db.insert_price_level(config=config)

        self.filter_records(tab="idle", symbol_filter="All")

    def trigger_remove_record(
        self,
        system_id,
        symbol,
        side,
        price_low,
        price_high,
        budget,
        order_trigger,
        orders_opened,
        orders_total,
        orders_filled,
        *args,
    ):
        asyncio.create_task(
            self.remove_record(
                system_id=system_id,
                symbol=symbol,
                side=side,
                price_high=price_high,
                price_low=price_low,
                budget=budget,
                order_trigger=order_trigger,
                orders_filled=orders_filled,
                orders_total=orders_total,
                orders_opened=orders_opened,
            )
        )

    async def remove_record(
        self,
        system_id,
        symbol,
        side,
        price_low,
        price_high,
        budget,
        order_trigger,
        orders_opened,
        orders_total,
        orders_filled,
    ):
        status = PositionStatus.CLOSED

        side = PositionSide.LONG if side == "BUY" else PositionSide.SHORT

        # Send a command to the strategy executor to stop the trading process
        await self.strategy_executor.remove_record(system_id=system_id)

        # Update GUI asynchronously
        await self.gui_handler.put(
            PositionData(
                system_id=system_id,
                symbol=symbol,
                side=side,
                price_low=price_low,
                price_high=price_high,
                budget=budget,
                order_trigger=order_trigger,
                orders_opened=orders_opened,
                orders_total=orders_total,
                orders_filled=orders_filled,
                status=status,
            )
        )

        await self.db.update_price_level(
            system_id=system_id,
            side=side,
            price_low=price_low,
            price_high=price_high,
            order_trigger=order_trigger,
            budget=budget,
            status=status,
            symbol=symbol,
        )

    async def update_ui(self):
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
                    if data.status == PositionStatus.OPEN.value:
                        self.strategy_logger.logger.debug(
                            "Recovering position to active tab in GUI: %s", data
                        )
                        self.recovery_to_active(data=data)

                elif any(
                    record["system_id"] == data.system_id
                    for record in self.active_records
                ):
                    self.strategy_logger.debug(
                        "Record %s found in active records", data.system_id
                    )
                    self.update_active_position(data=data)
                elif any(
                    record["system_id"] == data.system_id
                    for record in self.idle_records
                ):
                    self.strategy_logger.debug(
                        "Record %s found in idle records", data.system_id
                    )
                    self.update_idle_position(data=data)
                else:
                    self.add_new_position(data=data)
                self.strategy_logger.debug(
                    "Records active:\n%s\nIdle\n%s\nArchive\n%s",
                    self.active_records,
                    self.idle_records,
                    self.archive_records,
                )

    def add_new_position(self, data: PositionData):
        new_position = {
            "system_id": data.system_id,
            "symbol": data.symbol,
            "side": str(data.side.value),
            "price_low": str(data.price_low),
            "price_high": str(data.price_high),
            "budget": str(data.budget),
            "order_trigger": str(data.order_trigger),
            "orders_opened": str(data.orders_opened),
            "orders_total": str(data.orders_total),
            "orders_filled": str(data.orders_filled),
            "status": str(data.status),
        }

        self.idle_records.append(new_position)
        self.filter_records("idle", "All")

    def recovery_to_active(self, data: PositionData):
        new_position = {
            "system_id": data.system_id,
            "symbol": data.symbol,
            "side": str(data.side.value),
            "price_low": str(data.price_low),
            "price_high": str(data.price_high),
            "budget": str(data.budget),
            "order_trigger": str(data.order_trigger),
            "orders_opened": str(data.orders_opened),
            "orders_total": str(data.orders_total),
            "orders_filled": str(data.orders_filled),
            "status": str(data.status),
        }

        self.active_records.append(new_position)
        self.filter_records("active", "All")

    def update_active_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.active_records:
            if position["system_id"] == data.system_id:
                position.update(
                    {
                        "orders_opened": str(data.orders_opened),
                        "orders_total": str(data.orders_total),
                        "orders_filled": str(data.orders_filled),
                        "status": str(data.status),
                    }
                )
                if data.status == PositionStatus.CLOSED:
                    self.active_records.remove(position)
                    self.archive_records.append(position)
                    self.strategy_logger.debug("Archiving price level: %s", position)

        self.filter_records("active", "All")
        self.filter_records("archive", "All")

    def update_idle_position(
        self,
        data: PositionData,
    ) -> None:
        for position in self.idle_records:
            if position["system_id"] == data.system_id:
                self.strategy_logger.debug("Will update position")
                position.update(
                    {
                        "orders_opened": str(data.orders_opened),
                        "orders_total": str(data.orders_total),
                        "orders_filled": str(data.orders_filled),
                        "status": str(data.status),
                    }
                )
                if data.status == PositionStatus.OPEN:
                    self.idle_records.remove(position)
                    self.active_records.append(position)
                    self.strategy_logger.debug("Activating price level: %s", position)
                if data.status == PositionStatus.CLOSED:
                    self.idle_records.remove(position)
                    self.archive_records.append(position)
                    self.strategy_logger.debug("Archiving price level: %s", position)

        self.filter_records("idle", "All")
        self.filter_records("active", "All")
        self.filter_records("archive", "All")

    def filter_records(self, tab, symbol_filter):
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
