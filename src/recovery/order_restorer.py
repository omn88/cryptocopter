"""
Order restorer for recovering trading orders from database after system restart.

Handles fetching orders from database, aggregating duplicates, and verifying
with the exchange to ensure order states are current.
"""

import logging
import queue
from collections import defaultdict
from typing import List, Optional

from binance.enums import ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED, ORDER_STATUS_NEW

from src.common.client import BinanceClient
from src.common.identifiers import (
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPSellConfig,
    Order,
    PositionSide,
)
from src.strategies.hp_manager.position_buy import HPPositionBuy
from src.database.trading_database import Database


logger = logging.getLogger("OrderRestorer")


class OrderRestorer:
    """Restores trading orders from database and verifies with exchange."""

    def __init__(self, database: Database):
        self.db = database

    async def restore_buy_orders(
        self,
        buy_position: HPPositionBuy,
        worker_queue: queue.Queue,
        client: BinanceClient,
    ) -> List[Order]:
        """
        Restore buy orders from database, aggregating duplicates and verifying with exchange.

        Args:
            buy_position: The buy position whose orders to restore
            worker_queue: Queue for sending execution reports
            client: Binance API client for verification

        Returns:
            List of restored Order objects
        """
        buy_config = buy_position.data.config

        # Fetch all orders for this HP and side from database
        orders = await self.db.fetch_orders_for_price_level(
            hp_id=buy_config.hp_id, side=PositionSide.LONG.value
        )

        if not orders:
            buy_position.prepare_order()
            return [buy_position.buy_order] if buy_position.buy_order else []

        # Aggregate orders by (price, quantity) to handle duplicates
        restored_orders = self._aggregate_orders(orders, buy_config)

        # Verify open orders with exchange
        await self._verify_orders_with_exchange(
            restored_orders, buy_config.symbol.name, worker_queue, client
        )

        return restored_orders

    async def restore_sell_orders(
        self,
        sell_config: HPSellConfig,
        worker_queue: queue.Queue,
        client: BinanceClient,
    ) -> Optional[Order]:
        """
        Restore sell order from database and verify with exchange.

        Args:
            sell_config: The sell configuration whose order to restore
            worker_queue: Queue for sending execution reports
            client: Binance API client for verification

        Returns:
            Restored Order object or None if no orders found
        """
        # Fetch orders for this HP and side from database
        orders = await self.db.fetch_orders_for_price_level(
            hp_id=sell_config.hp_id,
            side=PositionSide.SHORT.value,
        )

        if not orders:
            return None

        # Select current order (prefer NEW status if multiple exist)
        current_order = self._select_current_sell_order(orders)

        # Convert to trading Order object
        trading_order = Order(
            order_id=current_order["order_id"],
            quantity=current_order["quantity"],
            precision=sell_config.symbol.precision,
            price_precision=sell_config.symbol.price_precision,
            price=current_order["price"],
            quantity_stable=current_order["quantity_stable"],
            realized_quantity=current_order["realized_quantity"],
            status=(
                current_order["status"].value
                if hasattr(current_order["status"], "value")
                else current_order["status"]
            ),
        )  # Verify with exchange if not filled or canceled
        if current_order["status"] not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
            await self._verify_single_order_with_exchange(
                trading_order,
                current_order,
                sell_config.symbol.name,
                worker_queue,
                client,
            )

        return trading_order

    def _aggregate_orders(
        self, orders: List[dict], buy_config: HPBuyConfig
    ) -> List[Order]:
        """
        Aggregate duplicate orders by (price, quantity), summing realized quantities.

        Returns list of Order objects with aggregated data.
        """
        grouped_orders = defaultdict(list)
        for order_dict in orders:
            key = (order_dict["price"], order_dict["quantity"])
            grouped_orders[key].append(order_dict)

        restored_orders: List[Order] = []
        for (_, _), order_dicts in grouped_orders.items():
            # Aggregate realized_quantity from all orders for this price level
            total_realized = sum(o["realized_quantity"] for o in order_dicts)

            # Find the latest open order, else the latest order overall
            open_orders = [
                o
                for o in order_dicts
                if o["status"] not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]
            ]
            latest_order = (
                max(open_orders, key=lambda o: o.get("order_id", 0))
                if open_orders
                else max(order_dicts, key=lambda o: o.get("order_id", 0))
            )

            trading_order = Order(
                order_id=latest_order["order_id"],
                quantity=latest_order["quantity"],
                precision=buy_config.symbol.precision,
                price_precision=buy_config.symbol.price_precision,
                price=latest_order["price"],
                quantity_stable=latest_order["quantity_stable"],
                realized_quantity=total_realized,
                status=(
                    latest_order["status"].value
                    if hasattr(latest_order["status"], "value")
                    else latest_order["status"]
                ),
            )
            restored_orders.append(trading_order)

        return restored_orders

    def _select_current_sell_order(self, orders: List[dict]) -> dict:
        """
        Select the current active sell order from list of orders.
        Prefers NEW status if multiple orders exist.
        """
        if len(orders) == 1:
            return orders[0]

        # If multiple orders, prefer NEW status
        for order in orders:
            if order["status"] == ORDER_STATUS_NEW:
                return order

        # Fallback to first order
        return orders[0]

    async def _verify_orders_with_exchange(
        self,
        orders: List[Order],
        symbol_name: str,
        worker_queue: queue.Queue,
        client: BinanceClient,
    ) -> None:
        """
        Verify open orders with exchange and send execution reports for any changes.
        """
        for order in orders:
            if order.status in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
                continue

            try:
                # Retrieve the latest order information from the API
                resp = await client.get_order(
                    symbol=symbol_name,
                    orderId=order.order_id,
                )
                latest_status = resp["status"]
                latest_realized_quantity = float(resp["executedQty"])

                # Check if status or realized quantity has changed
                if (
                    latest_status != order.status
                    or latest_realized_quantity != order.realized_quantity
                ):
                    ex_report = ExecutionReport(
                        symbol=symbol_name,
                        quantity=order.quantity,
                        price=order.price,
                        current_order_status=latest_status,
                        order_id=order.order_id,
                        cumulative_filled_quantity=latest_realized_quantity,
                    )
                    worker_queue.put_nowait(
                        Event(
                            name=EventName.EXECUTION_REPORT,
                            content=ex_report,
                        )
                    )
                    logger.info(
                        "Order %s modified, execution report sent",
                        order.order_id,
                    )
            except Exception as e:
                logger.error(
                    "Failed to verify order %s with exchange: %s", order.order_id, e
                )

    async def _verify_single_order_with_exchange(
        self,
        trading_order: Order,
        db_order: dict,
        symbol_name: str,
        worker_queue: queue.Queue,
        client: BinanceClient,
    ) -> None:
        """
        Verify a single order with exchange and send execution report if changed.
        """
        try:
            # Retrieve the latest order information from the API
            resp = await client.get_order(
                symbol=symbol_name,
                orderId=db_order["order_id"],
            )
            latest_status = resp["status"]
            latest_realized_quantity = float(resp["executedQty"])

            # Check if status or realized quantity has changed
            if (
                latest_status != db_order["status"]
                or latest_realized_quantity != db_order["realized_quantity"]
            ):
                ex_report = ExecutionReport(
                    symbol=symbol_name,
                    quantity=db_order["quantity"],
                    price=db_order["price"],
                    current_order_status=latest_status,
                    order_id=db_order["order_id"],
                    cumulative_filled_quantity=latest_realized_quantity,
                )
                worker_queue.put_nowait(
                    Event(
                        name=EventName.EXECUTION_REPORT,
                        content=ex_report,
                    )
                )
                logger.info(
                    "Order %s modified, execution report sent",
                    db_order["order_id"],
                )
        except Exception as e:
            logger.error(
                "Failed to verify order %s with exchange: %s", db_order["order_id"], e
            )
