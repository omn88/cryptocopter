"""
Recovery service for restoring trading positions after system restart.

This module handles the complex task of restoring all active positions,
verifying their state with the exchange, and ensuring consistency.
"""

import asyncio
import logging
import queue
from typing import List, Dict, Optional, Tuple, Any

from binance.enums import ORDER_STATUS_FILLED, ORDER_STATUS_NEW

from src.broker import BrokerSpot
from src.common.helpers import determine_sell_strategy
from src.database.trading_database import Database
from src.identifiers import (
    BinanceClient,
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
    UiState,
)
from src.common.symbol import Symbol
from src.strategies.hp_manager.position_buy import HPPositionBuy
from src.strategies.hp_manager.position_sell import HPPositionSell
from src.strategies.hp_manager.hp_manager import HpStrategy
from src.database.models import Position, PositionType, TradeType
from src.database.exceptions import RecoveryError
from .position_converter import PositionConverter
from .order_restorer import OrderRestorer
from .multihop_recovery_handler import MultihopRecoveryHandler
from .position_verifier import PositionVerifier

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

        # Initialize helper classes
        self.converter = PositionConverter(symbols)
        self.order_restorer = OrderRestorer(database)
        self.multihop_handler = MultihopRecoveryHandler(database)
        self.verifier = PositionVerifier(database, self.converter)

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
            verified_positions = await self.verifier.verify_positions_with_exchange(
                client, active_positions
            )

            # Group positions by type
            buy_positions = []
            sell_positions = []

            for position in verified_positions:
                if position.position_type == PositionType.BUY:
                    buy_data = await self.converter.convert_to_buy_data(position)
                    if buy_data:
                        buy_positions.append(buy_data)
                else:
                    sell_data = await self.converter.convert_to_sell_data(position)
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
        strategy.buy.orders = await self.order_restorer.restore_buy_orders(
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
        self.broker.setup_subscriptions(
            hp_id=str(buy_data.config.hp_id),
            symbol=buy_data.config.symbol.name,
            additional_symbols=None,
            worker_queue=worker_queue,
        )

        await self.db.upsert_buy_price_level(
            data=strategy.buy.data, strategy_state=strategy.state
        )

        strategy.worker_task = asyncio.create_task(strategy.worker())
        logger.info("System with ID %s restored.", buy_data.config.hp_id)

        return strategy

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
        parent_hp_id = full_hp_id[:4]
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
        sell_order = await self.order_restorer.restore_sell_orders(
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
            strategy.buy.orders = await self.order_restorer.restore_buy_orders(
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
        self.multihop_handler.restore_current_sell_position_for_multihop(strategy)
        await self.multihop_handler.restore_all_child_sell_positions_for_multihop(
            strategy
        )

        logger.info("Current position: %s", strategy.sell.current_position)

        # Setup broker subscriptions (main symbol + additional symbols for multihop)
        additional_symbols = (
            [s.name for s in sell_strategy[1:]] if len(sell_strategy) > 1 else None
        )
        self.broker.setup_subscriptions(
            hp_id=str(parent_hp_id),
            symbol=config.symbol.name,
            additional_symbols=additional_symbols,
            worker_queue=worker_queue,
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
