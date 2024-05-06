import asyncio
from typing import Dict, List
from binance import BinanceSocketManager
from kivy.properties import ListProperty, NumericProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from logging_config import StrategyLogger
from src.common.identifiers.common import (
    BinanceClient,
    Event,
    EventName,
    PositionSide,
    PositionStatus,
)
from src.common.identifiers.spot import StrategyConfig
from src.gui.gui_handler.spot import GuiHandler
from src.gui.identifiers.futures import AccountData
from src.gui.identifiers.spot import PositionData
from src.workers.strategy_executor import StrategyExecutor


class CoinSniper(BoxLayout):
    order_count = NumericProperty(0)
    position_count = NumericProperty(0)
    log_display = ObjectProperty(None)
    active_records: List[Dict] = ListProperty([])
    closed_records: List[Dict] = ListProperty([])

    def __init__(
        self,
        client: BinanceClient,
        gui_handler: GuiHandler,
        strategy_logger: StrategyLogger,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.client = client
        self.socket_manager = BinanceSocketManager(client=client)
        self.gui_handler = gui_handler
        self.strategy_logger = strategy_logger
        self.strategy_executor = StrategyExecutor(
            client=client, logger=strategy_logger, gui_handler=gui_handler
        )
        asyncio.create_task(self.strategy_executor.run())
        asyncio.create_task(self.update_ui())

    def trigger_add_record(self, *args):
        asyncio.create_task(self.add_record(*args))

    async def add_record(
        self, symbol, side, price_low, price_high, budget, order_trigger_buffer, mode
    ):
        config = StrategyConfig(
            symbol=symbol,
            side=PositionSide.LONG
            if side == PositionSide.LONG.value
            else PositionSide.SHORT,
            price_low=float(price_low),
            price_high=float(price_high),
            budget=float(budget),
            order_trigger_buffer=float(order_trigger_buffer),
        )
        self.strategy_logger.info(f"Adding new record with config: {config}")
        await self.strategy_executor.config_queue.put(config)
        await self.gui_handler.ui_queue.put(
            PositionData(
                symbol=config.symbol,
                side=config.side,
                price_low=config.price_low,
                price_high=config.price_high,
                budget=config.budget,
                order_trigger=order_trigger_buffer,
                orders_opened=0,
                orders_filled=0,
                orders_total=0,
                status=PositionStatus.NEW,
            )
        )

    def remove_record(self, index):
        # Assuming the data list is part of the root widget or accessible via ids
        active_records = self.root.ids.active_records_list.data
        if index < len(active_records):
            del active_records[index]
            # Update the RecycleView
            self.root.ids.active_records_list.refresh_from_data()

    async def update_ui(self):
        while True:
            if self.gui_handler.ui_queue.qsize() == 0:
                self.strategy_logger.debug("Awaiting new event")
                await asyncio.sleep(1)
                continue
            data = await self.gui_handler.ui_queue.get()
            if isinstance(data, Event) and data.name == EventName.SENTINEL:
                self.strategy_logger.info("Received sentinel event, exiting")
                return
            if isinstance(data, AccountData):
                pass  # handle account update
            if isinstance(data, PositionData):
                self.strategy_logger.info("Received position data: %s", data)
                updated_records = self.update_position(data=data)
                self.active_records = updated_records

    def update_position(self, data: PositionData):
        if any(pos["symbol"] == data.symbol for pos in self.active_records):
            return self.update_existing_position(data)
        elif data.status not in [PositionStatus.CLOSED, PositionStatus.CLOSING]:
            return self.add_new_position(data)
        return self.active_records

    def add_new_position(self, data: PositionData):
        self.position_count += 1
        new_position = {
            "symbol": data.symbol,
            "side": str(data.side.value),
            "price_low": str(data.price_low),
            "price_high": str(data.price_high),
            "budget": str(data.budget),
            "order_trigger_buffer": str(data.order_trigger),
            "orders_opened": str(data.orders_opened),
            "orders_total": str(data.orders_total),
            "orders_filled": str(data.orders_filled),
            "status": str(data.status.value),
        }
        self.active_records.append(new_position)
        self.strategy_logger.debug(f"Added new position: {new_position}")
        return self.active_records

    def update_existing_position(self, data: PositionData):
        for position in self.active_records:
            if position["symbol"] == data.symbol:
                position.update(
                    {
                        "orders_opened": str(data.orders_opened),
                        "orders_total": str(data.orders_total),
                        "orders_filled": str(data.orders_filled),
                        "status": str(data.status.value),
                    }
                )
                if data.status == PositionStatus.CLOSED:
                    self.active_records.remove(position)
                    self.closed_records.append(position)
                    self.position_count -= 1
                    self.strategy_logger.debug(f"Closed position moved: {position}")
        return self.active_records
