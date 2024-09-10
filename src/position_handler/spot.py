import datetime
import queue
from typing import List, Optional
import logging
from binance.enums import ORDER_STATUS_CANCELED
from logging_config import StrategyLogger
from src.common.database import Database
from src.common.identifiers.common import BinanceClient, PositionSide
from src.common.identifiers.spot import ExecutionReport, State, StrategyConfig, Order
from src.common.symbol_info import SymbolInfo
from src.gui.identifiers.spot import PositionData
from src.order_handler.spot import OrderHandler


logger = logging.getLogger("pos_handler")


class PositionHandler:
    def __init__(
        self,
        client: BinanceClient,
        strategy_logger: StrategyLogger,
        config: StrategyConfig,
        ui_queue: queue.Queue,
        db: Database,
        last_state: Optional[State] = None,
    ):
        self.config = config
        self.strategy_logger = strategy_logger
        self.db = db
        self.ui_queue: queue.Queue = ui_queue
        self.order_handler = OrderHandler(
            client=client,
            strategy_logger=strategy_logger,
        )
        self.orders: List[Order] = self.order_handler.prepare_orders(config=config)
        self.last_state: Optional[State] = last_state
        self.stagnation_counter: int = 0
        self.prev_orders: List[Order] = []
        self.next_monitor_position_time: str = datetime.datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    async def open_position(
        self,
        side: PositionSide,
        symbol_info: SymbolInfo,
    ) -> None:
        self.orders = await self.order_handler.create_orders(
            side=side, orders=self.orders, symbol_info=symbol_info
        )
        self.next_monitor_position_time = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")

        state = State.OPEN

        self.ui_queue.put(
            PositionData(
                config=self.config,
                state=state,
                stagnation_counter=self.stagnation_counter,
                completeness=round(
                    sum(order.realized_quantity for order in self.orders)
                    / sum(order.quantity for order in self.orders),
                    2,
                ),
            )
        )

        for order in self.orders:
            self.db.run_db_task(
                self.db.insert_order(price_level_id=self.config.system_id, order=order)
            )
        self.db.run_db_task(
            self.db.update_price_level(
                self.config,
                state=state,
                stagnation_counter=self.stagnation_counter,
                next_monitor_time=self.next_monitor_position_time,
            )
        )

        logger.debug("Position opened successfully.")

    async def cancel_position(self, state: State) -> None:
        logger.info(
            "Start canceling position: %s %s, system id: %s",
            self.config.symbol_info.symbol,
            self.config.side,
            self.config.system_id,
        )

        self.stagnation_counter = 0

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
                        price_level_id=self.config.system_id,
                    )
                )

        self.db.run_db_task(
            self.db.update_price_level(
                config=self.config,
                state=state,
                stagnation_counter=self.stagnation_counter,
                next_monitor_time=self.next_monitor_position_time,
            )
        )

        self.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.stagnation_counter,
                completeness=round(
                    sum(order.realized_quantity for order in self.orders)
                    / sum(order.quantity for order in self.orders),
                    2,
                ),
                state=state,
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

        self.stagnation_counter = 0
        self.next_monitor_position_time = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.config,
                state=State.OPEN,
                stagnation_counter=self.stagnation_counter,
                next_monitor_time=self.next_monitor_position_time,
            )
        )

        logger.info("Stagnation counter reset for system: %s", self.config.system_id)

        self.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.stagnation_counter,
                completeness=round(
                    sum(order.realized_quantity for order in self.orders)
                    / sum(order.quantity for order in self.orders),
                    2,
                ),
                state=State.OPEN,
            )
        )
        self.db.run_db_task(
            self.db.update_order(
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
        )

    async def handle_order_filled(self, execution_report: ExecutionReport) -> None:
        self.stagnation_counter = 0
        self.next_monitor_position_time = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).strftime("%Y-%m-%d %H:%M:%S")
        self.db.run_db_task(
            self.db.update_price_level(
                config=self.config,
                state=State.OPEN,
                stagnation_counter=self.stagnation_counter,
                next_monitor_time=self.next_monitor_position_time,
            )
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

        logger.info("Stagnation counter reset for system: %s", self.config.system_id)
        self.ui_queue.put(
            PositionData(
                config=self.config,
                stagnation_counter=self.stagnation_counter,
                completeness=round(
                    sum(order.realized_quantity for order in self.orders)
                    / sum(order.quantity for order in self.orders),
                    2,
                ),
                state=State.OPEN,
            )
        )

        self.db.run_db_task(
            self.db.update_order(
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
        )
