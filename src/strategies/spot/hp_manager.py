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
from src.common.database import Database
from src.common.identifiers.spot import (
    AccountPosition,
    Event,
    EventName,
    ExecutionReport,
    Signal,
    SignalUpdate,
    State,
    StrategyConfig,
    TickerUpdate,
)
from src.common.identifiers.common import (
    BinanceClient,
    Order,
    PositionSide,
    PositionStatus,
)
from src.gui.identifiers.spot import PositionData
from src.position_handler.spot import PositionHandler

STAGNATION_LIMIT = 8


class HpManager:
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        logger: StrategyLogger,
        balance: float,
        gui_handler: asyncio.Queue,
        db: Database,
    ):
        self.client = client
        self.logger = logger
        self.balance = balance
        self.db = db
        self.queue: asyncio.Queue = asyncio.Queue()
        self.config = config
        self.position_handler = PositionHandler(
            client=client,
            strategy_logger=logger,
            config=config,
            gui_handler=gui_handler,
            db=db,
        )
        self.state = State.NEW

        self.states = [
            State.CLOSED,
            State.NEW,
            State.OPEN,
            State.RECOVERING,
            State.STAGNATED,
        ]

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.execution_report: ExecutionReport = ExecutionReport()
        self.ticker_update: TickerUpdate = TickerUpdate()
        self.account_position: AccountPosition = AccountPosition()

        self.trigger_orders_price = self.calculate_trigger_orders_price()
        self.transitions = self.get_transitions()

    def __str__(self):
        return (
            f"HpManager(client={self.client}, config={self.config}, "
            f"logger={self.logger}, "
            f"balance={self.balance}, state={self.state}, "
            f"trigger_orders_price={self.trigger_orders_price}, "
            f"position_handler={self.position_handler})"
        )

    def get_transitions(self):
        return [
            {
                "trigger": "process_recovery",
                "source": State.RECOVERING,
                "dest": State.NEW,
                "conditions": "condition_for_recovering_to_new",
                "after": "handle_recovery_to_new",
            },
            {
                "trigger": "process_recovery",
                "source": State.RECOVERING,
                "dest": State.OPEN,
                "conditions": "condition_for_recovering_to_open",
                "after": "handle_recovery_to_open",
            },
            {
                "trigger": "process_recovery",
                "source": State.RECOVERING,
                "dest": State.STAGNATED,
                "conditions": "condition_for_recovering_to_stagnated",
                "after": "handle_recovery_to_stagnated",
            },
            {
                "trigger": "process_account",
                "source": [
                    State.NEW,
                    State.OPEN,
                    State.STAGNATED,
                    State.RECOVERING,
                    State.CLOSED,
                ],
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
        symbol_config = self.position_handler.order_handler.symbol_config
        symbol_config.min_notional = await self._get_minimum_notional_for_symbol(
            self.config.symbol
        )
        (
            symbol_config.lot_size,
            symbol_config.precision,
        ) = await self._get_lot_size_and_precision(self.config.symbol)

    async def _get_minimum_notional_for_symbol(self, symbol):
        exchange_info = await self.client.get_exchange_info()
        for s in exchange_info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "MIN_NOTIONAL":
                        return float(f["minNotional"])
        return None

    async def _get_lot_size_and_precision(self, symbol):
        exchange_info = await self.client.get_exchange_info()
        for s in exchange_info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        lot_size = float(f["stepSize"])
                        precision = self._calculate_precision(f["stepSize"])
                        return lot_size, precision
        return None, None

    def _calculate_precision(self, step_size):
        step_size_str = f"{float(step_size):.20f}".rstrip("0")
        if "." in step_size_str:
            return len(step_size_str.split(".")[1])
        return 0

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

    def condition_for_recovering_to_new(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.state == State.RECOVERING
            and self.config.status == PositionStatus.NEW.value
        )
        self.logger.debug("Recovering to state NEW: %s.", condition)
        return condition

    def condition_for_recovering_to_open(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.state == State.RECOVERING
            and self.config.status == PositionStatus.OPEN.value
        )
        self.logger.debug("Recovering to state OPEN: %s.", condition)
        return condition

    def condition_for_recovering_to_stagnated(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.state == State.RECOVERING
            and self.config.status == PositionStatus.STAGNATED.value
        )
        self.logger.debug("Recovering to state STAGNATED: %s.", condition)
        return condition

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.execution_report.order_type
            in [
                ORDER_TYPE_LIMIT,
                ORDER_TYPE_MARKET,
            ]
            and self.execution_report.current_order_status == ORDER_STATUS_NEW
        )
        self.logger.debug(
            "New order confirmation: %s, order type: %s order status: %s",
            condition,
            self.execution_report.order_type,
            self.execution_report.current_order_status,
        )
        return condition

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_CANCELED
        )
        self.logger.debug(
            "Order cancelled: %s, order update status: %s",
            condition,
            self.execution_report.current_order_status,
        )
        return condition

    def conditions_for_order_expiration(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_EXPIRED
        )
        self.logger.debug(
            "Order expired: %s, order update status: %s",
            condition,
            self.execution_report.current_order_status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_FILLED
        )

        self.logger.debug(
            "Order filled: %s, order status: %s",
            condition,
            self.execution_report.current_order_status,
        )
        return condition

    def conditions_for_order_partially_filled(self, *args, **kwargs):
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status
            == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.debug(
            "Order partially filled: %s, order update status: %s",
            condition,
            self.execution_report.current_order_status,
        )
        return condition

    def conditions_for_all_orders_filled(self, *args, **kwargs):
        condition = (
            self.state == State.OPEN
            and all(
                order.status == ORDER_STATUS_FILLED
                for order in self.position_handler.orders
            )
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )

        self.logger.debug(
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
        self.logger.debug(
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
        self.logger.debug("Resend buy orders: %s, state: %s", condition, self.state)

        return condition

    def conditions_for_sending_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.NEW
            and self.config.side == PositionSide.SHORT
            and self.ticker_update.last_price >= self.trigger_orders_price
        )
        self.logger.debug(
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
        self.logger.debug("Resend sell orders: %s, state: %s", condition, self.state)

        return condition

    def conditions_for_cancelling_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.position_handler.config.side == PositionSide.LONG
            and self.position_handler.stagnation_counter == STAGNATION_LIMIT
            and self.ticker_update.last_price > self.trigger_orders_price
        )
        self.logger.debug(
            "Cancel BUY orders due to stagnation: %s, last price: %s",
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
        self.logger.debug(
            "Cancel SELL orders due to stagnation: %s, last price: %s",
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
        self.position_handler.status = PositionStatus.STAGNATED

    async def cancel_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.position_handler.config.side)
        await self.position_handler.cancel_position()
        self.position_handler.status = PositionStatus.STAGNATED

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
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "New order confirmation: %s", self.execution_report.order_id
                )

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Cancelled order confirmation: %s", self.execution_report.order_id
                )

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Expired order confirmation: %s", self.execution_report.order_id
                )
                # await self.gui_handler.update_order(
                #     order=order,
                #     symbol=self.position_handler.position.symbol,
                #     side=self.position_handler.position.side,
                # )

    async def handle_account(self, *args, **kwargs):
        self.logger.debug("Account update: %s", self.account_position)

    async def handle_order_filled(self, *args, **kwargs):
        self.logger.debug("Entering handle order filled")

        await self.position_handler.handle_order_filled(
            execution_report=self.execution_report
        )

        if all(
            order.status == ORDER_STATUS_FILLED
            for order in self.position_handler.orders
        ):
            signal = Signal.HP_ALL_ORDERS_FILLED
            self.logger.info("All orders filled, sending: %s", signal)
            await self.queue.put(
                Event(name=EventName.SIGNAL, content=SignalUpdate(signal=signal))
            )

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.debug("Entering handle order partially filled")

        await self.position_handler.handle_order_partially_filled(
            execution_report=self.execution_report
        )

    async def handle_recovery_to_new(self, *args, **kwargs):
        self.logger.debug("Handle recovery to new")

        await self.position_handler.gui_handler.put(
            PositionData(
                system_id=self.config.system_id,
                symbol=self.config.symbol,
                side=self.config.side,
                price_low=self.config.price_low,
                price_high=self.config.price_high,
                budget=self.config.budget,
                order_trigger=self.config.order_trigger,
                orders_opened=0,
                orders_filled=0,
                orders_total=0,
                status=self.config.status,
            )
        )

    async def handle_recovery_to_open(self, *args, **kwargs):
        self.logger.debug("Handle recovery to open")

        orders = self.db.fetch_orders_for_price_level(
            price_level_id=self.config.system_id
        )

        self.logger.debug(
            "Fetched orders for price level: %s: \n%s", self.config.system_id, orders
        )

        # await self.position_handler.gui_handler.put(
        #     PositionData(
        #         system_id=self.config.system_id,
        #         symbol=self.config.symbol,
        #         side=self.config.side,
        #         price_low=self.config.price_low,
        #         price_high=self.config.price_high,
        #         budget=self.config.budget,
        #         order_trigger=self.config.order_trigger,
        #         orders_opened=0,
        #         orders_filled=0,
        #         orders_total=0,
        #         status=self.config.status,
        #     )
        # )

    async def handle_recovery_to_stagnated(self, *args, **kwargs):
        self.logger.debug("Handle recovery to stagnated")

        orders = self.db.fetch_orders_for_price_level(
            price_level_id=self.config.system_id
        )

        self.logger.debug(
            "Fetched orders for price level: %s: \n%s", self.config.system_id, orders
        )

        await self.position_handler.gui_handler.put(
            PositionData(
                system_id=self.config.system_id,
                symbol=self.config.symbol,
                side=self.config.side,
                price_low=self.config.price_low,
                price_high=self.config.price_high,
                budget=self.config.budget,
                order_trigger=self.config.order_trigger,
                orders_opened=0,
                orders_filled=0,
                orders_total=0,
                status=self.config.status,
            )
        )
