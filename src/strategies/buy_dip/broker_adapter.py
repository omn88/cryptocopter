"""
Broker Adapter for Buy Dip Strategy

Bridges the strategy's broker interface with the application's BrokerSpot.
Handles order placement, cancellation, and fill callbacks.
"""

import logging
from decimal import Decimal
from typing import Optional, Callable, Dict
from src.common.client import BinanceClient
from src.common.symbol import Symbol

logger = logging.getLogger(__name__)


class BuyDipBrokerAdapter:
    """
    Adapter between BuyDipStrategy and application broker/client.

    Responsibilities:
    - Place orders via BinanceClient REST API
    - Cancel orders via BinanceClient REST API
    - Register callbacks for order fills (from WebSocket user stream)
    - Format order requests according to Binance API requirements
    - Apply symbol-specific precision and validation rules
    """

    def __init__(self, client: BinanceClient, symbol: Symbol):
        """
        Initialize broker adapter.

        Args:
            client: BinanceClient instance for REST API calls
            symbol: Symbol object with precision and validation rules
        """
        self.client = client
        self.symbol = symbol

        # Callbacks for order events
        self._order_filled_callback: Optional[Callable] = None
        self._order_cancelled_callback: Optional[Callable] = None

        # Track pending orders
        self._pending_orders: Dict[str, Dict] = {}  # order_id -> order_data

    def set_order_filled_callback(self, callback: Callable) -> None:
        """
        Set callback for order fills.

        Args:
            callback: Function(order_id, fill_price) to call on fill
        """
        self._order_filled_callback = callback

    def set_order_cancelled_callback(self, callback: Callable) -> None:
        """
        Set callback for order cancellations.

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
        """
        Place a limit order on Binance.

        Args:
            order_id: Client order ID (unique identifier)
            side: "BUY" or "SELL"
            price: Limit price (will be adjusted to symbol precision)
            quantity: Order quantity (will be adjusted to symbol precision)

        Returns:
            Order response from Binance API
        """
        try:
            # Apply symbol precision rules
            adjusted_price = self.symbol.adjust_price(float(price))
            adjusted_quantity = self.symbol.adjust_quantity(float(quantity))

            # Validate order meets minimum notional requirements
            self.symbol.validate_order(price=adjusted_price, quantity=adjusted_quantity)

            # Format for display (logging)
            price_str = self.symbol.format_price(adjusted_price)
            quantity_str = self.symbol.format_quantity(adjusted_quantity)

            # Format for Binance API
            order_response = await self.client.create_order(
                symbol=self.symbol.name,
                side=side,
                order_type="LIMIT",
                time_in_force="GTC",  # Good Till Cancel
                quantity=adjusted_quantity,
                price=adjusted_price,
                new_client_order_id=order_id,
            )

            # Track the order
            self._pending_orders[order_id] = {
                "side": side,
                "price": Decimal(str(adjusted_price)),
                "quantity": Decimal(str(adjusted_quantity)),
                "binance_order_id": order_response.get("orderId"),
                "status": order_response.get("status"),
            }

            logger.info(
                f"Placed {side} order {order_id} @ {price_str} "
                f"qty {quantity_str} (Binance ID: {order_response.get('orderId')})"
            )

            return order_response

        except Exception as e:
            logger.error(f"Failed to place order {order_id}: {e}")
            raise

    async def cancel_order(self, order_id: str) -> Dict:
        """
        Cancel an order on Binance.

        Args:
            order_id: Client order ID to cancel

        Returns:
            Cancellation response from Binance API
        """
        try:
            # Cancel via REST API
            cancel_response = await self.client.cancel_order(
                symbol=self.symbol.name,
                orig_client_order_id=order_id,
            )

            logger.info(
                f"Cancelled order {order_id} "
                f"(Binance ID: {cancel_response.get('orderId', 0)})"
            )

            # Remove from tracking
            if order_id in self._pending_orders:
                del self._pending_orders[order_id]

            # Trigger callback if set
            if self._order_cancelled_callback:
                self._order_cancelled_callback(order_id)

            return cancel_response

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise

    def handle_user_stream_update(self, event: Dict) -> None:
        """
        Handle user stream events (order updates from WebSocket).

        Args:
            event: User stream event from Binance WebSocket
        """
        event_type = event.get("e")

        if event_type == "executionReport":
            order_id = event.get("c")  # Client order ID
            order_status = event.get("X")  # Order status

            if order_status == "FILLED":
                # Order fully filled
                fill_price = Decimal(str(event.get("L")))  # Last executed price

                logger.info(
                    f"Order {order_id} FILLED @ {fill_price} "
                    f"(qty: {event.get('l')})"
                )

                # Remove from tracking
                if order_id in self._pending_orders:
                    del self._pending_orders[order_id]

                # Trigger callback
                if self._order_filled_callback:
                    self._order_filled_callback(order_id, fill_price)

            elif order_status == "CANCELED":
                logger.info(f"Order {order_id} CANCELED")

                # Remove from tracking
                if order_id in self._pending_orders:
                    del self._pending_orders[order_id]

                # Trigger callback
                if self._order_cancelled_callback:
                    self._order_cancelled_callback(order_id)

            elif order_status == "EXPIRED":
                logger.info(f"Order {order_id} EXPIRED")

                # Treat expired same as cancelled
                if order_id in self._pending_orders:
                    del self._pending_orders[order_id]

                if self._order_cancelled_callback:
                    self._order_cancelled_callback(order_id)

    def get_pending_order(self, order_id: str) -> Optional[Dict]:
        """
        Get pending order details.

        Args:
            order_id: Client order ID

        Returns:
            Order data or None if not found
        """
        return self._pending_orders.get(order_id)

    def get_all_pending_orders(self) -> Dict[str, Dict]:
        """
        Get all pending orders.

        Returns:
            Dictionary of order_id -> order_data
        """
        return self._pending_orders.copy()
