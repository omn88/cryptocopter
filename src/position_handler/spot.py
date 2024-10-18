import datetime
import queue
from typing import List, Optional
import logging
from binance.enums import ORDER_STATUS_CANCELED
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, PositionSide
from src.common.identifiers.spot import (
    ExecutionReport,
    HPConfig,
    State,
    StateInfo,
    Order,
)
from src.gui.identifiers.spot import PositionData
from src.order_handler.spot import OrderHandler


logger = logging.getLogger("pos_handler")


class PositionHandler:
    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        config: HPConfig,
        state_info: StateInfo,
        ui_queue: queue.Queue,
        db: Database,
    ):
        self.config = config
        self.state_info = state_info
        self.strategy_logger = strategy_logger
        self.db = db
        self.ui_queue: queue.Queue = ui_queue
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
        )
        self.orders: List[Order] = []

    async def open_position(self, config: HPConfig, state_info: StateInfo) -> None:
        self.order_handler.prepare_orders(config=config, state_info=state_info)
        self.orders = await self.order_handler.create_orders(
            side=state_info.side, orders=self.orders, symbol_info=config.symbol_info
        )
        self.state_info.next_monitor_time = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        self.state_info.state = (
            State.BUYING if self.state_info.side == PositionSide.LONG else State.SELLING
        )

        position_data = PositionData(
            config=self.config,
            state_info=self.state_info,
            completeness=round(
                sum(order.realized_quantity for order in self.orders)
                / sum(order.quantity for order in self.orders),
                2,
            ),
        )

        logger.info("Going to send position data: %s", position_data)

        self.ui_queue.put_nowait(position_data)

        for order in self.orders:
            self.db.run_db_task(
                self.db.insert_order(hp_id=self.config.hp_id, order=order)
            )
        self.db.run_db_task(
            self.db.update_price_level(
                self.config,
                state_info=self.state_info,
            )
        )

        logger.info("Position opened successfully.")

    async def cancel_position(self) -> None:
        logger.info(
            "Start canceling position: %s %s, system id: %s",
            self.config.symbol_info.symbol,
            self.state_info.side,
            self.config.hp_id,
        )

        self.orders = await self.order_handler.cancel_remaining_limit_orders(
            symbol=self.config.symbol_info.symbol,
            orders=self.orders,
        )
        for order in self.orders:
            if order.status == ORDER_STATUS_CANCELED:
                self.db.run_db_task(
                    self.db.update_order(
                        price=order.price,
                        quantity=order.quantity,
                        quantity_stable=order.quantity_stable,
                        realized_quantity=order.realized_quantity,
                        time_in_force=order.time_in_force,
                        status=order.status,
                        order_type=order.order_type,
                        order_id=order.order_id,
                        hp_id=str(self.config.hp_id),
                    )
                )

        self.db.run_db_task(
            self.db.update_price_level(config=self.config, state_info=self.state_info)
        )

        self.ui_queue.put_nowait(
            PositionData(
                config=self.config,
                state_info=self.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.orders)
                    / sum(order.quantity for order in self.orders),
                    2,
                ),
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
                logger.info("Order: %s partially filled", order.order_id)

        self.state_info.stagnation_counter = 0
        self.state_info.next_monitor_time = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        self.db.run_db_task(
            self.db.update_price_level(config=self.config, state_info=self.state_info)
        )

        logger.info("Stagnation counter reset for system: %s", self.config.hp_id)

        self.ui_queue.put_nowait(
            PositionData(
                config=self.config,
                state_info=self.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.orders)
                    / sum(order.quantity for order in self.orders),
                    2,
                ),
            )
        )
        self.db.run_db_task(
            self.db.update_order(
                order_id=execution_report.order_id,
                hp_id=str(self.config.hp_id),
                quantity=execution_report.quantity,
                realized_quantity=execution_report.cumulative_filled_quantity,
                status=execution_report.current_order_status,
                price=execution_report.price,
                time_in_force=execution_report.time_in_force,
                order_type=execution_report.order_type,
                quantity_stable=self.orders[0].quantity_stable,
            )
        )

    async def handle_order_filled(self, execution_report: ExecutionReport) -> None:
        self.state_info.stagnation_counter = 0
        self.state_info.next_monitor_time = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        self.db.run_db_task(
            self.db.update_price_level(config=self.config, state_info=self.state_info)
        )
        for order in self.orders:
            if execution_report.order_id == order.order_id:
                order.status = execution_report.current_order_status
                order.price = execution_report.price
                order.realized_quantity = execution_report.cumulative_filled_quantity
                logger.info(
                    "Order: %s filled, symbol: %s, price: %s",
                    order.order_id,
                    execution_report.symbol,
                    order.price,
                )

        logger.info("Stagnation counter reset for system: %s", self.config.hp_id)
        self.ui_queue.put_nowait(
            PositionData(
                config=self.config,
                state_info=self.state_info,
                completeness=round(
                    sum(order.realized_quantity for order in self.orders)
                    / sum(order.quantity for order in self.orders),
                    2,
                ),
            )
        )

        self.db.run_db_task(
            self.db.update_order(
                order_id=execution_report.order_id,
                hp_id=str(self.config.hp_id),
                quantity=execution_report.quantity,
                realized_quantity=execution_report.cumulative_filled_quantity,
                status=execution_report.current_order_status,
                price=execution_report.price,
                time_in_force=execution_report.time_in_force,
                order_type=execution_report.order_type,
                quantity_stable=self.orders[0].quantity_stable,
            )
        )
