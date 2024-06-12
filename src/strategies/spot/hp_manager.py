import asyncio
from datetime import datetime, timedelta
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
)
from logging_config import StrategyLogger
from src.common.identifiers.spot import (
    Signal,
    SignalUpdate,
    State,
    StrategyConfig,
    TickerUpdate,
)
from src.common.identifiers.common import (
    AccountUpdate,
    BinanceClient,
    Order,
    OrderUpdate,
    PositionSide,
)
from src.gui.gui_handler.spot import GuiHandler
from src.position_handler.spot import PositionHandler

STAGNATION_LIMIT = 8


class HpManager:
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        gui_handler: GuiHandler,
        logger: StrategyLogger,
        balance: float,
    ):
        self.client = client
        self.logger = logger
        self.balance = balance
        self.queue: asyncio.Queue = asyncio.Queue()
        self.gui_handler = gui_handler
        self.config = config
        self.position_handler = PositionHandler(
            client=client,
            strategy_logger=logger,
            config=config,
            gui_handler=gui_handler,
        )
        self.state = State.NEW
        self.states = [
            State.NEW,
            State.OPEN,
            State.STAGNATED,
            State.CLOSED,
        ]

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.order_update: OrderUpdate = OrderUpdate()
        self.ticker_update: TickerUpdate = TickerUpdate()
        self.account_update: AccountUpdate = AccountUpdate(account_update={})

        self.trigger_orders_price = self.calculate_trigger_orders_price()

        self.transitions = self.get_transitions()

    def __str__(self):
        return (
            f"HpManager(client={self.client}, config={self.config}, "
            f"gui_handler={self.gui_handler}, logger={self.logger}, "
            f"balance={self.balance}, state={self.state}, "
            f"trigger_orders_price={self.trigger_orders_price}, "
            f"position_handler={self.position_handler})"
        )

    def get_transitions(self):
        return [
            {
                "trigger": "process_account",
                "source": [State.NEW, State.OPEN, State.STAGNATED, State.CLOSED],
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [State.OPEN, State.STAGNATED],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "confirm_new_order",
            },
            {
                "trigger": "process_order",
                "source": [State.OPEN, State.STAGNATED],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "confirm_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "confirm_expired_order",
            },
            {
                "trigger": "process_signal",
                "source": State.OPEN,
                "dest": State.CLOSED,
                "conditions": "conditions_for_all_orders_filled",
                "before": "close_position",
            },
            {
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled",
                "before": "handle_order_partially_filled",
            },
            {
                "trigger": "process_ticker",
                "source": State.NEW,
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_buy_orders",
                "after": "send_buy_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.NEW,
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_sell_orders",
                "after": "send_sell_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.STAGNATED,
                "dest": State.OPEN,
                "conditions": "conditions_for_resending_buy_orders",
                "after": "resend_buy_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.STAGNATED,
                "dest": State.OPEN,
                "conditions": "conditions_for_resending_sell_orders",
                "after": "resend_sell_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_buy_orders",
                "after": "cancel_buy_orders",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_sell_orders",
                "after": "cancel_sell_orders",
            },
            {
                "trigger": "process_ticker",
                "source": [State.NEW, State.OPEN, State.STAGNATED, State.CLOSED],
                "dest": "=",
                "after": "handle_ticker",
            },
        ]

    async def initialize(self):
        self.config.min_notional = await self._get_minimum_notional_for_symbol(
            symbol=self.config.symbol
        )

    def calculate_trigger_orders_price(self):
        return (
            round(
                self.config.price_low * (1 - (self.config.order_trigger / 100)),
                2,
            )
            if self.config.side == PositionSide.SHORT
            else round(
                self.config.price_high * (1 + (self.config.order_trigger / 100)),
                2,
            )
        )

    async def _get_minimum_notional_for_symbol(self, symbol: str) -> float:
        exchange_info = await self.client.get_exchange_info()

        for symbol_info in exchange_info["symbols"]:
            if symbol_info["symbol"] == symbol:
                # Iterate through filters to find minNotional filter
                for symbol_filter in symbol_info["filters"]:
                    if symbol_filter["filterType"] == "NOTIONAL":
                        return float(symbol_filter["minNotional"])
        safe_value = 10
        return safe_value

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.order_update.order_type
            in [
                ORDER_TYPE_LIMIT,
                ORDER_TYPE_MARKET,
            ]
            and self.order_update.status == ORDER_STATUS_NEW
        )
        self.logger.info(
            "New order confirmation: %s, order type: %s order status: %s",
            condition,
            self.order_update.order_type,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_CANCELED
        )
        self.logger.info(
            "Order cancelled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_expiration(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_EXPIRED
        )
        self.logger.info(
            "Order expired: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_FILLED
        )

        self.logger.info(
            "Order filled: %s, order status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_partially_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.info(
            "Order partially filled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_all_orders_filled(self, *args, **kwargs):
        self.logger.info("Entering conditions for all orders filled")
        condition = (
            self.state == State.OPEN
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.position_handler.orders
            )
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )

        self.logger.info(
            "All orders filled: %s, signal update: %s",
            condition,
            self.signal_update.signal,
        )
        return condition

    def conditions_for_sending_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.NEW
            and self.config.side == PositionSide.LONG
            and self.ticker_update.last_price <= self.trigger_orders_price
        )
        self.logger.info(
            "Send buy orders: %s, side: %s, state: %s",
            condition,
            self.config.side,
            self.state,
        )

        return condition

    def conditions_for_resending_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.STAGNATED
            and self.config.side == PositionSide.LONG
            and self.ticker_update.last_price <= self.trigger_orders_price
        )
        self.logger.info("Resend buy orders: %s, state: %s", condition, self.state)

        return condition

    def conditions_for_sending_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.NEW
            and self.config.side == PositionSide.SHORT
            and self.ticker_update.last_price >= self.trigger_orders_price
        )
        self.logger.info(
            "Send sell orders: %s, side: %s, state: %s",
            condition,
            self.config.side,
            self.state,
        )

        return condition

    def conditions_for_resending_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.STAGNATED
            and self.config.side == PositionSide.SHORT
            and self.ticker_update.last_price >= self.trigger_orders_price
        )
        self.logger.info("Resend sell orders: %s, state: %s", condition, self.state)

        return condition

    def conditions_for_cancelling_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.position_handler.config.side == PositionSide.LONG
            and self.position_handler.stagnation_counter == STAGNATION_LIMIT
            and self.ticker_update.last_price > self.trigger_orders_price
        )
        self.logger.info(
            "Cancel %s orders due to stagnation: %s, last price: %s",
            self.position_handler.config.side.value,
            condition,
            self.ticker_update.last_price,
        )

        return condition

    def conditions_for_cancelling_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.position_handler.config.side == PositionSide.SHORT
            and self.position_handler.stagnation_counter == STAGNATION_LIMIT
            and self.ticker_update.last_price < self.trigger_orders_price
        )
        self.logger.info(
            "Cancel %s orders due to stagnation: %s, last price: %s",
            self.position_handler.config.side,
            condition,
            self.ticker_update.last_price,
        )

        return condition

    async def send_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Opening %s %s", self.config.symbol, self.config.side.value)

        await self.position_handler.open_position(
            side=self.config.side,
            symbol=self.config.symbol,
        )

    async def resend_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Resending %s %s", self.config.symbol, self.config.side.value)

        new_orders = []

        for order in self.position_handler.orders:
            if order.status != ORDER_STATUS_FILLED:
                order = Order(
                    quantity=order.quantity - order.realized_quantity,
                    price=order.price,
                    quantity_stable=self.position_handler.order_handler.round_quantity(
                        (order.quantity - order.realized_quantity) * order.price
                    ),
                )
                new_orders.append(order)
                self.logger.info("New order prepared: %s", order)

        self.position_handler.orders = new_orders

        await self.position_handler.order_handler.create_orders(
            side=self.position_handler.config.side,
            symbol=self.position_handler.config.symbol,
            orders=self.position_handler.orders,
        )
        self.state = State.OPEN

    async def resend_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Resending %s %s", self.config.symbol, self.config.side.value)

        new_orders = []

        for order in self.position_handler.orders:
            if order.status != ORDER_STATUS_FILLED:
                order = Order(
                    quantity=order.quantity - order.realized_quantity,
                    price=order.price,
                    quantity_stable=self.position_handler.order_handler.round_quantity(
                        (order.quantity - order.realized_quantity) * order.price
                    ),
                )
                new_orders.append(order)
                self.logger.info("New order prepared: %s", order)

        self.position_handler.orders = new_orders

        await self.position_handler.order_handler.create_orders(
            side=self.position_handler.config.side,
            symbol=self.position_handler.config.symbol,
            orders=self.position_handler.orders,
        )
        self.state = State.OPEN

    async def send_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Opening %s %s", self.config.symbol, self.config.side.value)

        await self.position_handler.open_position(
            side=self.config.side,
            symbol=self.config.symbol,
        )

    async def cancel_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.position_handler.config.side)

        await self.position_handler.cancel_position()

    async def cancel_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.position_handler.config.side)
        await self.position_handler.cancel_position()

    async def close_position(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")
        self.state = State.CLOSED

    async def handle_ticker(self, *args, **kwargs) -> None:
        date_time_now = datetime.now()

        if (
            self.state == State.OPEN
            and date_time_now > self.position_handler.next_monitor_position_time
        ):
            self.position_handler.stagnation_counter += 1
            self.logger.info(
                "Stagnation counter increase due to crossing stagnation timer: %s, time now: %s, stagnation counter: %s",
                self.position_handler.next_monitor_position_time,
                date_time_now,
                self.position_handler.stagnation_counter,
            )
            self.position_handler.next_monitor_position_time += timedelta(hours=1)

    async def confirm_new_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "New order confirmation: %s", self.order_update.order_id
                )

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Cancelled order confirmation: %s", self.order_update.order_id
                )

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Expired order confirmation: %s", self.order_update.order_id
                )
                # await self.gui_handler.update_order(
                #     order=order,
                #     symbol=self.position_handler.position.symbol,
                #     side=self.position_handler.position.side,
                # )

    async def handle_account(self, *args, **kwargs):
        self.logger.info("Account update: %s", self.account_update.account_update)

    async def handle_order_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order filled")

        await self.position_handler.handle_order_filled(order_update=self.order_update)

        if all(
            order.status == ORDER_STATUS_FILLED
            for order in self.position_handler.orders
        ):
            signal = Signal.HP_ALL_ORDERS_FILLED
            self.logger.info("All orders filled, sending: %s", signal)
            await self.queue.put(SignalUpdate(signal=signal))

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order partially filled")

        await self.position_handler.handle_order_partially_filled(
            order_update=self.order_update
        )
