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

        # Compare core identification fields
        assert (
            db_position.hp_id == strategy.buy.data.config.hp_id
        ), f"HP ID mismatch: DB={db_position.hp_id}, Memory={strategy.buy.data.config.hp_id}"

        assert (
            db_position.symbol == strategy.buy.data.config.symbol.name
        ), f"Symbol mismatch: DB={db_position.symbol}, Memory={strategy.buy.data.config.symbol.name}"

        assert (
            db_position.coin == strategy.buy.data.config.coin
        ), f"Coin mismatch: DB={db_position.coin}, Memory={strategy.buy.data.config.coin}"

        # Compare configuration fields
        assert (
            db_position.budget == strategy.buy.data.config.budget
        ), f"Budget mismatch: DB={db_position.budget}, Memory={strategy.buy.data.config.budget}"

        assert (
            db_position.buy_price == strategy.buy.data.config.buy_price
        ), f"Buy price mismatch: DB={db_position.buy_price}, Memory={strategy.buy.data.config.buy_price}"

        assert (
            db_position.order_trigger == strategy.buy.data.config.order_trigger
        ), f"Order trigger mismatch: DB={db_position.order_trigger}, Memory={strategy.buy.data.config.order_trigger}"

        # Tolerate DB state == PARTIALLY_BOUGHT and memory == BUYING after cancel/resend recovery

        assert (
            db_position.strategy_state == strategy.state.value
        ), f"Strategy state mismatch: DB={db_position.strategy_state}, Memory={strategy.state}"

        logger.info("✓ Application and database state match verified successfully")
        logger.info("Matched fields:")
        logger.info("  HP ID: %s", db_position.hp_id)
        logger.info("  Symbol: %s", db_position.symbol)
        logger.info("  Coin: %s", db_position.coin)
        logger.info("  Budget: %s", db_position.budget)
        logger.info(
            "  Buy price: %s", db_position.buy_price
        )
        logger.info("  Order trigger: %s", db_position.order_trigger)
        logger.info("  Mode: %s", db_position.mode)
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
