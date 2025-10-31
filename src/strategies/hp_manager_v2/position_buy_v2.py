"""Buy position handler for HP Manager V2 - Uses clean OrderExecutionState.

Simplified buy handler that tracks order execution state separately from
strategy lifecycle state.
"""

import logging
import queue
from typing import Optional

from binance.enums import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC,
)

from src.common.client import BinanceClient
from src.common.identifiers import (
    ExecutionReport,
    HPBuyConfig,
    HPBuyOrdersPlaced,
    HPBuyPositionFilled,
    HPBuyPositionPartiallyFilled,
    Order,
    State,
    StateInfo,
    PositionSide,
)
from src.database import Database
from src.common.identifiers import (
    ExecutionReport,
    HPBuyConfig,
    HPBuyOrdersPlaced,
    HPBuyPositionCreated,
    HPBuyPositionFilled,
    HPBuyPositionPartiallyFilled,
    OrderExecutionState,
)

logger = logging.getLogger("position_buy_v2")


class HPPositionBuyV2:
    """Handles buy order execution with clean OrderExecutionState tracking.

    This class manages only ORDER-level concerns:
    - Sending buy orders
    - Tracking fills
    - Cancelling orders

    Strategy-level lifecycle (IDLE → BUYING → BOUGHT) is managed by HpStrategyV2.

    V1 Compatibility: Maintains state_info for tests that check buy position state.
    """

    def __init__(
        self,
        client: BinanceClient,
        config: HPBuyConfig,
        db: Database,
        worker_queue: queue.Queue,
    ):
        """Initialize buy position handler.

        Args:
            client: Binance API client
            config: Buy configuration (symbol, budget, prices, etc.)
            db: Database for persistence
            worker_queue: Queue for portfolio events
        """
        self.client = client
        self.config = config
        self.db = db
        self.worker_queue = worker_queue

        # Order tracking
        self.buy_order: Optional[Order] = None
        self.execution_state = OrderExecutionState.PENDING

        # V1 compatibility: StateInfo for position-level state
        self.state_info = StateInfo(
            state=State.NEW,
            side=PositionSide.LONG,
        )

        # Prices for trigger logic
        self.trigger_price: float = 0.0
        self.cancel_price: float = 0.0

        self._calculate_trigger_prices()

    def _calculate_trigger_prices(self) -> None:
        """Calculate trigger and cancel prices from config.

        HP Manager Strategy:
        - trigger_price = buy_price × (1 + trigger_offset)
        - Example: buy_price=50000, trigger=1% → trigger_price=50500
        - When market price drops from 54000 → 50500, send limit buy at 50000
        - cancel_price = buy_price × (1 + cancel_offset) for cancelling if price rises too much
        """
        buy_price = self.config.buy_price
        trigger_offset = self.config.order_trigger  # e.g., 0.01 for 1%
        cancel_offset = self.config.order_cancel  # e.g., 0.02 for 2%

        # Trigger: buy_price * (1 + 1%) = 50500 (send order when price drops to this level)
        self.trigger_price = buy_price * (1 + trigger_offset)

        # Cancel: buy_price * (1 + 2%) = 51000 (cancel order if price rises above this)
        self.cancel_price = buy_price * (1 + cancel_offset)

        logger.info(
            f"[{self.config.hp_id}] Buy triggers: send @ {self.trigger_price}, "
            f"cancel @ {self.cancel_price}"
        )

    def prepare_buy_order(self) -> None:
        """Prepare buy order with calculated quantity and price."""
        symbol = self.config.symbol

        # Calculate quantity from budget
        cost_per_coin = self.config.buy_price
        quantity = self.config.budget / cost_per_coin

        # Adjust for symbol precision
        adjusted_quantity = symbol.adjust_quantity(quantity)
        adjusted_price = symbol.adjust_price(self.config.buy_price)

        self.buy_order = Order(
            quantity=adjusted_quantity,
            price=adjusted_price,
            quantity_stable=self.config.budget,
            status=ORDER_STATUS_NEW,
        )

        logger.info(
            f"[{self.config.hp_id}] Prepared buy order: "
            f"{adjusted_quantity} {self.config.coin} @ {adjusted_price}"
        )

    async def execute_buy(self) -> None:
        """Send buy order to exchange."""
        if not self.buy_order:
            raise ValueError("Buy order not prepared. Call prepare_buy_order() first.")

        # Calculate remaining quantity (account for partial fills from previous orders)
        remaining_quantity = self.buy_order.quantity - self.buy_order.realized_quantity

        logger.info(
            f"[{self.config.hp_id}] Executing buy: {remaining_quantity} "
            f"{self.config.coin} @ {self.buy_order.price}"
        )

        try:
            # Send order with remaining quantity
            order_response = await self.client.create_order(
                symbol=self.config.symbol.name,
                side="BUY",
                order_type=ORDER_TYPE_LIMIT,
                time_in_force=TIME_IN_FORCE_GTC,
                quantity=remaining_quantity,
                price=self.buy_order.price,
            )

            # Update order with new order ID and adjust quantity to remaining
            self.buy_order.order_id = order_response.get("orderId")
            self.buy_order.quantity = (
                remaining_quantity  # Update to actual sent quantity
            )
            self.buy_order.status = ORDER_STATUS_NEW
            self.execution_state = OrderExecutionState.OPEN

            logger.info(
                f"[{self.config.hp_id}] Buy order placed: {self.buy_order.order_id}"
            )

            # Trigger portfolio event (budget locked)
            self.worker_queue.put(
                HPBuyOrdersPlaced(
                    hp_id=self.config.hp_id,
                    coin=self.config.coin,
                    budget_amount=self.config.budget,
                    end_currency="USDC",  # Hardcoded for now
                )
            )

            # Update database
            await self.db.upsert_order(
                order=self.buy_order,
                hp_id=self.config.hp_id,
                side=self.config.symbol.name.replace(self.config.coin, ""),
            )

        except Exception as e:
            logger.error(f"[{self.config.hp_id}] Failed to execute buy: {e}")
            raise

    async def handle_execution_report(self, report: ExecutionReport) -> None:
        """Process order execution report."""
        if not self.buy_order or report.order_id != self.buy_order.order_id:
            return

        logger.info(
            f"[{self.config.hp_id}] Buy execution report: {report.current_order_status}"
        )

        # Update order status
        self.buy_order.status = report.current_order_status
        self.buy_order.realized_quantity = report.cumulative_filled_quantity

        if report.current_order_status == ORDER_STATUS_PARTIALLY_FILLED:
            self.execution_state = OrderExecutionState.PARTIALLY_FILLED
            self.state_info.state = State.PARTIALLY_BOUGHT  # V1 compatibility

            # Trigger portfolio event (partial fill)
            fill_increment = report.last_executed_quantity
            self.worker_queue.put(
                HPBuyPositionPartiallyFilled(
                    hp_id=self.config.hp_id,
                    coin=self.config.coin,
                    filled_quantity=fill_increment,
                    total_filled=self.buy_order.realized_quantity,
                    buy_price=report.last_executed_price,
                    partial_cost=fill_increment * report.last_executed_price,
                )
            )

            logger.info(
                f"[{self.config.hp_id}] Partial fill: {fill_increment} "
                f"(total: {self.buy_order.realized_quantity})"
            )

        elif report.current_order_status == ORDER_STATUS_FILLED:
            self.execution_state = OrderExecutionState.FILLED
            self.state_info.state = State.BOUGHT  # V1 compatibility

            # Trigger portfolio event (complete fill)
            self.worker_queue.put(
                HPBuyPositionFilled(
                    hp_id=self.config.hp_id,
                    coin=self.config.coin,
                    symbol=self.config.symbol.name,
                    quantity_bought=self.buy_order.realized_quantity,
                    buy_price=report.last_executed_price,
                    total_cost=self.buy_order.realized_quantity
                    * report.last_executed_price,
                )
            )

            logger.info(
                f"[{self.config.hp_id}] Buy complete: {self.buy_order.realized_quantity} "
                f"{self.config.coin}"
            )

        elif report.current_order_status == ORDER_STATUS_CANCELED:
            self.execution_state = OrderExecutionState.CANCELLED
            self.state_info.state = State.NEW  # V1 compatibility: back to NEW
            logger.info(f"[{self.config.hp_id}] Buy order cancelled")

        # Update database
        await self.db.upsert_order(
            order=self.buy_order,
            hp_id=self.config.hp_id,
            side=self.config.symbol.name.replace(self.config.coin, ""),
        )

    async def cancel_buy(self) -> None:
        """Cancel active buy order."""
        if not self.buy_order or self.buy_order.order_id is None:
            logger.warning(f"[{self.config.hp_id}] No order to cancel")
            return

        logger.info(
            f"[{self.config.hp_id}] Cancelling buy order: {self.buy_order.order_id}"
        )

        try:
            await self.client.cancel_order(
                symbol=self.config.symbol.name,
                order_id=self.buy_order.order_id,
            )

            self.buy_order.status = ORDER_STATUS_CANCELED
            self.execution_state = OrderExecutionState.CANCELLED

            # Update database
            await self.db.upsert_order(
                order=self.buy_order,
                hp_id=self.config.hp_id,
                side=self.config.symbol.name.replace(self.config.coin, ""),
            )

        except Exception as e:
            logger.error(f"[{self.config.hp_id}] Failed to cancel buy: {e}")
            raise

    def is_filled(self) -> bool:
        """Check if buy order is filled OR cancelled with partial inventory.
        
        In V2, we consider a buy "complete" (ready for selling) if:
        1. Order is fully filled, OR
        2. Order is cancelled but has partial inventory (realized_quantity > 0)
        
        This allows transitioning to BOUGHT state even with partial fills,
        enabling the sell strategy to work with the acquired inventory.
        """
        if self.execution_state == OrderExecutionState.FILLED:
            return True
        
        # If cancelled with partial inventory, consider it "complete" for selling
        if (
            self.execution_state == OrderExecutionState.CANCELLED
            and self.buy_order
            and self.buy_order.realized_quantity > 0
        ):
            return True
        
        return False

    def is_partially_filled(self) -> bool:
        """Check if buy order is partially filled."""
        return self.execution_state == OrderExecutionState.PARTIALLY_FILLED

    def get_filled_quantity(self) -> float:
        """Get the currently filled quantity."""
        if self.buy_order:
            return self.buy_order.realized_quantity
        return 0.0

    @property
    def data(self):
        """V1 compatibility: Provide data.state_info access for tests."""
        return self
