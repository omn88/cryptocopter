class CrashRecoveryHelper:
    @staticmethod
    def mock_orders_from_db(order_db_list):
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
