"""Mock Broker Adapter for Backtesting.

Simulates WebSocket execution reports and order lifecycle
without connecting to real exchange.
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional, Callable, Dict

logger = logging.getLogger(__name__)


class MockBrokerAdapter:
    """Mock broker that simulates order execution for backtesting.

    This adapter mimics the behavior of BuyDipBrokerAdapter but instead of
    placing real orders, it stores them and allows the backtester to simulate
    fills by sending execution reports.
    """

    def __init__(self, symbol: str):
        """Initialize mock broker.

        Args:
            symbol: Trading symbol (e.g., "BTCUSDC")
        """
        self.symbol = symbol

        # Callbacks for order events (same as real broker)
        self._order_filled_callback: Optional[Callable] = None
        self._order_cancelled_callback: Optional[Callable] = None

        # Track pending orders (order_id -> order_data)
        self._pending_orders: Dict[str, Dict] = {}

        # Track filled orders for analysis
        self._filled_orders: Dict[str, Dict] = {}
        self._cancelled_orders: Dict[str, Dict] = {}

    def set_order_filled_callback(self, callback: Callable) -> None:
        """Set callback for order fills.

        Args:
            callback: Function(order_id, fill_price) to call on fill
        """
        self._order_filled_callback = callback

    def set_order_cancelled_callback(self, callback: Callable) -> None:
        """Set callback for order cancellations.

        Args:
            callback: Function(order_id) to call on cancellation
        """
        self._order_cancelled_callback = callback

    async def place_order(
        self,
        order_id: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
    ) -> Dict:
        """Simulate placing a limit order.

        Args:
            order_id: Client order ID (unique identifier)
            side: "BUY" or "SELL"
            price: Limit price
            quantity: Order quantity

        Returns:
            Simulated order response (like Binance API)
        """
        # Store the pending order
        self._pending_orders[order_id] = {
            "side": side,
            "price": price,
            "quantity": quantity,
            "status": "NEW",
            "binance_order_id": f"mock_{order_id}",
        }

        logger.debug(f"Mock order placed: {order_id} {side} {quantity} @ {price}")

        # Return simulated API response
        return {
            "orderId": f"mock_{order_id}",
            "clientOrderId": order_id,
            "symbol": self.symbol,
            "status": "NEW",
            "price": str(price),
            "origQty": str(quantity),
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
        }

    async def cancel_order(self, order_id: str) -> bool:
        """Simulate canceling an order.

        Args:
            order_id: Client order ID to cancel

        Returns:
            True if cancelled, False if not found
        """
        if order_id not in self._pending_orders:
            logger.warning(f"Mock cancel: Order {order_id} not found")
            return False

        # Move to cancelled
        order_data = self._pending_orders.pop(order_id)
        self._cancelled_orders[order_id] = order_data

        logger.debug(f"Mock order cancelled: {order_id}")

        # Trigger callback if set
        if self._order_cancelled_callback:
            try:
                result = self._order_cancelled_callback(order_id)
                # Handle both sync and async callbacks
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Error in cancel callback: {e}")

        return True

    def simulate_fill(self, order_id: str, fill_price: Decimal) -> bool:
        """Simulate an order fill (called by backtester).

        This mimics receiving an executionReport from WebSocket.

        Args:
            order_id: Client order ID that filled
            fill_price: Price at which order filled

        Returns:
            True if order was pending and filled, False otherwise
        """
        if order_id not in self._pending_orders:
            logger.warning(f"Mock fill: Order {order_id} not found in pending")
            return False

        # Move to filled
        order_data = self._pending_orders.pop(order_id)
        order_data["status"] = "FILLED"
        order_data["fill_price"] = fill_price
        self._filled_orders[order_id] = order_data

        logger.debug(
            f"Mock order filled: {order_id} {order_data['side']} "
            f"{order_data['quantity']} @ {fill_price}"
        )

        # Trigger callback if set (simulate executionReport processing)
        if self._order_filled_callback:
            try:
                result = self._order_filled_callback(order_id, fill_price)
                # Handle both sync and async callbacks
                if asyncio.iscoroutine(result):
                    # Don't await here - let caller handle it
                    # This mimics how WebSocket messages are processed
                    asyncio.create_task(result)
            except Exception as e:
                logger.error(f"Error in fill callback: {e}")

        return True

    def get_pending_orders(self) -> Dict[str, Dict]:
        """Get all pending orders.

        Returns:
            Dict mapping order_id to order data
        """
        return self._pending_orders.copy()

    def get_filled_orders(self) -> Dict[str, Dict]:
        """Get all filled orders.

        Returns:
            Dict mapping order_id to order data (including fill_price)
        """
        return self._filled_orders.copy()

    def get_cancelled_orders(self) -> Dict[str, Dict]:
        """Get all cancelled orders.

        Returns:
            Dict mapping order_id to order data
        """
        return self._cancelled_orders.copy()

    def handle_user_stream_update(self, event: Dict) -> None:
        """Handle simulated user stream events (for compatibility).

        This method exists for API compatibility with BuyDipBrokerAdapter
        but isn't used in backtesting - we call simulate_fill directly.

        Args:
            event: Simulated execution report event
        """
        if event.get("e") != "executionReport":
            return

        order_id = event.get("c")  # clientOrderId
        status = event.get("X")  # orderStatus

        if status == "FILLED" and order_id:
            fill_price = Decimal(str(event.get("L", event.get("p"))))
            self.simulate_fill(order_id, fill_price)
        elif status == "CANCELED":
            if order_id in self._pending_orders:
                order_data = self._pending_orders.pop(order_id)
                self._cancelled_orders[order_id] = order_data

                if self._order_cancelled_callback:
                    try:
                        result = self._order_cancelled_callback(order_id)
                        if asyncio.iscoroutine(result):
                            asyncio.create_task(result)
                    except Exception as e:
                        logger.error(f"Error in cancel callback: {e}")
