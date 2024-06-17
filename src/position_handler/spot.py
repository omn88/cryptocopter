import asyncio
import datetime
from typing import List

from binance.enums import ORDER_STATUS_FILLED
from logging_config import StrategyLogger
from src.common.identifiers.common import (
    BinanceClient,
    Order,
    PositionSide,
    PositionStatus,
)
from src.common.identifiers.spot import ExecutionReport, State, StrategyConfig
from src.gui.identifiers.spot import PositionData
from src.order_handler.spot import OrderHandler


class PositionHandler:
    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        config: StrategyConfig,
        gui_handler: asyncio.Queue,
    ):
        self.config = config
        self.strategy_logger = strategy_logger
        self.gui_handler: asyncio.Queue = gui_handler
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
        )
        self.orders: List[Order] = self.order_handler.prepare_orders(
            budget=config.budget,
            price_low=config.price_low,
            price_high=config.price_high,
            min_notional=self.order_handler.symbol_config.min_notional,
        )

        self.stagnation_counter: int = 0
        self.prev_orders: List[Order] = []
        self.next_monitor_position_time: datetime.datetime = datetime.datetime.now()

        self.state: State = State.NEW
        self.status: PositionStatus = PositionStatus.NEW

    async def open_position(
        self,
        side: PositionSide,
        symbol: str,
    ) -> None:
        self.orders = await self.order_handler.create_orders(
            side=side, orders=self.orders, symbol=symbol
        )
        self.next_monitor_position_time = datetime.datetime.now() + datetime.timedelta(
            hours=1
        )

        self.state = State.OPEN
        self.status = PositionStatus.OPEN
        await self.gui_handler.put(
            PositionData(
                system_id=self.config.system_id,
                status=self.status,
                orders_opened=len(self.orders),
                orders_filled=0,
                orders_total=len(self.orders),
            )
        )

        self.strategy_logger.debug("Position opened successfully.")

    async def cancel_position(self) -> None:
        self.strategy_logger.debug("Enter cancel position")

        self.orders = await self.order_handler.cancel_remaining_limit_orders(
            symbol=self.config.symbol,
            orders=self.orders,
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
        orders_opened = len(
            [order for order in self.orders if order.status != ORDER_STATUS_FILLED]
        )

        orders_filled = len(
            [order for order in self.orders if order.status == ORDER_STATUS_FILLED]
        )

        await self.gui_handler.put(
            PositionData(
                system_id=self.config.system_id,
                status=PositionStatus.OPEN,
                orders_opened=orders_opened,
                orders_filled=orders_filled,
                orders_total=orders_opened + orders_filled,
            )
        )
