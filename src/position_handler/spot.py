import asyncio
import datetime
from typing import List

from binance.enums import ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import (
    BinanceClient,
    Order,
    PositionSide,
    PositionStatus,
)
from src.common.identifiers.spot import ExecutionReport, StrategyConfig
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.order_handler.spot import OrderHandler


class PositionHandler:
    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        config: StrategyConfig,
        gui_handler: asyncio.Queue,
        db: Database,
    ):
        self.config = config
        self.strategy_logger = strategy_logger
        self.db = db
        self.gui_handler: asyncio.Queue = gui_handler
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
        )
        self.orders: List[Order] = self.order_handler.prepare_orders(
            budget=config.budget,
            price_low=config.price_low,
            price_high=config.price_high,
            min_notional=self.config.symbol_info.min_notional,
            mode=self.config.mode,
            side=self.config.side,
        )

        self.stagnation_counter: int = 0
        self.prev_orders: List[Order] = []
        self.next_monitor_position_time: datetime.datetime = datetime.datetime.now()

    async def open_position(
        self,
        side: PositionSide,
        symbol_info: SymbolInfo,
    ) -> None:
        self.orders = await self.order_handler.create_orders(
            side=side, orders=self.orders, symbol_info=symbol_info
        )
        self.next_monitor_position_time = datetime.datetime.now() + datetime.timedelta(
            hours=1
        )

        self.config.status = PositionStatus.OPEN
        await self.gui_handler.put(
            PositionData(
                system_id=self.config.system_id,
                price_high=self.config.price_high,
                price_low=self.config.price_low,
                side=self.config.side,
                symbol=self.config.symbol_info.symbol,
                order_trigger=self.config.order_trigger,
                budget=self.config.budget,
                status=self.config.status,
                orders_opened=len(self.orders),
                orders_filled=0,
                orders_total=len(self.orders),
            )
        )

        for order in self.orders:
            await self.db.insert_order(
                price_level_id=self.config.system_id, order=order
            )
        await self.db.update_price_level(
            system_id=self.config.system_id,
            side=self.config.side,
            price_low=self.config.price_low,
            price_high=self.config.price_high,
            order_trigger=self.config.order_trigger,
            budget=self.config.budget,
            status=self.config.status,
            symbol=self.config.symbol_info.symbol,
        )

        self.strategy_logger.debug("Position opened successfully.")

    async def cancel_position(self) -> None:
        self.strategy_logger.debug("Enter cancel position")

        self.orders = await self.order_handler.cancel_remaining_limit_orders(
            symbol=self.config.symbol_info.symbol,
            orders=self.orders,
        )
        self.config.status = PositionStatus.STAGNATED
        for order in self.orders:
            if order.status == ORDER_STATUS_CANCELED:
                await self.db.update_order(
                    price=order.price,
                    quantity=order.quantity,
                    quantity_stable=order.quantity_stable,
                    realized_quantity=order.realized_quantity,
                    time_in_force=order.time_in_force,
                    status=order.status,
                    order_type=order.order_type,
                    order_id=order.order_id,
                    price_level_id=self.config.system_id,
                )

        await self.db.update_price_level(
            system_id=self.config.system_id,
            symbol=self.config.symbol_info.symbol,
            side=self.config.side,
            price_low=self.config.price_low,
            price_high=self.config.price_high,
            order_trigger=self.config.order_trigger,
            budget=self.config.budget,
            status=self.config.status,
        )

        orders_filled = len(
            [order for order in self.orders if order.status == ORDER_STATUS_FILLED]
        )

        await self.gui_handler.put(
            PositionData(
                system_id=self.config.system_id,
                price_high=self.config.price_high,
                price_low=self.config.price_low,
                side=self.config.side,
                symbol=self.config.symbol_info.symbol,
                order_trigger=self.config.order_trigger,
                budget=self.config.budget,
                status=self.config.status,
                orders_opened=0,
                orders_filled=orders_filled,
                orders_total=len(self.orders),
            )
        )

    async def handle_order_partially_filled(
        self, execution_report: ExecutionReport
    ) -> None:
        for order in self.orders:
            if execution_report.order_id == order.order_id:
                order.status = execution_report.current_order_status
                order.realized_quantity = execution_report.cumulative_filled_quantity
                order.quantity_stable -= (
                    execution_report.price * execution_report.last_executed_quantity
                )
                self.strategy_logger.info("Order: %s partially filled", order.order_id)

        self.stagnation_counter = 0
        self.next_monitor_position_time = datetime.datetime.now() + datetime.timedelta(
            hours=1
        )

        orders_opened = len(
            [order for order in self.orders if order.status != ORDER_STATUS_FILLED]
        )

        orders_filled = len(
            [order for order in self.orders if order.status == ORDER_STATUS_FILLED]
        )

        await self.gui_handler.put(
            PositionData(
                symbol=self.config.symbol_info.symbol,
                side=self.config.side,
                order_trigger=self.config.order_trigger,
                budget=self.config.budget,
                price_low=self.config.price_low,
                price_high=self.config.price_high,
                system_id=self.config.system_id,
                status=self.config.status,
                orders_opened=orders_opened,
                orders_filled=orders_filled,
                orders_total=orders_opened + orders_filled,
            )
        )
        self.strategy_logger.info("status: %s", execution_report.current_order_status)
        await self.db.update_order(
            order_id=execution_report.order_id,
            price_level_id=self.config.system_id,
            quantity=execution_report.quantity,
            realized_quantity=execution_report.cumulative_filled_quantity,
            status=execution_report.current_order_status,
            price=execution_report.price,
            time_in_force=execution_report.time_in_force,
            order_type=execution_report.order_type,
            quantity_stable=self.orders[0].quantity_stable,
        )

    async def handle_order_filled(self, execution_report: ExecutionReport) -> None:
        for order in self.orders:
            if execution_report.order_id == order.order_id:
                order.status = execution_report.current_order_status
                order.price = execution_report.price
                order.quantity = execution_report.quantity
                order.realized_quantity = execution_report.cumulative_filled_quantity
                self.strategy_logger.info("Order: %s filled", order.order_id)

        self.stagnation_counter = 0
        self.next_monitor_position_time = datetime.datetime.now() + datetime.timedelta(
            hours=1
        )
        self.strategy_logger.info(
            "Reseting stagation counter, current value: %s", self.stagnation_counter
        )
        orders_opened = len(
            [order for order in self.orders if order.status != ORDER_STATUS_FILLED]
        )

        orders_filled = len(
            [order for order in self.orders if order.status == ORDER_STATUS_FILLED]
        )

        await self.gui_handler.put(
            PositionData(
                system_id=self.config.system_id,
                symbol=self.config.symbol_info.symbol,
                side=self.config.side,
                order_trigger=self.config.order_trigger,
                budget=self.config.budget,
                price_low=self.config.price_low,
                price_high=self.config.price_high,
                status=self.config.status,
                orders_opened=orders_opened,
                orders_filled=orders_filled,
                orders_total=orders_opened + orders_filled,
            )
        )

        await self.db.update_order(
            order_id=execution_report.order_id,
            price_level_id=self.config.system_id,
            quantity=execution_report.quantity,
            realized_quantity=execution_report.cumulative_filled_quantity,
            status=execution_report.current_order_status,
            price=execution_report.price,
            time_in_force=execution_report.time_in_force,
            order_type=execution_report.order_type,
            quantity_stable=self.orders[0].quantity_stable,
        )
