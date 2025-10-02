"""
Recovery service for restoring trading positions after system restart.

This module handles the complex task of restoring all active positions,
verifying their state with the exchange, and ensuring consistency.
"""

import asyncio
from collections import defaultdict
import logging
import queue
from typing import List, Dict, Optional, Tuple, Any

from binance.enums import ORDER_STATUS_FILLED, ORDER_STATUS_NEW, ORDER_STATUS_CANCELED

from src.broker import BrokerSpot
from src.common.helpers import determine_sell_strategy
from src.database.trading_database import Database
from src.identifiers import (
    BinanceClient,
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuy,
    HPSellConfig,
    HPSell,
    Order,
    SellPosition,
    SellType,
    StateInfo,
    State,
    PositionSide,
    Mode,
    SubscriptionInfo,
    SubscriptionTarget,
    SubscriptionType,
    UiState,
)
from src.common.symbol import Symbol
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell
from src.strategies.hp_manager import HpStrategy
from .models import (
    Position,
    Order as DatabaseOrder,
    PositionType,
    PositionStatus,
    TradeType,
    OrderStatus,
)  # Alias to avoid collision
from .exceptions import RecoveryError

logger = logging.getLogger("recovery_service")


class RecoveryService:
    """
    Service for recovering trading positions after system restart.

    The recovery process:
    1. Load all active positions from database
    2. Verify position states with exchange
    3. Reconstruct position objects for the trading system
    4. Handle any discrepancies or missing data
    """

    def __init__(
        self, symbols: Dict[str, Symbol], database: Database, broker: BrokerSpot
    ):
        self.db = database
        self.symbols = symbols
        self.broker = broker

    async def recover_all_positions(
        self, client: BinanceClient
    ) -> Tuple[List[HPBuy], List[HPSell]]:
        """
        Recover all active positions from the database.

        Returns:
            Tuple of (buy_positions, sell_positions) ready for the trading system
        """
        logger.info("Starting position recovery process...")

        try:
            # Load all active positions from database
            active_positions = await self.db.get_active_positions()
            logger.info("Found %d active positions in database", len(active_positions))

            logger.info("Active positions: %s", active_positions)

            # Verify positions with exchange
            verified_positions = await self._verify_positions_with_exchange(
                client, active_positions
            )

            # Group positions by type
            buy_positions = []
            sell_positions = []

            for position in verified_positions:
                if position.position_type == PositionType.BUY:
                    buy_data = await self._convert_to_buy_data(position)
                    if buy_data:
                        buy_positions.append(buy_data)
                else:
                    sell_data = await self._convert_to_sell_data(position)
                    if sell_data:
                        sell_positions.append(sell_data)

            logger.info(
                "Recovered %d buy positions and %d sell positions",
                len(buy_positions),
                len(sell_positions),
            )

            return buy_positions, sell_positions

        except Exception as e:
            raise RecoveryError(f"Failed to recover positions: {e}") from e

    async def restore_buy_position(
        self,
        buy_data: HPBuy,
        client: BinanceClient,
        ui_queue,
        balance,
        config_queue,
        price_resolver,
        portfolio_ui_queue=None,
    ) -> HpStrategy:
        """
        Restore a buy position from crash recovery with its existing HP ID and state.
        Uses the normal setup process but with restoration flag to preserve state.
        """
        logger.info("Restoring buy position: %s", buy_data.config.hp_id)

        worker_queue: queue.Queue = queue.Queue()
        assert client is not None

        logger.info("Creating HpStrategy for HP %s", buy_data.config.hp_id)
        strategy = HpStrategy(
            client=client,
            ui_queue=ui_queue,
            balance=balance,
            db=self.db,
            worker_queue=worker_queue,
            config_queue=config_queue,
            buy_position=HPPositionBuy(
                client=client,
                data=buy_data,
                db=self.db,
            ),
            sell_position=HPPositionSell(
                client=client,
                original_position=SellPosition(
                    config=HPSellConfig(
                        hp_id=buy_data.config.hp_id,
                        symbol=buy_data.config.symbol,
                        coin=buy_data.config.coin,
                    ),
                    state_info=StateInfo(side=PositionSide.SHORT),
                    sell_order=Order(quantity=0.0),
                ),
                db=self.db,
                sell_strategy=[],
                price_resolver=price_resolver,
                broker=self.broker,
                worker_queue=worker_queue,
            ),
            # Pass callback for portfolio events
            portfolio_ui_queue=portfolio_ui_queue,
        )

        assert isinstance(strategy.buy.data.config, HPBuyConfig)
        logger.info("HpStrategy created successfully for HP %s", buy_data.config.hp_id)

        # Restore existing buy orders from database instead of creating new ones
        strategy.buy.orders = await self.restore_buy_orders(
            buy_position=strategy.buy, worker_queue=worker_queue, client=client
        )

        # --- Patch: recalculate state from orders after restoration ---
        # Completeness calculation for buy orders
        all_filled = all(
            order.status == ORDER_STATUS_FILLED for order in strategy.buy.orders
        )
        part_bought = any(order.realized_quantity > 0 for order in strategy.buy.orders)

        strategy.buy.data.state_info.state = (
            State.BOUGHT
            if all_filled
            else State.NEW if not part_bought else State.PARTIALLY_BOUGHT
        )

        # --- Restore sell position state and orders if they exist in DB ---
        sell_orders = await self.db.fetch_orders_for_price_level(
            hp_id=buy_data.config.hp_id, side=PositionSide.SHORT.value
        )
        logger.info("[Recovery] fetch_orders_for_price_level returned: %s", sell_orders)
        if sell_orders:
            logger.info(
                "[Recovery] Found %d sell orders for HP %s",
                len(sell_orders),
                buy_data.config.hp_id,
            )
            db_order = sell_orders[0]
            logger.info("[Recovery] Restoring sell order fields from DB: %s", db_order)
            strategy.sell.current_position.sell_order.order_id = db_order["order_id"]
            strategy.sell.current_position.sell_order.quantity = db_order["quantity"]
            strategy.sell.current_position.sell_order.precision = (
                strategy.sell.current_position.config.symbol.precision
            )
            strategy.sell.current_position.sell_order.price_precision = (
                strategy.sell.current_position.config.symbol.price_precision
            )
            strategy.sell.current_position.sell_order.price = db_order["price"]
            strategy.sell.current_position.sell_order.quantity_stable = db_order[
                "quantity_stable"
            ]
            strategy.sell.current_position.sell_order.realized_quantity = db_order[
                "realized_quantity"
            ]
            strategy.sell.current_position.sell_order.status = db_order["status"]
            logger.info(
                "[Recovery] Patched sell order for HP %s: %s",
                buy_data.config.hp_id,
                strategy.sell.current_position.sell_order,
            )
        else:
            logger.info(
                "[Recovery] No sell orders found in DB for HP %s",
                buy_data.config.hp_id,
            )

        strategy_state_str = await self.get_strategy_state_from_db(
            buy_data.config.hp_id
        )
        strategy.state = State(strategy_state_str)
        logger.info(
            "strategy.state restored from DB for restoration: %s",
            strategy.state,
        )
        logger.info("buy data state preserved as: %s", buy_data.state_info.state)

        # Strategy management should be handled by StrategyExecutor
        # Return the strategy so StrategyExecutor can manage it
        return strategy
        self.broker.subscribe(
            system_id=str(buy_data.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=buy_data.config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        self.broker.subscribe(
            system_id=str(buy_data.config.hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.PRICE,
                symbol=buy_data.config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )

        await self.db.upsert_buy_price_level(
            data=strategy.buy.data, strategy_state=strategy.state
        )

        strategy.worker_task = asyncio.create_task(strategy.worker())
        logger.info("System with ID %s restored.", buy_data.config.hp_id)

    async def restore_buy_orders(
        self,
        buy_position: HPPositionBuy,
        worker_queue: queue.Queue,
        client: BinanceClient,
    ) -> List[Order]:
        buy_config = buy_position.data.config  # Restore orders for buy position

        # Use the dedicated method to fetch all orders for this HP and side
        orders = await self.db.fetch_orders_for_price_level(
            hp_id=buy_config.hp_id, side=PositionSide.LONG.value
        )

        logger.info("Orders for HP: %s, %s", buy_config.hp_id, orders)
        if not orders:
            buy_position.prepare_orders()
            return buy_position.orders

        grouped_orders = defaultdict(list)
        for order_dict in orders:
            key = (order_dict["price"], order_dict["quantity"])
            grouped_orders[key].append(order_dict)

        restored_orders: List[Order] = []
        for (_, _), order_dicts in grouped_orders.items():
            # Aggregate realized_quantity from all orders for this price level
            total_realized = sum(o["realized_quantity"] for o in order_dicts)
            # Find the latest open order (not FILLED or CANCELED), else the latest order
            open_orders = [
                o
                for o in order_dicts
                if o["status"] not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]
            ]
            if open_orders:
                # Use the latest open order (by order_id or timestamp if available)
                latest_order = max(open_orders, key=lambda o: o.get("order_id", 0))
            else:
                # Use the latest order overall
                latest_order = max(order_dicts, key=lambda o: o.get("order_id", 0))

            trading_order = Order(
                order_id=latest_order["order_id"],
                quantity=latest_order["quantity"],
                precision=buy_config.symbol.precision,
                price_precision=buy_config.symbol.price_precision,
                price=latest_order["price"],
                quantity_stable=latest_order["quantity_stable"],
                realized_quantity=total_realized,
                status=latest_order["status"],
            )
            restored_orders.append(trading_order)

        logger.info("Buy orders restored from DB (aggregated): %s.", restored_orders)

        # Confirm buy position state with the exchange for open orders
        for order in restored_orders:
            if order.status not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
                # Retrieve the latest order information from the API
                resp = await client.get_order(
                    symbol=buy_config.symbol.name,
                    orderId=order.order_id,
                )
                latest_status = resp["status"]
                latest_realized_quantity = float(resp["executedQty"])

                # Check if status or realized quantity has changed
                status_changed = latest_status != order.status
                quantity_changed = latest_realized_quantity != order.realized_quantity

                if status_changed or quantity_changed:
                    ex_report = ExecutionReport(
                        symbol=buy_config.symbol.name,
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
                        "Order %s has been modified, execution report send: %s",
                        order.order_id,
                        ex_report,
                    )
                else:
                    logger.info("No changes detected for order %s.", order.order_id)

        return restored_orders

    async def restore_sell_position(
        self,
        sell_data: HPSell,
        client: BinanceClient,
        ui_queue,
        balance,
        config_queue,
        price_resolver,
        portfolio_ui_queue=None,
    ) -> HpStrategy:
        """
        Restore a sell position from crash recovery with its existing HP ID and state.
        Uses the normal setup process but with restoration flag to preserve state.
        """
        # Convert HPSell to SellPosition format expected by setup method
        sell_position = SellPosition(
            config=sell_data.config,
            state_info=sell_data.state_info,
            sell_order=Order(quantity=sell_data.config.quantity),
        )

        # Determine sell strategy for this position
        sell_strategy = determine_sell_strategy(
            config=sell_data.config, symbols=self.symbols
        )

        # For restored positions, extract parent ID for strategy registration
        full_hp_id = sell_position.config.hp_id
        if "_CONVERT" in full_hp_id:
            parent_hp_id = full_hp_id.split("_CONVERT")[0]
        elif "_SELL" in full_hp_id:
            parent_hp_id = full_hp_id.split("_SELL")[0]
        else:
            parent_hp_id = full_hp_id
        logger.info(
            "Setting up NEW SELL position with config: %s", sell_position.config
        )

        worker_queue: queue.Queue = queue.Queue()

        strategy = HpStrategy(
            client=client,
            ui_queue=ui_queue,
            buy_position=HPPositionBuy(
                client=client,
                data=HPBuy(
                    config=HPBuyConfig(
                        hp_id=parent_hp_id,
                        symbol=sell_position.config.symbol,
                        coin=sell_position.config.coin,
                    ),
                    state_info=StateInfo(ui_state=UiState.CLOSED, state=State.BOUGHT),
                ),
                db=self.db,
            ),
            sell_position=HPPositionSell(
                client=client,
                original_position=SellPosition(
                    config=sell_position.config,
                    state_info=sell_position.state_info,
                    sell_order=Order(quantity=sell_position.config.quantity),
                    sell_type=(
                        SellType.TWOHOPS
                        if len(sell_strategy) == 2
                        else (
                            SellType.CONVERT
                            if sell_strategy[0].is_convert_only
                            else SellType.DIRECT
                        )
                    ),
                ),
                db=self.db,
                sell_strategy=sell_strategy,
                price_resolver=price_resolver,
                broker=self.broker,
                worker_queue=worker_queue,
                is_restoration=True,
            ),
            balance=balance,
            db=self.db,
            worker_queue=worker_queue,
            config_queue=config_queue,
            initial_state=State.BOUGHT,
            portfolio_ui_queue=portfolio_ui_queue,
        )

        config = strategy.sell.current_position.config

        # Restore existing sell orders from database
        sell_order = await self.restore_sell_orders(
            sell_config=strategy.sell.current_position.config,
            worker_queue=worker_queue,
            client=client,
        )
        if sell_order:
            strategy.sell.current_position.sell_order = sell_order

        # --- Restore buy position state and orders if they exist in DB ---
        # Check if there are buy orders for this hp_id
        buy_orders = await self.db.fetch_orders_for_price_level(
            hp_id=parent_hp_id, side=PositionSide.LONG.value
        )
        if buy_orders:
            # Use the existing restore_buy_orders logic to populate strategy.buy.orders
            strategy.buy.orders = await self.restore_buy_orders(
                buy_position=strategy.buy,
                worker_queue=worker_queue,
                client=client,
            )
            strategy_state_str = await self.get_strategy_state_from_db(parent_hp_id)
            strategy.state = State(strategy_state_str)

            # Set buy state based on actual buy order statuses
            all_filled = all(
                o.status == ORDER_STATUS_FILLED for o in strategy.buy.orders
            )
            all_new = all(o.status == ORDER_STATUS_NEW for o in strategy.buy.orders)

            if all_filled:
                strategy.buy.data.state_info.state = State.BOUGHT
            elif all_new:
                strategy.buy.data.state_info.state = State.NEW
            elif any(o.realized_quantity > 0 for o in strategy.buy.orders):
                strategy.buy.data.state_info.state = State.PARTIALLY_BOUGHT
            else:
                strategy.buy.data.state_info.state = State.CLOSED

        logger.info(
            "Before restoration, current_position: %s",
            strategy.sell.current_position,
        )
        self.restore_current_sell_position_for_multihop(strategy)
        await self.restore_all_child_sell_positions_for_multihop(strategy)

        logger.info("Current position: %s", strategy.sell.current_position)

        self.broker.subscribe(
            system_id=str(parent_hp_id),
            subscription_info=SubscriptionInfo(
                data_type=SubscriptionType.USER,
                symbol=config.symbol.name,
                target=SubscriptionTarget.BACKEND,
                queue=worker_queue,
            ),
        )
        for symbol in sell_strategy:
            self.broker.subscribe(
                system_id=str(parent_hp_id),
                subscription_info=SubscriptionInfo(
                    data_type=SubscriptionType.PRICE,
                    symbol=symbol.name,
                    target=SubscriptionTarget.BACKEND,
                    queue=worker_queue,
                ),
            )

        await self.db.upsert_sell_price_level(
            data=strategy.sell.current_position, strategy_state=strategy.state
        )

        # For two-hop scenarios, save all sell positions to database (not just current position)
        if len(strategy.sell.sell_positions) > 1:
            for position in strategy.sell.sell_positions:
                if (
                    position != strategy.sell.current_position
                ):  # Don't duplicate the current position
                    logger.info(
                        "[MULTIHOP DEBUG] Saving additional position to DB: %s",
                        position.config.hp_id,
                    )
                    await self.db.upsert_sell_price_level(
                        data=position, strategy_state=strategy.state
                    )

        strategy.worker_task = asyncio.create_task(strategy.worker())

        logger.info("Sell position %s restored successfully", sell_data.config.hp_id)

        return strategy

    async def restore_sell_orders(
        self,
        sell_config: HPSellConfig,
        worker_queue: queue.Queue,
        client: BinanceClient,
    ) -> Optional[Order]:

        # Use the dedicated method to fetch orders for this HP and side
        orders = await self.db.fetch_orders_for_price_level(
            hp_id=sell_config.hp_id,
            side=PositionSide.SHORT.value,
        )

        if not orders:
            logger.info("No sell orders found in DB")
            return None

        if len(orders) == 2:
            for order in orders:
                if order["status"] == ORDER_STATUS_NEW:
                    current_order = order
                    break
        if len(orders) == 1:
            current_order = orders[0]

        # Convert order dictionaries to trading Order objects
        # Only restore orders that are not filled or canceled
        logger.info(
            "Restoring order %s with status %s",
            current_order["order_id"],
            current_order["status"],
        )
        trading_order = Order(
            order_id=current_order["order_id"],
            quantity=current_order["quantity"],
            precision=sell_config.symbol.precision,
            price_precision=sell_config.symbol.price_precision,
            price=current_order["price"],
            quantity_stable=current_order["quantity_stable"],
            realized_quantity=current_order["realized_quantity"],
            status=current_order["status"],
        )

        logger.info("Sell orders restored from DB: %s.", trading_order)

        if current_order["status"] not in [ORDER_STATUS_FILLED, ORDER_STATUS_CANCELED]:
            # Retrieve the latest order information from the API
            resp = await client.get_order(
                symbol=sell_config.symbol.name,
                orderId=current_order["order_id"],
            )
            latest_status = resp["status"]
            latest_realized_quantity = float(resp["executedQty"])

            # Check if status or realized quantity has changed
            status_changed = latest_status != current_order["status"]
            quantity_changed = (
                latest_realized_quantity != current_order["realized_quantity"]
            )

            if status_changed or quantity_changed:
                # Send a message to the appropriate queue

                ex_report = ExecutionReport(
                    symbol=sell_config.symbol.name,
                    quantity=current_order["quantity"],
                    price=current_order["price"],
                    current_order_status=latest_status,
                    order_id=current_order["order_id"],
                    cumulative_filled_quantity=latest_realized_quantity,
                )
                worker_queue.put_nowait(
                    Event(
                        name=EventName.EXECUTION_REPORT,
                        content=ex_report,
                    )
                )
                logger.info(
                    "Order %s has been modified, execution report send: %s",
                    current_order["order_id"],
                    ex_report,
                )
            else:
                logger.info(
                    "No changes detected for order %s.", current_order["order_id"]
                )
        return trading_order

    async def _verify_positions_with_exchange(
        self, client: BinanceClient, positions: List[Position]
    ) -> List[Position]:
        """
        Verify position states with the exchange and update if necessary.

        This is crucial for ensuring consistency after a system outage.
        """
        verified_positions = []

        for position in positions:
            try:
                # Get position orders from database
                orders = await self.db.get_position_orders(position.id)

                # Optimization: If all orders are FILLED, skip exchange verification
                all_filled = all(
                    (
                        order.status.value
                        if hasattr(order.status, "value")
                        else order.status
                    )
                    == "FILLED"
                    for order in orders
                )
                if all_filled and len(orders) > 0:
                    # Just update position from orders, do not query exchange
                    updated_position = await self._update_position_from_orders(
                        position, orders
                    )
                    verified_positions.append(updated_position)
                    continue

                # Otherwise, verify each order with exchange
                updated_orders = []
                for order in orders:
                    if order.exchange_order_id:
                        # Check order status with exchange
                        try:
                            exchange_order = await client.get_order(
                                symbol=order.symbol, orderId=order.exchange_order_id
                            )

                            # Update order status if changed
                            if exchange_order["status"] != order.status.value:
                                logger.info(
                                    "Order %s status changed from %s to %s",
                                    order.exchange_order_id,
                                    order.status.value,
                                    exchange_order["status"],
                                )
                                order.status = self._convert_exchange_status(
                                    exchange_order["status"]
                                )
                                order.realized_quantity = float(
                                    exchange_order["executedQty"]
                                )

                                # Save updated order
                                await self.db.save_order(order)

                            updated_orders.append(order)

                        except Exception as e:
                            logger.warning(
                                "Could not verify order %s: %s",
                                order.exchange_order_id,
                                e,
                            )
                            updated_orders.append(order)
                    else:
                        updated_orders.append(
                            order
                        )  # Update position based on order states only if there are orders
                if updated_orders:
                    updated_position = await self._update_position_from_orders(
                        position, updated_orders
                    )
                    verified_positions.append(updated_position)
                else:
                    # No orders, keep position as-is
                    verified_positions.append(position)

            except Exception as e:
                logger.error("Failed to verify position %s: %s", position.hp_id, e)
                # Add position anyway for manual review
                verified_positions.append(position)

        return verified_positions

    async def _update_position_from_orders(
        self, position: Position, orders: List[DatabaseOrder]
    ) -> Position:
        """Update position status and quantities based on order states."""
        if not orders:
            # No orders, return position unchanged
            return position

        total_quantity = sum(order.quantity for order in orders)
        realized_quantity = sum(order.realized_quantity for order in orders)

        # Update quantities
        position.quantity = total_quantity
        position.realized_quantity = realized_quantity
        position.completeness = (
            realized_quantity / total_quantity if total_quantity > 0 else 0.0
        )

        # Explicitly check for all orders canceled
        all_canceled = all(
            (order.status.value if hasattr(order.status, "value") else order.status)
            == "CANCELED"
            for order in orders
        )
        any_filled = any(
            (order.status.value if hasattr(order.status, "value") else order.status)
            == "FILLED"
            for order in orders
        )
        any_partial = any(
            (order.realized_quantity if hasattr(order, "realized_quantity") else 0.0)
            > 0.0
            for order in orders
        )
        if all_canceled and not any_filled:
            if any_partial:
                position.status = PositionStatus.PARTIALLY_FILLED
                logger.info(
                    "[Recovery] All buy orders canceled but some partially filled for position %s: setting status to PARTIALLY_FILLED",
                    position.hp_id,
                )
            else:
                position.status = PositionStatus.NEW
                position.completeness = 0.0
                logger.info(
                    "[Recovery] All buy orders canceled and none filled for position %s: setting status to NEW and completeness to 0.0",
                    position.hp_id,
                )
        elif position.completeness == 0.0:
            if any(
                (order.status.value if hasattr(order.status, "value") else order.status)
                in ["NEW", "PARTIALLY_FILLED"]
                for order in orders
            ):
                position.status = PositionStatus.OPEN
            else:
                position.status = PositionStatus.NEW
        elif (
            position.completeness >= 1.0
        ):  # Use >= instead of == for floating point safety
            position.status = PositionStatus.FILLED
        else:
            position.status = PositionStatus.PARTIALLY_FILLED

        # Save updated position

        # --- PATCH: Check for PARTIALLY_SOLD after full buy and partial/canceled sell ---
        try:
            # Only run this for BUY positions
            if (
                position.position_type == PositionType.BUY
                and position.status == PositionStatus.FILLED
            ):
                # Try to find a related SELL position (same hp_id, type SELL)
                related_sell_positions = []
                if hasattr(self.db, "get_positions_by_hp_id"):
                    related_sell_positions = await self.db.get_positions_by_hp_id(
                        position.hp_id, PositionType.SELL
                    )
                # Fallback: try to get all positions and filter
                elif hasattr(self.db, "get_active_positions"):
                    all_positions = await self.db.get_active_positions()
                    related_sell_positions = [
                        p
                        for p in all_positions
                        if getattr(p, "hp_id", None) == position.hp_id
                        and getattr(p, "position_type", None) == PositionType.SELL
                    ]
                for sell_pos in related_sell_positions:
                    # Get all orders for the sell position
                    sell_orders = []
                    if hasattr(self.db, "get_position_orders"):
                        sell_orders = await self.db.get_position_orders(sell_pos.id)
                    # If any sell order is CANCELED and realized_quantity > 0, set PARTIALLY_SOLD
                    for so in sell_orders:
                        so_status = (
                            so.status.value
                            if hasattr(so.status, "value")
                            else so.status
                        )
                        if (
                            so_status == "CANCELED"
                            and getattr(so, "realized_quantity", 0.0) > 0.0
                        ):
                            logger.warning(
                                "[Recovery] Detected fully filled buy and partially filled/canceled sell for hp_id=%s: setting strategy_state to PARTIALLY_SOLD",
                                position.hp_id,
                            )
                            position.strategy_state = "PARTIALLY_SOLD"
                            break

        except Exception as e:
            logger.error(
                "[Recovery] Error in PARTIALLY_SOLD patch logic for hp_id=%s: %s",
                getattr(position, "hp_id", None),
                e,
            )

        await self.db.save_position(position)
        return position

    def _convert_to_state_info_state(
        self, status: PositionStatus, completeness: float, side: PositionSide
    ) -> State:
        """
        Convert database PositionStatus and side to the nested state_info.state for HPBuy/HPSell.
        This state should never be BUYING or SELLING, only terminal/summary states.
        Handles both buy and sell sides, and complex/edge states.
        For OPEN status, return BUYING/SELLING for the nested state to match the main strategy state.
        """
        # Handle fully filled (or completeness >= 1.0, even if status is PARTIALLY_FILLED)
        if completeness >= 1.0:
            logger.debug(
                "[Recovery] Mapping to state: completeness >= 1.0, status=%s, side=%s -> BOUGHT/SOLD",
                status,
                side,
            )
            return State.BOUGHT if side == PositionSide.LONG else State.SOLD
        # Handle fully filled by status (legacy safety)
        if status == PositionStatus.FILLED:
            logger.debug(
                "[Recovery] Mapping to state: status == FILLED, completeness=%s, side=%s -> BOUGHT/SOLD",
                completeness,
                side,
            )
            return State.BOUGHT if side == PositionSide.LONG else State.SOLD
        # Handle partially filled
        if status == PositionStatus.PARTIALLY_FILLED or (0.0 < completeness < 1.0):
            logger.debug(
                "[Recovery] Mapping to state: PARTIALLY_FILLED, status=%s, completeness=%s, side=%s",
                status,
                completeness,
                side,
            )
            if side == PositionSide.LONG:
                return State.PARTIALLY_BOUGHT
            elif side == PositionSide.SHORT:
                return State.PARTIALLY_SOLD
        # Handle open (orders sent, not filled)
        if status == PositionStatus.OPEN:
            logger.debug("[Recovery] Mapping to state: OPEN, side=%s", side)
            if side == PositionSide.LONG:
                return State.BUYING
            elif side == PositionSide.SHORT:
                return State.SELLING
        # New
        if status == PositionStatus.NEW:
            logger.debug("[Recovery] Mapping to state: NEW, side=%s", side)
            return State.NEW
        # Closed/canceled
        if status == PositionStatus.CANCELED or status == PositionStatus.CLOSED:
            logger.debug("[Recovery] Mapping to state: CANCELED/CLOSED, side=%s", side)
            return State.CLOSED
        # Waiting
        if (
            status == PositionStatus.WAITING_PARENT
            or status == PositionStatus.WAITING_CHILD
        ):
            logger.debug("[Recovery] Mapping to state: WAITING, side=%s", side)
            return State.WAITING_CHILD
        # Fallback
        logger.warning(
            "[Recovery] Mapping to state: FALLBACK to NEW, status=%s, completeness=%s, side=%s",
            status,
            completeness,
            side,
        )
        return State.NEW

    async def _convert_to_buy_data(self, position: Position) -> Optional[HPBuy]:
        """Convert database Position to HPBuy for the trading system."""
        try:
            symbol = self.symbols.get(position.symbol)
            if not symbol:
                logger.error("Symbol info not found for %s", position.symbol)
                return None

            # Ensure that if all buy orders are filled, completeness is correct
            if position.status == PositionStatus.FILLED and position.completeness < 1.0:
                position.completeness = 1.0

            # Always enforce: if completeness >= 1.0, buy state must be BOUGHT (never PARTIALLY_SOLD), regardless of any strategy state
            state_info_state = self._convert_to_state_info_state(
                position.status, position.completeness, PositionSide.LONG
            )

            # Special case: if database status is NEW but strategy_state is BUYING/SELLING,
            # it means orders were sent but no fills yet, so state should reflect the active trading state
            logger.debug(
                "[Recovery] Checking special case: status=%s, strategy_state=%s, condition=%s",
                position.status,
                position.strategy_state,
                (
                    position.status == PositionStatus.NEW
                    and position.strategy_state
                    and position.strategy_state in ["BUYING", "SELLING"]
                ),
            )
            if (
                position.status == PositionStatus.NEW
                and position.strategy_state
                and position.strategy_state in ["BUYING", "SELLING"]
            ):
                logger.info(
                    "[Recovery] Position status=NEW but strategy_state=%s, using strategy state for state_info",
                    position.strategy_state,
                )
                if position.strategy_state == "BUYING":
                    state_info_state = State.BUYING
                elif position.strategy_state == "SELLING":
                    state_info_state = State.SELLING

            if position.completeness >= 1.0:
                if state_info_state != State.BOUGHT:
                    logger.warning(
                        "[Recovery] For hp_id=%s, completeness=%.3f, forcibly setting buy state to BOUGHT (was %s)",
                        position.hp_id,
                        position.completeness,
                        state_info_state,
                    )
                # Explicitly set buy state to BOUGHT if all buy orders are filled
                state_info_state = State.BOUGHT
            else:
                # If for any reason the mapping returns PARTIALLY_SOLD for a buy, force to PARTIALLY_BOUGHT
                if state_info_state == State.PARTIALLY_SOLD:
                    logger.error(
                        "[Recovery] Invalid buy state PARTIALLY_SOLD detected for hp_id=%s, forcing to PARTIALLY_BOUGHT",
                        position.hp_id,
                    )
                    state_info_state = State.PARTIALLY_BOUGHT
                else:
                    logger.info(
                        "[Recovery] For hp_id=%s, completeness=%.3f, buy state mapped to %s",
                        position.hp_id,
                        position.completeness,
                        state_info_state,
                    )

            config = HPBuyConfig(
                symbol=symbol,
                coin=position.coin,
                hp_id=position.hp_id,
                price_low=position.price_low,
                price_high=position.price_high,
                order_trigger=position.order_trigger,
                budget=position.budget,
                mode=(
                    Mode(position.mode)
                    if position.mode in ["SINGLE", "DCA"]
                    else Mode.DCA
                ),
            )

            state_info = StateInfo(
                state=state_info_state,
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.LONG,
                completeness=position.completeness,
            )

            logger.debug(
                "[Recovery] Creating HPBuy with state=%s for hp_id=%s",
                state_info_state,
                position.hp_id,
            )

            return HPBuy(config=config, state_info=state_info)

        except Exception as e:
            logger.error(
                "Failed to convert position %s to buy data: %s", position.hp_id, e
            )
            return None

    async def _convert_to_sell_data(self, position: Position) -> Optional[HPSell]:
        """Convert database Position to HPSell for the trading system."""
        try:
            symbol = self.symbols.get(position.symbol)
            if not symbol:
                logger.error("Symbol info not found for %s", position.symbol)
                return None

            config = HPSellConfig(
                symbol=symbol,
                hp_id=position.hp_id,
                coin=position.coin,
                quantity=position.quantity,
                buy_price=position.buy_price,
                sell_price=position.sell_price,
                end_currency=position.end_currency,
                is_child=position.parent_position_id is not None,
                parent_hp_id=position.parent_position_id,
            )

            # Nested state_info.state (never BUYING/SELLING), pass side explicitly
            state_info_state = self._convert_to_state_info_state(
                position.status, position.completeness, PositionSide.SHORT
            )

            state_info = StateInfo(
                state=state_info_state,
                open_time=position.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                side=PositionSide.SHORT,
                completeness=position.completeness,
            )

            return HPSell(config=config, state_info=state_info)

        except Exception as e:
            logger.error(
                "Failed to convert position %s to sell data: %s", position.hp_id, e
            )
            return None

    def _convert_to_state(self, status: PositionStatus) -> State:
        """Convert database PositionStatus to trading system State."""
        mapping = {
            PositionStatus.NEW: State.NEW,
            PositionStatus.OPEN: State.BUYING,  # or SELLING depending on context
            PositionStatus.PARTIALLY_FILLED: State.PARTIALLY_BOUGHT,  # or PARTIALLY_SOLD
            PositionStatus.FILLED: State.BOUGHT,  # or SOLD
            PositionStatus.CANCELED: State.CLOSED,
            PositionStatus.CLOSED: State.CLOSED,
            PositionStatus.WAITING_PARENT: State.WAITING_CHILD,
            PositionStatus.WAITING_CHILD: State.WAITING_CHILD,
        }
        return mapping.get(status, State.NEW)

    def _convert_exchange_status(self, exchange_status: str):
        """Convert exchange order status to our OrderStatus."""

        mapping = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.CANCELED,
        }
        return mapping.get(exchange_status, OrderStatus.NEW)

    async def recover_multihop_positions(self) -> Dict[str, List[Position]]:
        """
        Recover multihop positions with their complete hierarchies.

        Returns:
            Dict mapping parent hp_id to list of positions in the chain
        """
        try:
            active_positions = (
                await self.db.get_active_positions()
            )  # Group by parent positions
            multihop_chains: Dict[str, List[Position]] = {}

            for position in active_positions:
                if position.trade_type in [TradeType.TWOHOP, TradeType.CONVERT]:
                    # Find the root parent
                    root_hp_id = position.hp_id
                    if position.parent_position_id:
                        # This is a child, find the parent
                        parent_positions = [
                            p
                            for p in active_positions
                            if p.id == position.parent_position_id
                        ]
                        if parent_positions:
                            root_hp_id = parent_positions[0].hp_id

                    if root_hp_id not in multihop_chains:
                        multihop_chains[root_hp_id] = []
                    multihop_chains[root_hp_id].append(position)

            # Sort each chain by hop sequence
            for _, chain in multihop_chains.items():
                chain.sort(key=lambda p: p.hop_sequence)

            logger.info("Recovered %d multihop position chains", len(multihop_chains))
            return multihop_chains

        except Exception as e:
            raise RecoveryError(f"Failed to recover multihop positions: {e}") from e

    async def validate_recovery_integrity(self) -> Dict[str, Any]:
        """
        Validate the integrity of recovered positions.

        Returns a report of any issues found.
        """
        try:
            issues: Dict[str, List[str]] = {
                "missing_symbols": [],
                "orphaned_orders": [],
                "inconsistent_states": [],
                "broken_hierarchies": [],
            }

            positions = await self.db.get_active_positions()

            for position in positions:
                # Check if symbol info exists
                if position.symbol not in self.symbols:
                    issues["missing_symbols"].append(position.symbol)

                # Check for broken parent-child relationships
                if position.parent_position_id:
                    parents = [
                        p for p in positions if p.id == position.parent_position_id
                    ]
                    if not parents:
                        issues["broken_hierarchies"].append(
                            f"Position {position.hp_id} has missing parent {position.parent_position_id}"
                        )

                # Check orders
                orders = await self.db.get_position_orders(position.id)
                for order in orders:
                    if order.position_id != position.id:
                        issues["orphaned_orders"].append(order.id)

            return issues

        except Exception as e:
            logger.error("Failed to validate recovery integrity: %s", e)
            return {"validation_error": str(e)}

    async def get_strategy_state_from_db(self, hp_id: str) -> Optional[str]:
        """
        Get the strategy execution state for a given HP ID from the database.

        Args:
            hp_id: The HP ID to query for

        Returns:
            The strategy_state string from the database, or None if not found
        """
        try:
            async with self.db.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT strategy_state FROM positions WHERE hp_id = ? LIMIT 1",
                    (hp_id,),
                )
                row = await cursor.fetchone()
                if row:
                    return row["strategy_state"]
                logger.warning("No strategy state found for HP ID: %s", hp_id)
                return None
        except Exception as e:
            logger.error("Failed to get strategy state for HP %s: %s", hp_id, e)
            return None

    def restore_current_sell_position_for_multihop(self, strategy: HpStrategy) -> None:
        """
        If this is a two-hop sell, and the first leg is FILLED,
        advance current_position to the second leg.
        """
        sell_positions = strategy.sell.sell_positions
        if sell_positions and len(sell_positions) == 2:
            first_leg = sell_positions[0]
            second_leg = sell_positions[1]
            if first_leg.sell_order.status == ORDER_STATUS_FILLED:
                # Advance current_position to the second leg
                strategy.sell.current_position = second_leg
                logger.info(
                    "[Recovery] Advanced current_position to second leg after first leg FILLED: %s",
                    second_leg.config.hp_id,
                )

    async def restore_all_child_sell_positions_for_multihop(self, strategy: HpStrategy):
        """
        For two-hop sells, after recovery, restore both child sell positions (e.g., hp_id ending with 'a' and 'b') from DB.
        Set their orders and state, and set current_position to the correct child based on the status of the child positions in the DB.
        """
        sell_positions = strategy.sell.sell_positions
        if not (sell_positions and len(sell_positions) == 2):
            return

        # Restore each child sell position's order from DB (as before)
        for pos in sell_positions:
            orders = await self.db.fetch_orders_for_price_level(
                hp_id=pos.config.hp_id, side=PositionSide.SHORT.value
            )
            if orders:
                order_dict = orders[0]
                pos.sell_order.order_id = order_dict["order_id"]
                pos.sell_order.quantity = order_dict["quantity"]
                pos.sell_order.precision = pos.config.symbol.precision
                pos.sell_order.price_precision = pos.config.symbol.price_precision
                pos.sell_order.price = order_dict["price"]
                pos.sell_order.quantity_stable = order_dict["quantity_stable"]
                pos.sell_order.realized_quantity = order_dict["realized_quantity"]
                pos.sell_order.status = order_dict["status"]
                logger.info(
                    "[Recovery] Patched sell order for child %s: %s",
                    pos.config.hp_id,
                    pos.sell_order,
                )
            else:
                logger.info(
                    "[Recovery] No sell orders found in DB for child %s",
                    pos.config.hp_id,
                )

        # Set current_position based on child leg order status
        first_leg = sell_positions[0]
        second_leg = sell_positions[1]
        first_status = first_leg.sell_order.status
        second_status = second_leg.sell_order.status

        if first_status == ORDER_STATUS_FILLED:
            strategy.sell.current_position = second_leg
            logger.info(
                "[Recovery] Set current_position to second leg after first leg FILLED: %s",
                second_leg.config.hp_id,
            )
        elif first_status in [ORDER_STATUS_NEW, "PARTIALLY_FILLED", "SUBMITTED"]:
            strategy.sell.current_position = first_leg
            logger.info(
                "[Recovery] Set current_position to first leg (open): %s",
                first_leg.config.hp_id,
            )
        elif second_status in [ORDER_STATUS_NEW, "PARTIALLY_FILLED", "SUBMITTED"]:
            strategy.sell.current_position = second_leg
            logger.info(
                "[Recovery] Set current_position to second leg (open): %s",
                second_leg.config.hp_id,
            )
        else:
            # Fallback: set to 'b' if present
            for pos in sell_positions:
                if pos.config.hp_id.endswith("b"):
                    strategy.sell.current_position = pos
                    logger.info(
                        "[Recovery] Fallback: Set current_position to child leg 'b': %s",
                        pos.config.hp_id,
                    )
                    break
