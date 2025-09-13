import asyncio
import queue
import logging
from typing import Optional, Callable
from transitions.extensions.asyncio import AsyncMachine
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
)
from src.common.symbol_info import SymbolInfo
from src.database import TradingDatabase
from src.identifiers import (
    AccountPosition,
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuyData,
    HPBuyPositionFilled,
    HPBuyPositionPartiallyFilled,
    HPPositionCancelled,
    HPSellConfig,
    HPSellData,
    HPSellPositionCreated,
    HPSellPositionPartiallyFilled,
    SellPosition,
    SellType,
    Signal,
    SignalUpdate,
    State,
    StateInfo,
    TickerUpdate,
    UiState,
    BinanceClient,
    PositionSide,
    HPSellPositionCompleted,
)
from src.gui.identifiers.spot import HPClose, HPGuiDataBuy, HPGuiDataSell, HPUpdate
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell

logger = logging.getLogger("HPStrategy")

# pylint: disable=unused-argument


class HpStrategy:
    def __init__(
        self,
        client: BinanceClient,
        balance: float,
        ui_queue: queue.Queue,
        worker_queue: queue.Queue,
        config_queue: queue.Queue,
        db: TradingDatabase,
        buy_position: HPPositionBuy,
        sell_position: HPPositionSell,
        initial_state: State = State.NEW,
        portfolio_event_callback: Optional[Callable] = None,
    ):
        self.client = client
        self.balance = balance
        self.db = db
        self.stop_event: asyncio.Event = asyncio.Event()
        self.worker_queue = worker_queue
        self.config_queue = config_queue
        self.ui_queue = ui_queue
        self.buy = buy_position
        self.sell = sell_position
        self.portfolio_event_callback = (
            portfolio_event_callback  # Callback to send HP events to portfolio
        )

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.execution_report: ExecutionReport = ExecutionReport()
        self.ticker_update: TickerUpdate = TickerUpdate()
        self.account_position: AccountPosition = AccountPosition()

        self.state = initial_state
        self.states = [
            State.NEW,
            State.BUYING,
            State.PARTIALLY_BOUGHT,
            State.BOUGHT,
            State.READY_TO_SELL,
            State.SELLING,
            State.PARTIALLY_SOLD,
            State.PART_SOLD_PART_BOUGHT,
            State.SOLD_PART_BOUGHT,
            State.SOLD,
            State.CLOSED,
        ]
        self.transitions = self._get_transitions()
        self.state_machine = AsyncMachine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=self.state,
            send_event=True,
            queued=True,
        )
        self.worker_active = False
        self.worker_task: Optional[asyncio.Task] = (
            None  # Track the worker task for cleanup
        )

    def _send_portfolio_event(self, event_name, event_data):
        """Send HP events to portfolio via callback."""
        if self.portfolio_event_callback:
            try:
                self.portfolio_event_callback(event_name, event_data)
            except Exception as e:
                logger.error(f"Failed to send portfolio event: {e}")

    def _get_transitions(self):
        return [
            {
                # No 1
                "trigger": "process_ticker",
                "source": State.NEW,
                "dest": State.BUYING,
                "conditions": "conditions_for_sending_buy_orders",
                "after": "send_buy_orders",
            },
            {
                # No 2
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.NEW,
                "conditions": "conditions_for_cancelling_unfilled_buy_orders",
                "after": "cancel_unfilled_buy_orders",
            },
            {
                # No 3
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.PARTIALLY_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_bought_orders",
                "after": "cancel_partially_bought_orders",
            },
            {
                # No 4
                "trigger": "process_ticker",
                "source": State.PARTIALLY_BOUGHT,
                "dest": State.BUYING,
                "conditions": "conditions_for_resending_partially_bought_position",
                "after": "resend_buy_orders",
            },
            {
                # No 5
                "trigger": "process_ticker",
                "source": State.PARTIALLY_BOUGHT,
                "dest": State.SELLING,
                "conditions": "conditions_for_sending_sell_orders_for_partially_bought_position",
                "after": "send_sell_order",
            },
            {
                # No 6
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.PARTIALLY_BOUGHT,
                "conditions": "conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position",
                "after": "cancel_unfilled_sell_orders",
            },
            {
                # No 7
                "trigger": "process_signal",
                "source": State.BUYING,
                "dest": State.BOUGHT,
                "conditions": "conditions_for_all_orders_filled_buy",
                "after": "close_filled_position_buy",
            },
            {
                # No x probably to allow msg to come when it is already bought.
                "trigger": "process_signal",
                "source": State.BOUGHT,
                "dest": State.BOUGHT,
                "after": "close_filled_position_buy",
            },
            {
                # No 8
                "trigger": "process_ticker",
                "source": State.BOUGHT,
                "dest": State.SELLING,
                "conditions": "conditions_for_sending_sell_orders",
                "before": "send_sell_order",
            },
            {
                # No 9
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.BOUGHT,
                "conditions": "conditions_for_cancelling_unfilled_sell_orders",
                "after": "cancel_unfilled_sell_orders",
            },
            {
                # No 10
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.PARTIALLY_SOLD,
                "conditions": "conditions_for_cancelling_partially_sold_orders",
                "after": "cancel_partially_sold_orders",
            },
            {
                # No 11
                "trigger": "process_ticker",
                "source": State.PARTIALLY_SOLD,
                "dest": State.SELLING,
                "conditions": "conditions_for_resending_partially_sold_orders",
                "after": "resend_sell_order",
            },
            {
                # No 12 - MOVED to after 18 to prevent race condition
                "trigger": "process_signal",
                "source": State.SELLING,
                "dest": State.SOLD_PART_BOUGHT,
                "conditions": "conditions_for_closing_sold_position_which_is_part_bought",
                "after": "close_sold_position_which_is_part_bought",
            },
            {
                # No 13 - Was 12, moved down to check SOLD_PART_BOUGHT first
                "trigger": "process_signal",
                "source": State.SELLING,
                "dest": State.SOLD,
                "conditions": "conditions_for_all_orders_filled_sell",
                "after": "close_filled_position_sell",
            },
            {
                # No 14 - Was 13
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.PART_SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_sold_and_bought_orders_sell_position",
                "after": "cancel_partially_sold_orders",
            },
            {
                # No 15 - Was 14
                "trigger": "process_ticker",
                "source": State.PART_SOLD_PART_BOUGHT,
                "dest": State.SELLING,
                "conditions": "conditions_for_resending_sell_orders_from_part_sold_and_bought_orders",
                "before": "resend_sell_order",
            },
            {
                # No 16 - Was 15
                "trigger": "process_ticker",
                "source": State.PART_SOLD_PART_BOUGHT,
                "dest": State.BUYING,
                "conditions": "conditions_for_resending_buy_orders_from_part_sold_and_bought_orders",
                "after": "resend_buy_orders",
            },
            {
                # No 17 - Was 16
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.PART_SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_sold_and_bought_orders_buy_position",
                "after": "cancel_partially_bought_orders",
            },
            {
                # No 18 - Was 17
                "trigger": "process_signal",
                "source": State.BUYING,
                "dest": State.PARTIALLY_SOLD,
                "conditions": "conditions_for_buying_fully_previously_partially_sold_position",
                "after": "close_filled_position_buy",
            },
            {
                # No 19
                "trigger": "process_ticker",
                "source": State.SOLD_PART_BOUGHT,
                "dest": State.BUYING,
                "conditions": "conditions_for_resending_buy_orders_for_sold_position",
                "after": "resend_buy_orders",
            },
            {
                # No 20
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_buy_orders_to_sold_part_bought",
                "after": "cancel_partially_bought_orders",
            },
            {
                "trigger": "process_order",
                "source": State.BUYING,
                "dest": "=",
                "conditions": "conditions_for_order_filled_buy",
                "after": "handle_order_filled_buy",
            },
            {
                "trigger": "process_order",
                "source": State.BUYING,
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled_buy",
                "before": "handle_order_partially_filled_buy",
            },
            {
                "trigger": "process_order",
                "source": State.SELLING,
                "dest": "=",
                "conditions": "conditions_for_order_filled_sell",
                "after": "handle_order_filled_sell",
            },
            {
                "trigger": "process_order",
                "source": State.SELLING,
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled_sell",
                "before": "handle_order_partially_filled_sell",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "confirm_new_order",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "confirm_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "confirm_expired_order",
            },
            {
                "trigger": "process_ticker",
                "source": [State.CLOSED, State.SOLD],
                "dest": "=",
                # No "after" action - just consume the ticker event gracefully
                # This prevents state machine errors during teardown
            },
        ]

    def calculate_remaining_quantity(self) -> float:
        if not self.buy.orders:
            return self._calculate_from_sell_only()
        return self._calculate_from_buy_and_sell()

    def _calculate_from_buy_and_sell(self) -> float:
        total_bought = sum(order.realized_quantity for order in self.buy.orders)

        logger.info("Number of sell positions: %s", len(self.sell.sell_positions))

        if len(self.sell.sell_positions) == 1:
            sold = self.sell.sell_positions[0].sell_order.realized_quantity
        elif len(self.sell.sell_positions) == 2:
            # Placeholding logic: use second leg’s executed quantity as final sold
            sold = self.sell.sell_positions[1].sell_order.realized_quantity
        else:
            sold = 0

        return max(0.0, total_bought - sold)

    def _calculate_from_sell_only(self) -> float:
        # Used when sell is started independently (inventory sell)
        # Return the original quantity, not remaining quantity
        return self.sell.current_position.config.quantity

    def build_hp_update_from_orders(
        self,
        symbol_info: SymbolInfo,
        current_price: Optional[float] = None,
    ) -> HPUpdate:
        """Build HP update data from current orders and positions."""
        # Determine the appropriate buy price
        if self.buy.orders:
            all_unrealized = all(
                order.realized_quantity == 0.0 for order in self.buy.orders
            )
            if all_unrealized:
                buy_price = self.buy.data.config.price_high
            else:
                buy_price = self.buy.calculate_avg_buy_price()
        else:
            # If no buy orders exist, use the original buy configuration price
            # If that's not available or is 0, fall back to sell config buy_price
            if (
                hasattr(self.buy.data, "config")
                and hasattr(self.buy.data.config, "price_high")
                and self.buy.data.config.price_high > 0
            ):
                buy_price = self.buy.data.config.price_high
            else:
                buy_price = self.sell.current_position.config.buy_price

        logger.info("HP update buy price: %s", buy_price)

        # logger.info("BUY PRICE: %s", buy_price)

        quantity = symbol_info.adjust_quantity(self.calculate_remaining_quantity())

        quantity_usd = symbol_info.adjust_price(
            float(quantity) * float(buy_price) if buy_price else 0.0
        )

        logger.info("quantity: %s, q usd: %s", quantity, quantity_usd)

        net = None
        net_percent = None
        if current_price and buy_price and quantity:
            # Calculate net profit/loss in USD
            net = symbol_info.adjust_price((current_price - buy_price) * quantity)
            # Calculate percentage change
            net_percent = round(((current_price / buy_price) - 1) * 100, 2)

        hp_id = (
            self.sell.current_position.config.hp_id
            if not self.buy.orders
            else self.buy.data.config.hp_id
        )
        coin = (
            self.sell.current_position.config.coin
            if not self.buy.orders
            else self.buy.data.config.coin
        )

        # Calculate total bought quantity across all cycles by querying database
        if self.buy.orders:
            try:
                # Get all filled buy orders for this HP from database to get cumulative total
                import asyncio
                from src.database.trading_database import TradingDatabase

                db = TradingDatabase()

                # Try different approaches for async call in sync context
                try:
                    # Check if we're in an event loop
                    loop = asyncio.get_running_loop()
                    # If we get here, we're in an event loop, but we can't use asyncio.run()
                    # For now, skip DB lookup and use fallback
                    logger.warning(
                        "Already in event loop, using current cycle total only"
                    )
                    total_quantity = sum(
                        order.realized_quantity for order in self.buy.orders
                    )
                except RuntimeError:
                    # Not in an event loop, safe to use asyncio.run
                    all_buy_orders = asyncio.run(
                        db.get_orders_by_position_id(self.buy.data.config.hp_id)
                    )
                    total_quantity = sum(
                        order.realized_quantity
                        for order in all_buy_orders
                        if order.status in ["FILLED", "PARTIALLY_FILLED"]
                    )
                    logger.info(
                        "Total quantity from DB (all cycles): %s", total_quantity
                    )
            except Exception as e:
                logger.warning(
                    "Failed to get total quantity from DB, using current cycle: %s", e
                )
                # Fallback to current cycle only
                total_quantity = sum(
                    order.realized_quantity for order in self.buy.orders
                )
        else:
            total_quantity = self.sell.current_position.config.quantity

        logger.info("Total quantity: %s", total_quantity)

        expected_return = None
        if buy_price and self.sell.current_position.config.sell_price:
            expected_return = symbol_info.adjust_price(
                (self.sell.current_position.config.sell_price - buy_price)
                * total_quantity
            )
            logger.info("Expected return : %s", expected_return)

        # Get sell order realized quantity if available
        sell_realized_quantity = None
        if hasattr(self.sell, "current_position") and self.sell.current_position:
            if (
                hasattr(self.sell.current_position, "sell_order")
                and self.sell.current_position.sell_order
            ):
                sell_realized_quantity = (
                    self.sell.current_position.sell_order.realized_quantity
                )

        # Calculate expected quantity from budget and price configuration
        # For DCA mode, this is the total across all orders
        expected_qty = 0.0
        if (
            hasattr(self.buy.data.config, "budget")
            and hasattr(self.buy.data.config, "price_high")
            and hasattr(self.buy.data.config, "price_low")
            and hasattr(self.buy.data.config, "mode")
            and self.buy.data.config.budget > 0
        ):

            if self.buy.data.config.mode == "DCA":
                # DCA calculation: sum of quantities across all price levels
                num_orders = 3
                min_budget_for_max_orders = num_orders * symbol_info.min_notional

                if self.buy.data.config.budget >= min_budget_for_max_orders:
                    order_quantity_stable = self.buy.data.config.budget / num_orders
                else:
                    order_quantity_stable = symbol_info.min_notional
                    num_orders = int(
                        self.buy.data.config.budget / symbol_info.min_notional
                    )
                    num_orders = num_orders if num_orders % 2 == 1 else num_orders - 1

                if num_orders == 1:
                    # Single order fallback
                    expected_qty = (
                        self.buy.data.config.budget / self.buy.data.config.price_high
                    )
                else:
                    # Calculate total expected quantity across all DCA orders
                    price_increment = (
                        self.buy.data.config.price_high - self.buy.data.config.price_low
                    ) / (num_orders - 1)
                    for i in range(num_orders):
                        order_price = (
                            self.buy.data.config.price_high - i * price_increment
                        )
                        if order_price > 0:
                            expected_qty += order_quantity_stable / order_price

                    # Round to symbol precision for consistent formatting
                    if hasattr(symbol_info, "precision"):
                        expected_qty = round(expected_qty, symbol_info.precision)
            else:
                # SINGLE mode: budget / price_high
                expected_qty = (
                    self.buy.data.config.budget / self.buy.data.config.price_high
                )

        # Calculate sum of all buy order quantities
        orders_total_qty = sum(order.quantity for order in self.buy.orders)

        hp_update = HPUpdate(
            hp_id=hp_id,
            coin=coin,
            symbol_info=symbol_info,
            quantity=quantity,
            quantity_usd=quantity_usd,
            realized_quantity=sell_realized_quantity,  # Add sell order realized quantity
            total_quantity=total_quantity,  # Add total bought quantity
            expected_quantity=expected_qty,  # Add total expected quantity based on budget
            orders_total_quantity=orders_total_qty,  # Add sum of all buy order quantities
            buy_price=buy_price,
            sell_price=self.sell.current_position.config.sell_price,
            current_price=current_price,
            net=net,
            net_percent=net_percent,
            state=self.state,
            expected_return=expected_return,
            is_child=self.sell.current_position.config.is_child,
            side="BUY",  # Set side to BUY for buy positions
        )

        return hp_update

    def send_buy_position_to_ui(self):
        """Send buy position update to UI."""
        hp_update = self.build_hp_update_from_orders(
            symbol_info=self.buy.data.config.symbol_info
        )
        # Set specific child ID for buy operations
        parent_id = str(self.buy.data.config.hp_id)
        hp_update.hp_id = f"{parent_id}_BUY"

        # Set actual buy operation state for proper child state determination
        # This comes from the actual buy state, not the strategy state
        buy_state = self.buy.data.state_info.state.value
        hp_update.buy_operation_state = buy_state

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=hp_update,
            )
        )

    def send_sell_position_to_ui(self):
        """Send sell position update to UI."""
        hp_update = self.build_hp_update_from_orders(
            symbol_info=self.sell.current_position.config.symbol_info
        )

        # Set specific child ID for sell operations
        parent_id = str(self.sell.current_position.config.hp_id)
        # For two-hop trades (child positions), keep the original ID (e.g., 1000a)
        # For convert operations, append _CONVERT suffix (e.g., 1000_CONVERT)
        # For regular trades, append _SELL suffix (e.g., 1000_SELL)
        if self.sell.current_position.config.is_child:
            hp_update.hp_id = parent_id
        elif self.sell.current_position.sell_type == SellType.CONVERT:
            hp_update.hp_id = f"{parent_id}_CONVERT"
        else:
            hp_update.hp_id = f"{parent_id}_SELL"

        # Add sell state information for UI sell child state processing
        hp_update.sell_state = self.sell.current_position.state_info.state.value

        data = HPGuiDataSell(
            data=HPSellData(
                config=self.sell.current_position.config,
                state_info=self.sell.current_position.state_info,
            ),
            hp_update=hp_update,
        )
        self.ui_queue.put_nowait(data)
        logger.info("Send HPGuiDataSell to UI: %s", data)

    def calculate_trigger_send_orders_price_buy(self):

        logger.info(self.buy.orders)

        price = (
            self.buy.data.config.symbol_info.adjust_price(
                max(
                    order.price
                    for order in self.buy.orders
                    if order.status != ORDER_STATUS_FILLED
                )
                * (1 + self.buy.data.config.order_trigger / 100)
            )
            if any(order.status != ORDER_STATUS_FILLED for order in self.buy.orders)
            else 0.0
        )
        # logger.info(
        #     "Calculated price for trigger send orders price buy: %s, config: %s",
        #     price,
        #     self.buy.data.config,
        # )
        return price

    def get_remaining_quantity_buy(self, *args, **kwargs) -> float:
        """Calculate remaining quantity for buy orders."""
        rem_quant = 0.0
        for order in self.buy.orders:
            rem_quant += order.quantity_stable - order.quantity_stable * (
                order.realized_quantity / order.quantity
            )
        return rem_quant

    def conditions_for_sending_buy_orders(self, *args, **kwargs) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_buy()
        condition = (
            self.state == State.NEW
            and self.buy.data.state_info.state == State.NEW
            and self.ticker_update.last_price <= trigger_send_orders_price
            and self.balance >= self.buy.data.config.budget
        )
        if condition:
            logger.info(
                "[Send buy orders] %s, side: %s, state: %s, budget: %s, balance: %s "
                "price trigger: %s last price: %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
                self.state,
                self.buy.data.config.budget,
                self.balance,
                trigger_send_orders_price,
                self.ticker_update.last_price,
            )
        if self.balance < self.buy.data.config.budget:
            logger.warning("Ni mo hajsu")
        # logger.info(
        #     "[Send buy orders]: %s, %s, side: %s, state: %s, budget: %s, balance: %s "
        #     "price trigger: %s last price: %s",
        #     condition,
        #     self.buy.data.config.symbol_info.symbol,
        #     self.buy.data.state_info.side,
        #     self.state,
        #     self.buy.data.config.budget,
        #     self.balance,
        #     trigger_send_orders_price,
        #     self.ticker_update.last_price,
        # )

        return condition

    async def send_buy_orders(self, *args, **kwargs) -> None:
        logger.info("Sending %s BUY", self.buy.data.config.symbol_info.symbol)
        self.balance -= self.get_remaining_quantity_buy()

        self.buy.prepare_orders()
        self.buy.orders = await self.buy.open_position()
        self.state = State.BUYING
        self.buy.data.state_info.state = State.NEW

        self.buy.data.state_info.get_completeness(self.buy.orders)

        self.buy.data.state_info.ui_state = UiState.OPEN

        logger.info("Orders sent, updating DB: %s", self.buy.orders)

        for order in self.buy.orders:
            await self.db.upsert_order(
                order=order,
                hp_id=self.buy.data.config.hp_id,
                side=self.buy.data.state_info.side,
            )

        logger.info(
            "Orders sent, updating DB with price level: %s",
            self.buy.data.state_info,
        )
        await self.db.upsert_buy_price_level(
            data=self.buy.data, strategy_state=self.state
        )
        self.send_buy_position_to_ui()

    def conditions_for_cancelling_unfilled_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.buy.data.state_info.state == State.NEW
            and self.sell.current_position.state_info.state == State.NEW
            and self.state == State.BUYING
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
            and all(order.status == ORDER_STATUS_NEW for order in self.buy.orders)
        )
        if condition:
            logger.info(
                "[Cancel Unfilled BUY] %s, last price: %s, trig price: %s, state: %s, buy state: %s",
                self.buy.data.config.symbol_info.symbol,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
                self.state,
                self.buy.data.state_info.state,
            )

        return condition

    async def cancel_unfilled_buy_orders(self, *args, **kwargs) -> None:
        logger.info("Cancelling %s", self.buy.data.state_info.side.value)
        logger.info("Orders: %s", self.buy.orders)
        self.balance += self.get_remaining_quantity_buy()
        await self.buy.cancel_position()

        # Send HP position cancelled event to portfolio (for buy cancellations)
        total_quantity = sum(order.quantity for order in self.buy.orders)
        hp_cancelled = HPPositionCancelled(
            hp_id=self.buy.data.config.hp_id,
            coin=self.buy.data.config.coin,
            quantity=total_quantity,
            position_type="BUY",
        )
        self._send_portfolio_event(EventName.HP_POSITION_CANCELLED, hp_cancelled)

        self.buy.data.state_info.state = State.NEW

        self.send_buy_position_to_ui()

    def conditions_for_cancelling_partially_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
        )
        if condition:
            logger.info(
                "[Cancel Part Filled BUY] %s, last price: %s, trig price: %s",
                self.buy.data.config.symbol_info.symbol,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
            )

        return condition

    async def cancel_partially_bought_orders(self, *args, **kwargs) -> None:
        logger.info("Cancelling %s", self.buy.data.state_info.side.value)
        logger.info("Orders: %s", self.buy.orders)
        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT
        self.balance += self.get_remaining_quantity_buy()
        await self.buy.cancel_position()

        self.send_buy_position_to_ui()

    def conditions_for_resending_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_buy()
        remaining_quantity = self.get_remaining_quantity_buy()

        condition = (
            self.state == State.PARTIALLY_BOUGHT
            and self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.ticker_update.last_price <= trigger_send_orders_price
            and self.balance
            >= remaining_quantity  # Check if we have enough balance for remaining orders
        )
        if condition:
            logger.info(
                "[Resend buy orders] %s, side: %s, state: %s, budget: %s, balance: %s"
                "price trigger: %s last price: %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
                self.state,
                self.buy.data.config.budget,
                self.balance,
                trigger_send_orders_price,
                self.ticker_update.last_price,
            )

        return condition

    async def resend_buy_orders(self, *args, **kwargs) -> None:
        logger.info("Resending %s BUY", self.buy.data.config.symbol_info.symbol)
        self.balance -= self.get_remaining_quantity_buy()

        await self.buy.open_position()
        self.state = State.BUYING
        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT
        self.buy.data.state_info.get_completeness(self.buy.orders)
        self.buy.data.state_info.ui_state = UiState.OPEN

        logger.info("Will update orders: %s", self.buy.orders)

        for order in self.buy.orders:
            await self.db.upsert_order(
                order=order,
                hp_id=self.buy.data.config.hp_id,
                side=self.buy.data.state_info.side,
            )
        await self.db.upsert_buy_price_level(
            data=self.buy.data, strategy_state=self.state
        )

        self.send_buy_position_to_ui()

    def calculate_trigger_send_orders_price_sell(self) -> float:
        sell_price = self.sell.original_position.config.sell_price
        if sell_price is None:
            return 0.0  # or raise an error depending on your logic

        adjusted = (
            self.sell.original_position.config.symbol_info.adjust_price(
                0.96 * sell_price
            )
            if self.sell.current_position.sell_type == SellType.DIRECT
            else self.sell.original_position.config.symbol_info.adjust_price(sell_price)
        )
        return float(adjusted)

    def conditions_for_sending_sell_orders_for_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
            and self.ticker_update.symbol
            == self.sell.current_position.config.symbol_info.symbol
        )
        if condition:
            logger.info(
                "[Send sell orders] hp id: %s, %s, side: %s, state: %s",
                self.sell.current_position.config.hp_id,
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.side,
                self.sell.current_position.state_info.state,
            )

        return condition

    async def send_sell_order(self, *args, **kwargs) -> None:
        if self.sell.current_position.config.symbol_info.is_convert_only:
            await self.convert_position()
            self.send_sell_position_to_ui()
            return

        logger.info(
            "Sending %s SELL", self.sell.current_position.config.symbol_info.symbol
        )

        await self.sell.open_position()

        # NOTE: Don't send HP_SELL_POSITION_CREATED here - already sent during position initialization
        # to avoid double inventory locking

        self.state = State.SELLING
        self.sell.current_position.state_info.get_completeness(
            self.sell.current_position.sell_order
        )
        self.sell.current_position.state_info.ui_state = UiState.OPEN

        await self.db.upsert_order(
            order=self.sell.current_position.sell_order,
            side=self.sell.current_position.state_info.side,
            hp_id=self.sell.current_position.config.hp_id,
        )
        # Persist SELLING state in DB when sending sell order
        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )

        self.send_sell_position_to_ui()

        if self.sell.current_position.sell_order.status == ORDER_STATUS_FILLED:
            self.sell.current_position.state_info.state = State.SOLD
            self.sell.current_position.state_info.ui_state = UiState.CLOSED
            self.sell.current_position.state_info.completeness = 1.0

            signal = Signal.HP_ALL_ORDERS_FILLED
            logger.info("All SELL orders filled, sending: %s", signal)
            self.worker_queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

    async def convert_position(self, max_spread: float = 0.01) -> None:
        symbol_info = self.sell.current_position.config.symbol_info
        if not symbol_info.is_convert_only:
            logger.warning("Conversion not required for symbol: %s", symbol_info.symbol)
            return

        from_asset = symbol_info.extract_coin_from_symbol(symbol_info.symbol)
        to_asset = self.sell.current_position.config.end_currency or "USDC"
        quantity = symbol_info.format_quantity(
            self.sell.current_position.config.quantity
        )

        try:
            logger.info(
                "Requesting convert quote from %s to %s, quantity: %s",
                from_asset,
                to_asset,
                quantity,
            )

            quote = await self.client.convert_request_quote(
                fromAsset=from_asset,
                toAsset=to_asset,
                fromAmount=quantity,
            )

            quote_id = quote["quoteId"]
            quoted_amount = float(quote["toAmount"])
            effective_price = quoted_amount / float(quote["fromAmount"])

            # Validate against price via USDT if necessary
            usdt_pair = f"{from_asset}USDT"
            market_price_usdt = self.sell.price_resolver.latest_prices.get(usdt_pair)

            if not market_price_usdt:
                logger.warning(
                    "No market price available for %s, skipping convert", usdt_pair
                )
                return

            spread = abs((market_price_usdt - effective_price) / market_price_usdt)
            logger.info(
                "Quote effective price: %.6f, market price (USDT): %.6f, spread: %.2f%%",
                effective_price,
                market_price_usdt,
                spread * 100,
            )

            if spread > max_spread:
                logger.warning(
                    "Spread %.2f%% exceeds max allowed (%.2f%%), skipping convert",
                    spread * 100,
                    max_spread * 100,
                )
                return

            accept = await self.client.convert_accept_quote(quoteId=quote_id)
            logger.info("Quote accepted: %s", accept)

            self.sell.current_position.sell_order.status = ORDER_STATUS_FILLED
            self.sell.current_position.sell_order.realized_quantity = float(quantity)
            self.sell.current_position.state_info.state = State.SOLD
            self.state = State.SOLD
            self.sell.current_position.state_info.ui_state = UiState.CLOSED
            self.sell.current_position.state_info.completeness = 1.0

            # Emit a partial fill event (treat full convert as a single fill) so portfolio can
            # reduce inventory immediately under the new "fills mutate inventory" rule.
            if self.portfolio_event_callback:
                try:
                    self.portfolio_event_callback(
                        EventName.HP_SELL_POSITION_PARTIALLY_FILLED,
                        HPSellPositionPartiallyFilled(
                            hp_id=self.sell.current_position.config.hp_id,
                            coin=self.sell.current_position.config.coin,
                            filled_quantity=float(quantity),
                            total_filled=float(quantity),
                        ),
                    )
                except Exception as e:
                    logger.error(
                        "Failed sending convert partial fill event for %s: %s",
                        self.sell.current_position.config.hp_id,
                        e,
                    )

            # Send HP sell position completed event to portfolio
            end_currency_received = quoted_amount  # Already calculated from convert API
            hp_sell_completed = HPSellPositionCompleted(
                hp_id=self.sell.current_position.config.hp_id,
                coin=self.sell.current_position.config.coin,
                quantity_sold=float(quantity),
                buy_price=self.sell.current_position.config.buy_price,  # Add missing buy price
                sell_price=self.sell.current_position.config.sell_price,  # Add missing sell price
                end_currency=to_asset,  # Use the actual to_asset from convert
                end_currency_received=end_currency_received,
            )
            logger.info(
                "Sending HP sell position completed from CONVERT POSITION: %s",
                hp_sell_completed,
            )
            self._send_portfolio_event(
                EventName.HP_SELL_POSITION_COMPLETED, hp_sell_completed
            )

            signal = Signal.HP_ALL_ORDERS_FILLED
            logger.info("All SELL orders filled, sending: %s", signal)
            self.worker_queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

        except Exception as e:
            logger.error("Convert failed from %s to %s: %s", from_asset, to_asset, e)

    def conditions_for_all_orders_filled_buy(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.BUYING
            and self.sell.current_position.state_info.state == State.NEW
            and all(order.status == ORDER_STATUS_FILLED for order in self.buy.orders)
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            logger.info(
                "[All orders filled] %s %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
            )
        return condition

    async def close_filled_position_buy(self, *args, **kwargs) -> None:
        logger.info("All order filled, archiving position")

        self.buy.data.state_info.state = State.BOUGHT
        self.buy.data.state_info.get_completeness(self.buy.orders)
        self.buy.data.state_info.ui_state = UiState.CLOSED

        logger.info("Sending HP update with state BOUGHT: %s", self.state)
        self.send_buy_position_to_ui()

        # Send HP buy position filled event to portfolio for inventory addition
        total_quantity_bought = sum(
            order.realized_quantity for order in self.buy.orders
        )
        total_cost = sum(
            order.realized_quantity * order.price for order in self.buy.orders
        )
        average_buy_price = (
            total_cost / total_quantity_bought if total_quantity_bought > 0 else 0
        )

        hp_buy_filled = HPBuyPositionFilled(
            hp_id=self.buy.data.config.hp_id,
            coin=self.buy.data.config.coin,
            quantity_bought=total_quantity_bought,
            buy_price=average_buy_price,
            total_cost=total_cost,
        )
        self._send_portfolio_event(EventName.HP_BUY_POSITION_FILLED, hp_buy_filled)

        await self.db.upsert_buy_price_level(data=self.buy.data)

        if self.sell.current_position.state_info.state == State.PARTIALLY_SOLD:
            await self.db.upsert_sell_price_level(
                data=self.sell.current_position, strategy_state=State.PARTIALLY_SOLD
            )

    def conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and self.ticker_update.symbol
            == self.sell.current_position.config.symbol_info.symbol
            and self.sell.current_position.sell_order.status == ORDER_STATUS_NEW
        )
        if condition:
            logger.info(
                "[Cancel Unfilled SELL] %s, last price: %s, trig price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_unfilled_sell_orders(self, *args, **kwargs) -> None:
        logger.info("Cancelling %s", self.sell.current_position.state_info.side.value)
        await self.sell.cancel_position()

        # Send HP position cancelled event to portfolio for quantity unlocking
        hp_cancelled = HPPositionCancelled(
            hp_id=self.sell.current_position.config.hp_id,
            coin=self.sell.current_position.config.coin,
            quantity=self.sell.current_position.sell_order.quantity,
            position_type="SELL",
        )
        self._send_portfolio_event(EventName.HP_POSITION_CANCELLED, hp_cancelled)

        self.state = (
            State.BOUGHT
            if all(order.status == ORDER_STATUS_FILLED for order in self.buy.orders)
            else State.PARTIALLY_BOUGHT
        )
        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )
        self.send_sell_position_to_ui()

    def conditions_for_sending_sell_orders(self, *args, **kwargs) -> bool:
        """Check if conditions are met for sending sell orders."""
        trig_ord_price: float = self.calculate_trigger_send_orders_price_sell()

        assert isinstance(self.buy.data.config, HPBuyConfig)
        assert isinstance(self.sell.current_position.config, HPSellConfig)
        price = self.sell.current_position.config.sell_price
        condition = (
            self.sell.current_position.state_info.state == State.NEW
            and price is not None
            and price > 0
            and self.ticker_update.last_price >= trig_ord_price
            and self.ticker_update.symbol
            == self.sell.original_position.config.symbol_info.symbol
        )
        if condition:
            logger.info(
                "[Send sell orders]: %s hp id: %s, %s, side: %s, state: %s",
                condition,
                self.sell.current_position.config.hp_id,
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.side,
                self.sell.current_position.state_info.state,
            )
        # if (
        #     self.ticker_update.symbol
        #     == self.sell.original_position.config.symbol_info.symbol
        # ):
        #     logger.info(
        #         "[Send sell orders]: %s hp id: %s, %s, side: %s, state: %s, trigger price: %s, ticker price: %s, ticker symbol: %s, orig sell data symbol: %s",
        #         condition,
        #         self.sell.current_position.config.hp_id,
        #         self.sell.current_position.config.symbol_info.symbol,
        #         self.sell.current_position.state_info.side,
        #         self.sell.current_position.state_info.state,
        #         trig_ord_price,
        #         self.ticker_update.last_price,
        #         self.ticker_update.symbol,
        #         self.sell.original_position.config.symbol_info.symbol,
        #     )
        return condition

    def conditions_for_cancelling_unfilled_sell_orders(self, *args, **kwargs) -> bool:
        sell_cancel_order_price: float = (
            self.calculate_trigger_cancel_orders_price_sell()
        )
        condition = (
            self.buy.data.state_info.state == State.BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and (self.ticker_update.last_price <= sell_cancel_order_price)
            and (
                self.ticker_update.symbol
                == self.sell.current_position.config.symbol_info.symbol
            )
        )
        if condition:
            logger.info(
                "[Cancel Unfilled SELL] %s, last price: %s, trig price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.ticker_update.last_price,
                sell_cancel_order_price,
            )

        return condition

    def conditions_for_resending_partially_sold_orders(self, *args, **kwargs) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_sell()
        condition = (
            self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.buy.data.state_info.state == State.BOUGHT
            and self.ticker_update.last_price >= trigger_send_orders_price
            and self.ticker_update.symbol
            == self.sell.current_position.config.symbol_info.symbol
        )
        assert (
            self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
        ), "sell state is wrong"
        assert self.buy.data.state_info.state == State.BOUGHT, "buy state is wrong"
        assert (
            self.ticker_update.last_price >= trigger_send_orders_price
        ), f"price condition is wrong, last price: {self.ticker_update.last_price}, trigger: {trigger_send_orders_price}"
        assert condition
        if condition:
            logger.info(
                "[Resend sell] %s, sell state: %s, state: %s, balance: %s, price trig: %s last price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.state.value,
                self.state.value,
                self.balance,
                trigger_send_orders_price,
                self.ticker_update.last_price,
            )

        return condition

    async def resend_sell_order(self, *args, **kwargs) -> None:
        logger.info("Sending %s SELL")

        await self.sell.open_position()
        self.state = State.SELLING
        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD
        self.sell.current_position.state_info.get_completeness(
            self.sell.current_position.sell_order
        )
        self.sell.current_position.state_info.ui_state = UiState.OPEN

        logger.info("Will update order: %s", self.sell.current_position.sell_order)

        await self.db.upsert_order(
            order=self.sell.current_position.sell_order,
            side=self.sell.current_position.state_info.side,
            hp_id=self.sell.current_position.config.hp_id,
        )
        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )

        self.send_sell_position_to_ui()

    def conditions_for_cancelling_partially_sold_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and self.ticker_update.symbol
            == self.sell.current_position.config.symbol_info.symbol
            and self.sell.current_position.sell_order.status != ORDER_STATUS_NEW
            and self.buy.data.state_info.state == State.BOUGHT
        )
        if condition:
            logger.info(
                "[Cancel Part Filled SELL] %s, last price: %s, trig price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_partially_sold_orders(self, *args, **kwargs) -> None:
        logger.info("Cancelling %s", self.sell.current_position.state_info.side.value)
        await self.sell.cancel_position()
        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        self.send_sell_position_to_ui()

    def conditions_for_all_orders_filled_sell(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.SELLING
            and self.buy.data.state_info.state == State.BOUGHT
            and self.sell.current_position.sell_order.status == ORDER_STATUS_FILLED
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        logger.info(
            "[All orders filled] %s %s",
            self.sell.current_position.config.symbol_info.symbol,
            self.sell.current_position.state_info.side,
        )
        return condition

    async def close_filled_position_sell(self, *args, **kwargs) -> None:
        logger.info("All order filled, archiving position")

        self.sell.current_position.state_info.state = State.SOLD
        self.sell.current_position.state_info.ui_state = UiState.CLOSED
        self.sell.current_position.state_info.get_completeness(
            self.sell.current_position.sell_order
        )

        # Send HP sell position completed event to portfolio
        end_currency_received = (
            self.sell.current_position.sell_order.realized_quantity
            * self.sell.current_position.config.sell_price
        )
        hp_sell_completed = HPSellPositionCompleted(
            hp_id=self.sell.current_position.config.hp_id,
            coin=self.sell.current_position.config.coin,
            quantity_sold=self.sell.current_position.sell_order.realized_quantity,
            buy_price=self.sell.current_position.config.buy_price,  # Add missing buy price
            sell_price=self.sell.current_position.config.sell_price,  # Add missing sell price
            end_currency=self.sell.current_position.config.end_currency,  # Use actual end_currency from config
            end_currency_received=end_currency_received,
        )

        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )
        self.send_sell_position_to_ui()
        if len(self.sell.sell_positions) == 1:
            # Check if this is a convert operation - if so, completion event was already sent
            is_convert_operation = (
                self.sell.current_position.config.symbol_info.is_convert_only
            )
            if is_convert_operation:
                logger.info(
                    "Skipping duplicate completion event for convert operation: %s",
                    self.sell.current_position.config.hp_id,
                )
            else:
                # For direct sell (single position), send completion event instead of HPClose
                logger.info(
                    "Sending HP sell position completed from CLOSE FILLED POSITION SELL (direct): %s",
                    hp_sell_completed,
                )
                self._send_portfolio_event(
                    EventName.HP_SELL_POSITION_COMPLETED, hp_sell_completed
                )

            # Also send HPClose to complete the position lifecycle
            self.config_queue.put_nowait(
                HPClose(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                )
            )
        if (
            len(self.sell.sell_positions) == 2
            and self.sell.current_position is self.sell.sell_positions[1]
        ):
            self.sell.original_position.state_info.state = State.SOLD
            self.sell.original_position.sell_order.status = ORDER_STATUS_FILLED
            self.sell.original_position.state_info.completeness = 1.0

            self.sell.current_position = SellPosition(
                sell_order=self.sell.original_position.sell_order,
                config=self.sell.original_position.config,
                state_info=self.sell.original_position.state_info,
            )
            data = HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.original_position.config,
                    state_info=self.sell.original_position.state_info,
                ),
                hp_update=self.build_hp_update_from_orders(
                    symbol_info=self.sell.original_position.config.symbol_info
                ),
            )
            self.ui_queue.put_nowait(data)
            logger.info("Send HPGuiDataSell to UI: %s", data)

            # For successful multihop completion, send HPSellPositionCompleted but NOT HPClose
            # HPClose would trigger cancellation logic instead of completion
            logger.info(
                "Sending HP sell position completed from CLOSE FILLED POSITION SELL: %s",
                hp_sell_completed,
            )
            self._send_portfolio_event(
                EventName.HP_SELL_POSITION_COMPLETED, hp_sell_completed
            )

            # Also send completion event for parent position (original multihop position)
            parent_hp_sell_completed = HPSellPositionCompleted(
                hp_id=self.sell.original_position.config.hp_id,
                coin=self.sell.original_position.config.coin,
                quantity_sold=self.sell.original_position.config.quantity,
                buy_price=self.sell.original_position.config.buy_price,
                sell_price=self.sell.original_position.config.sell_price,
                end_currency=self.sell.original_position.config.end_currency,
                end_currency_received=end_currency_received,  # Use same end_currency_received as child
            )
            logger.info(
                "Sending HP sell position completed for PARENT multihop position: %s",
                parent_hp_sell_completed,
            )
            self._send_portfolio_event(
                EventName.HP_SELL_POSITION_COMPLETED, parent_hp_sell_completed
            )

        if (
            len(self.sell.sell_positions) == 2
            and self.sell.current_position is self.sell.sell_positions[0]
        ):
            self.send_sell_position_to_ui()
            logger.info(
                "First sell position from two hop trade closed, assigning second one as current one."
            )
            self.sell.current_position = self.sell.sell_positions[1]
            assert isinstance(self.sell.current_position, SellPosition)
            self.buy.orders = []
            logger.info(
                "crnt pos coin: %s, sell order: %s",
                self.sell.current_position.config.coin,
                self.sell.current_position.sell_order,
            )
            self.buy.data.config.coin = self.sell.current_position.config.coin
            self.sell.current_position.state_info.state = State.SELLING

            await self.send_sell_order()

    def conditions_for_cancelling_partially_sold_and_bought_orders_sell_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and self.ticker_update.symbol
            == self.sell.current_position.config.symbol_info.symbol
        )
        if condition:
            logger.info(
                "[Cancel Part Filled SELL] %s, last price: %s, trigger price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_sell_part_sold_part_bought(self, *args, **kwargs) -> None:
        logger.info("Cancelling %s", self.sell.current_position.state_info.side.value)
        await self.sell.cancel_position()
        self.state = State.PARTIALLY_SOLD
        self.sell.current_position.state_info = StateInfo(
            side=PositionSide.SHORT, state=State.PARTIALLY_SOLD
        )
        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )
        self.send_sell_position_to_ui()

    def conditions_for_resending_sell_orders_from_part_sold_and_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
            and self.ticker_update.symbol
            == self.sell.current_position.config.symbol_info.symbol
        )
        if condition:
            logger.info(
                "[Resend sell orders] hp id: %s, %s, side: %s, state: %s",
                self.sell.current_position.config.hp_id,
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.side,
                self.sell.current_position.state_info.state,
            )

        return condition

    def conditions_for_resending_buy_orders_from_part_sold_and_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.ticker_update.last_price
            <= self.calculate_trigger_send_orders_price_buy()
        )
        if condition:
            logger.info(
                "[Resend buy orders] hp id: %s, %s, side: %s, state: %s",
                self.sell.current_position.config.hp_id,
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.side,
                self.sell.current_position.state_info.state,
            )

        return condition

    def conditions_for_cancelling_partially_sold_and_bought_orders_buy_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
        )
        if condition:
            logger.info(
                "[Cancel Part Filled BUY] %s, last price: %s, trigger price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
            )

        return condition

    def conditions_for_buying_fully_previously_partially_sold_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.state == State.BUYING
            and self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and all(order.status == ORDER_STATUS_FILLED for order in self.buy.orders)
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            logger.info(
                "[All orders filled] %s %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
            )
        return condition

    def conditions_for_closing_sold_position_which_is_part_bought(
        self, *args, **kwargs
    ) -> bool:
        # Check all conditions for SOLD_PART_BOUGHT transition
        condition = (
            self.state == State.SELLING
            and self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.sell_order.status == ORDER_STATUS_FILLED
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            logger.info(
                "[All orders filled] %s %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
            )
        return condition

    async def close_sold_position_which_is_part_bought(self, *args, **kwargs) -> None:
        logger.info("Close sold position which is partially bought")

        self.sell.current_position.state_info.state = State.SOLD

        # Send HP sell position completed event to portfolio
        end_currency_received = (
            self.sell.current_position.sell_order.realized_quantity
            * self.sell.current_position.config.sell_price
        )
        hp_sell_completed = HPSellPositionCompleted(
            hp_id=self.sell.current_position.config.hp_id,
            coin=self.sell.current_position.config.coin,
            quantity_sold=self.sell.current_position.sell_order.realized_quantity,
            buy_price=self.sell.current_position.config.buy_price,  # Add missing buy price
            sell_price=self.sell.current_position.config.sell_price,  # Add missing sell price
            end_currency=self.sell.current_position.config.end_currency,  # Use actual end_currency from config
            end_currency_received=end_currency_received,
        )
        logger.info(
            "Sending HP sell position completed from SOLD POSITION WHICH IS PART BOUGHT: %s",
            hp_sell_completed,
        )
        self._send_portfolio_event(
            EventName.HP_SELL_POSITION_COMPLETED, hp_sell_completed
        )

        self.sell.current_position.state_info.get_completeness(
            self.sell.current_position.sell_order
        )
        self.sell.current_position.state_info.ui_state = UiState.CLOSED
        self.send_sell_position_to_ui()
        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )

    def conditions_for_resending_buy_orders_for_sold_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.SOLD
            and self.ticker_update.last_price
            <= self.calculate_trigger_send_orders_price_buy()
        )
        if condition:
            logger.info(
                "[Resend buy orders] hp id: %s, %s, side: %s, state: %s",
                self.sell.current_position.config.hp_id,
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.side,
                self.sell.current_position.state_info.state,
            )

        return condition

    def conditions_for_cancelling_buy_orders_to_sold_part_bought(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.SOLD
            and self.sell.current_position.state_info.state == State.PARTIALLY_BOUGHT
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
        )
        if condition:
            logger.info(
                "[Cancel Part Filled BUY] %s, last price: %s, trigger price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
            )

        return condition

    def conditions_for_order_filled_buy(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.buy.orders]
        )
        if condition:
            logger.info(
                "[Filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_filled_buy(self, *args, **kwargs) -> None:
        """Handle filled buy order."""
        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT
        if self.sell.current_position.state_info.state == State.SOLD:
            self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        await self.buy.handle_order_filled(execution_report=self.execution_report)

        await self.db.upsert_buy_price_level(
            data=self.buy.data, strategy_state=self.state
        )

        # Send fill event to portfolio for inventory updates
        if self.portfolio_event_callback:
            self.portfolio_event_callback(
                EventName.HP_BUY_POSITION_PARTIALLY_FILLED,
                HPBuyPositionPartiallyFilled(
                    hp_id=self.buy.data.config.hp_id,
                    coin=self.buy.data.config.symbol_info.symbol,
                    filled_quantity=self.execution_report.last_executed_quantity,
                    total_filled=self.execution_report.cumulative_filled_quantity,
                    buy_price=self.execution_report.price,
                    partial_cost=self.execution_report.last_executed_quantity
                    * self.execution_report.price,
                ),
            )

        self.send_buy_position_to_ui()

        if all(order.status == ORDER_STATUS_FILLED for order in self.buy.orders):
            signal = Signal.HP_ALL_ORDERS_FILLED
            logger.info("All BUY orders filled, sending: %s", signal)
            self.worker_queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

    def conditions_for_order_partially_filled_buy(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status
            == ORDER_STATUS_PARTIALLY_FILLED
            and self.execution_report.order_id
            in [order.order_id for order in self.buy.orders]
        )
        if condition:
            logger.info(
                "[Partially filled buy order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_partially_filled_buy(self, *args, **kwargs):
        """Handle partially filled buy order."""
        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT

        await self.buy.handle_order_partially_filled(
            execution_report=self.execution_report
        )

        await self.db.upsert_buy_price_level(data=self.buy.data)

        # Send partial fill event to portfolio for inventory updates
        if self.portfolio_event_callback:
            self.portfolio_event_callback(
                EventName.HP_BUY_POSITION_PARTIALLY_FILLED,
                HPBuyPositionPartiallyFilled(
                    hp_id=self.buy.data.config.hp_id,
                    coin=self.buy.data.config.symbol_info.symbol,
                    filled_quantity=self.execution_report.last_executed_quantity,
                    total_filled=self.execution_report.cumulative_filled_quantity,
                    buy_price=self.execution_report.price,
                    partial_cost=self.execution_report.last_executed_quantity
                    * self.execution_report.price,
                ),
            )

        self.send_buy_position_to_ui()

    def conditions_for_order_filled_sell(self, *args, **kwargs) -> bool:
        assert self.sell
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_FILLED
            and self.execution_report.order_id
            == self.sell.current_position.sell_order.order_id
        )
        if condition:
            logger.info(
                "[Filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_filled_sell(self, *args, **kwargs) -> None:
        logger.info("Entering handle order filled sell")

        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        await self.sell.handle_order_filled(execution_report=self.execution_report)

        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )

        # Send fill event to portfolio for inventory updates
        if self.portfolio_event_callback:
            self.portfolio_event_callback(
                EventName.HP_SELL_POSITION_PARTIALLY_FILLED,
                HPSellPositionPartiallyFilled(
                    hp_id=self.sell.current_position.config.hp_id,
                    coin=self.sell.current_position.config.coin,
                    filled_quantity=self.execution_report.last_executed_quantity,
                    total_filled=self.execution_report.cumulative_filled_quantity,
                ),
            )

        self.send_sell_position_to_ui()

        if self.sell.current_position.sell_order.status == ORDER_STATUS_FILLED:
            self.sell.current_position.state_info.state = State.SOLD
            self.sell.current_position.state_info.ui_state = UiState.CLOSED
            self.sell.current_position.state_info.completeness = 1.0

            signal = Signal.HP_ALL_ORDERS_FILLED
            logger.info("All SELL orders filled, sending: %s", signal)
            self.worker_queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

    def conditions_for_order_partially_filled_sell(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status
            == ORDER_STATUS_PARTIALLY_FILLED
            and self.execution_report.order_id
            == self.sell.current_position.sell_order.order_id
        )
        if condition:
            logger.info(
                "[Partially filled sell order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_partially_filled_sell(self, *args, **kwargs):
        """Handle partially filled sell order."""
        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        await self.sell.handle_order_partially_filled(
            execution_report=self.execution_report
        )

        await self.db.upsert_sell_price_level(
            data=self.sell.current_position, strategy_state=self.state
        )

        # Send partial fill event to portfolio for inventory updates
        if self.portfolio_event_callback:
            self.portfolio_event_callback(
                EventName.HP_SELL_POSITION_PARTIALLY_FILLED,
                HPSellPositionPartiallyFilled(
                    hp_id=self.sell.current_position.config.hp_id,
                    coin=self.sell.current_position.config.coin,
                    filled_quantity=self.execution_report.last_executed_quantity,
                    total_filled=self.execution_report.cumulative_filled_quantity,
                ),
            )

        self.send_sell_position_to_ui()

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type
            in [
                ORDER_TYPE_LIMIT,
                ORDER_TYPE_MARKET,
            ]
            and self.execution_report.current_order_status == ORDER_STATUS_NEW
            and self.execution_report.symbol == self.buy.data.config.symbol_info.symbol
        )
        if condition:
            logger.info(
                "[New Order] %s, order type: %s order status: %s",
                self.execution_report.symbol,
                self.execution_report.order_type,
                self.execution_report.current_order_status,
            )
        return condition

    async def confirm_new_order(self, *args, **kwargs) -> None:
        """Confirm new order placement."""
        for order in self.buy.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id

        if self.sell:
            if (
                self.sell.current_position.sell_order.order_id
                == self.execution_report.order_id
            ):
                self.sell.current_position.sell_order.status = (
                    self.execution_report.current_order_status
                )

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_CANCELED
            and self.execution_report.symbol == self.buy.data.config.symbol_info.symbol
        )
        if condition:
            logger.info(
                "[Cancelled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        """Confirm order cancellation."""
        for order in self.buy.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id

        if self.sell:
            if (
                self.sell.current_position.sell_order.order_id
                == self.execution_report.order_id
            ):
                self.sell.current_position.sell_order.status = (
                    self.execution_report.current_order_status
                )
                self.sell.current_position.sell_order.order_id = (
                    self.execution_report.order_id
                )

    def conditions_for_order_expiration(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_EXPIRED
        )

        if condition:
            logger.info(
                "[Expired order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        """Confirm and update expired order status."""
        for order in self.buy.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id

        if self.sell:
            if (
                self.sell.current_position.sell_order.order_id
                == self.execution_report.order_id
            ):
                self.sell.current_position.sell_order.status = (
                    self.execution_report.current_order_status
                )
                self.sell.current_position.sell_order.order_id = (
                    self.execution_report.order_id
                )

    def calculate_trigger_cancel_orders_price_sell(self):
        return self.sell.original_position.config.symbol_info.adjust_price(
            0.92 * self.sell.original_position.config.sell_price
        )

    async def allow_messages(self, *args, **kwargs) -> None:
        logger.info(
            "Ticker update from allow messages method: %s",
            self.ticker_update.last_price,
        )

    async def worker(self):
        logger.info("Worker start now, state: %s.", self.state)
        self.worker_active = True

        # Send initial UI update for new positions
        if self.state == State.NEW:
            self.send_buy_position_to_ui()
        while not self.stop_event.is_set():
            try:
                event = self.worker_queue.get_nowait()
                assert isinstance(event, Event)

                # logger.info("New event: %s", event)

                if EventName.TICKER == event.name:
                    assert isinstance(event.content, TickerUpdate)
                    self.ticker_update = event.content
                    await self.process_ticker()  # pylint: disable=no-member

                elif EventName.EXECUTION_REPORT == event.name:
                    assert isinstance(event.content, ExecutionReport)
                    self.execution_report = event.content
                    await self.process_order()  # pylint: disable=no-member

                elif EventName.ACCOUNT_POSITION == event.name:
                    assert isinstance(event.content, AccountPosition)
                    self.account_position = event.content
                    await self.process_account()  # pylint: disable=no-member

                elif EventName.SIGNAL == event.name:
                    assert isinstance(event.content, SignalUpdate)
                    self.signal_update = event.content
                    logger.info(
                        f"[WORKER QUEUE] Processing signal: {self.signal_update}"
                    )
                    logger.info(f"[WORKER QUEUE] Current state: {self.state}")
                    await self.process_signal()  # pylint: disable=no-member
                    logger.info(
                        f"[WORKER QUEUE] After process_signal, state: {self.state}"
                    )

                self.worker_queue.task_done()
            except queue.Empty:
                # logger.info("Queue empty, waiting 0.1s")
                await asyncio.sleep(0.1)
        logger.info("Stop event IS SET, worker closed")
        self.worker_active = False
