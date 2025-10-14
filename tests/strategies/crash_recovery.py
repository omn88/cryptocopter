import logging

logger = logging.getLogger("crash_recovery_helper")


class CrashRecoveryHelper:
    def __init__(self, front, back):
        self.front = front
        self.back = back

    async def assert_application_db_state_match(self, hp_id: str = "1000") -> None:
        """Assert that the in-memory application state matches the database state for a position."""

        logger.info(
            "=== ASSERTING APPLICATION <-> DATABASE STATE MATCH for %s ===", hp_id
        )

        # Get the in-memory strategy
        strategy = self.back.strategies.get(hp_id)
        assert strategy is not None, f"Strategy {hp_id} not found in memory"

        # Get the corresponding position from database
        positions = await self.front.db.get_active_positions()
        db_position = None
        for pos in positions:
            if pos.hp_id == hp_id:
                db_position = pos
                break

        assert db_position is not None, f"Position {hp_id} not found in database"

        # Determine if this is a BUY or SELL position
        from src.database.models import PositionType

        is_sell_position = db_position.position_type == PositionType.SELL

        # Get the appropriate config based on position type
        if is_sell_position:
            # For SELL positions, use sell.original_position.config
            memory_config = strategy.sell.original_position.config
            memory_hp_id = memory_config.hp_id
            memory_symbol = memory_config.symbol.name
            memory_coin = memory_config.coin
            memory_buy_price = memory_config.buy_price
            memory_budget = 0.0  # Sell positions don't have budget
            memory_order_trigger = 0.0  # Sell positions don't have order_trigger
        else:
            # For BUY positions, use buy.data.config
            memory_config = strategy.buy.data.config
            memory_hp_id = memory_config.hp_id
            memory_symbol = memory_config.symbol.name
            memory_coin = memory_config.coin
            memory_buy_price = memory_config.buy_price
            memory_budget = memory_config.budget
            memory_order_trigger = memory_config.order_trigger

        # Compare core identification fields
        assert (
            db_position.hp_id == memory_hp_id
        ), f"HP ID mismatch: DB={db_position.hp_id}, Memory={memory_hp_id}"

        assert (
            db_position.symbol == memory_symbol
        ), f"Symbol mismatch: DB={db_position.symbol}, Memory={memory_symbol}"

        assert (
            db_position.coin == memory_coin
        ), f"Coin mismatch: DB={db_position.coin}, Memory={memory_coin}"

        # Compare configuration fields (skip budget and order_trigger for sell positions)
        if not is_sell_position:
            assert (
                db_position.budget == memory_budget
            ), f"Budget mismatch: DB={db_position.budget}, Memory={memory_budget}"

            assert (
                db_position.order_trigger == memory_order_trigger
            ), f"Order trigger mismatch: DB={db_position.order_trigger}, Memory={memory_order_trigger}"

        assert (
            db_position.buy_price == memory_buy_price
        ), f"Buy price mismatch: DB={db_position.buy_price}, Memory={memory_buy_price}"

        # Tolerate DB state == PARTIALLY_BOUGHT and memory == BUYING after cancel/resend recovery

        assert (
            db_position.strategy_state == strategy.state.value
        ), f"Strategy state mismatch: DB={db_position.strategy_state}, Memory={strategy.state}"

        logger.info("✓ Application and database state match verified successfully")
        logger.info("Matched fields:")
        logger.info("  HP ID: %s", db_position.hp_id)
        logger.info("  Symbol: %s", db_position.symbol)
        logger.info("  Coin: %s", db_position.coin)
        if not is_sell_position:
            logger.info("  Budget: %s", db_position.budget)
            logger.info("  Order trigger: %s", db_position.order_trigger)
        logger.info("  Buy price: %s", db_position.buy_price)
        logger.info(
            "  Strategy state: %s (matches: %s)",
            db_position.strategy_state,
            strategy.state,
        )
        logger.info("  Position status: %s", db_position.status)

    def mock_orders_from_db(self, order_db_list):
        """
        Returns a mock function that returns the actual status, realized_quantity, etc., for each order from the DB.
        Args:
            order_db_list: List of DB order objects (with .exchange_order_id, .status, .realized_quantity, .quantity, .price)
        Returns:
            Callable for use as side_effect in mock.
        """

        def _mock(symbol, orderId=None):  # type: ignore[no-untyped-def]
            # orderId is camelCase for Binance API compatibility; required for mock side_effect
            oid = orderId
            db_order = next(
                (
                    o
                    for o in order_db_list
                    if getattr(o, "exchange_order_id", None) == oid
                ),
                None,
            )
            if db_order:
                return {
                    "symbol": symbol,
                    "orderId": oid,
                    "status": db_order.status.value,
                    "executedQty": str(db_order.realized_quantity),
                    "origQty": str(db_order.quantity),
                    "price": str(db_order.price),
                }
            # Fallback for unexpected orders
            return {
                "symbol": symbol,
                "orderId": oid,
                "status": "NEW",
                "executedQty": "0.00000000",
                "origQty": "0.00000000",
                "price": "0.00",
            }

        return _mock
