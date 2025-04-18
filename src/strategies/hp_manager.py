import asyncio
from datetime import datetime
import queue
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
from logging_config import StrategyLogger
from src.database import Database
from src.identifiers.spot import (
    AccountPosition,
    Event,
    EventName,
    ExecutionReport,
    HPBuyConfig,
    HPBuyData,
    HPSellConfig,
    HPSellData,
    Signal,
    SignalUpdate,
    State,
    StateInfo,
    TickerUpdate,
    UiState,
)
from src.identifiers.common import (
    BinanceClient,
    PositionSide,
)
from src.gui.identifiers.spot import HPClose, HPGuiDataBuy, HPGuiDataSell, HPUpdate
from src.position_buy import HPPositionBuy
from src.position_sell import HPPositionSell

# pylint: disable=unused-argument


class HpStrategy:
    def __init__(
        self,
        client: BinanceClient,
        logger: StrategyLogger,
        balance: float,
        ui_queue: queue.Queue,
        worker_queue: queue.Queue,
        config_queue: queue.Queue,
        db: Database,
        buy_position: HPPositionBuy,
        sell_position: HPPositionSell,
        initial_state: State = State.NEW,
    ):
        self.client = client
        self.logger = logger
        self.balance = balance
        self.db = db
        self.stop_event: asyncio.Event = asyncio.Event()
        self.worker_queue = worker_queue
        self.config_queue = config_queue
        self.ui_queue = ui_queue
        self.buy = buy_position
        self.sell = sell_position

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
                # No 12
                "trigger": "process_signal",
                "source": State.SELLING,
                "dest": State.SOLD,
                "conditions": "conditions_for_all_orders_filled_sell",
                "after": "close_filled_position_sell",
            },
            {
                # No 13
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": State.PART_SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_sold_and_bought_orders_sell_position",
                "after": "cancel_partially_sold_orders",
            },
            {
                # No 14
                "trigger": "process_ticker",
                "source": State.PART_SOLD_PART_BOUGHT,
                "dest": State.SELLING,
                "conditions": "conditions_for_resending_sell_orders_from_part_sold_and_bought_orders",
                "before": "resend_sell_order",
            },
            {
                # No 15
                "trigger": "process_ticker",
                "source": State.PART_SOLD_PART_BOUGHT,
                "dest": State.BUYING,
                "conditions": "conditions_for_resending_buy_orders_from_part_sold_and_bought_orders",
                "after": "resend_buy_orders",
            },
            {
                # No 16
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": State.PART_SOLD_PART_BOUGHT,
                "conditions": "conditions_for_cancelling_partially_sold_and_bought_orders_buy_position",
                "after": "cancel_partially_bought_orders",
            },
            {
                # No 17
                "trigger": "process_signal",
                "source": State.BUYING,
                "dest": State.PARTIALLY_SOLD,
                "conditions": "conditions_for_buying_fully_previously_partially_sold_position",
                "after": "close_filled_position_buy",
            },
            {
                # No 18
                "trigger": "process_signal",
                "source": State.SELLING,
                "dest": State.SOLD_PART_BOUGHT,
                "conditions": "conditions_for_closing_sold_position_which_is_part_bought",
                "after": "close_sold_position_which_is_part_bought",
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
                "trigger": "process_ticker",
                "source": State.BUYING,
                "dest": "=",
                "conditions": "conditions_for_position_stagnation_buy",
                "after": "increase_stagnation_counter_buy",
            },
            {
                "trigger": "process_ticker",
                "source": State.SELLING,
                "dest": "=",
                "conditions": "conditions_for_position_stagnation_sell",
                "after": "increase_stagnation_counter_sell",
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
                "after": "allow_messages",
            },
        ]

    def calculate_trigger_send_orders_price_buy(self):
        return self.buy.data.config.symbol_info.adjust_price(
            max(
                order.price
                for order in self.buy.orders
                if order.status != ORDER_STATUS_FILLED
            )
            * (1 + (self.buy.data.config.order_trigger / 100))
        )

    def get_remaining_quantity_buy(self, *args, **kwargs) -> float:
        rem_quant = 0.0
        for order in self.buy.orders:
            rem_quant += order.quantity_stable - order.quantity_stable * (
                order.realized_quantity / order.quantity
            )
        self.logger.debug(
            "Remaining quantity: %s for %s",
            rem_quant,
            self.buy.data.config.symbol_info.symbol,
        )
        return rem_quant

    def conditions_for_sending_buy_orders(self, *args, **kwargs) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_buy()
        condition = (
            self.state == State.NEW
            and self.buy.data.state_info.state == State.NEW
            and self.ticker_update.last_price <= trigger_send_orders_price
            and self.balance > self.buy.data.config.budget
        )
        if condition:
            self.logger.info(
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

        return condition

    async def send_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Sending %s BUY", self.buy.data.config.symbol_info.symbol)
        self.balance -= self.get_remaining_quantity_buy()

        self.buy.prepare_orders()
        self.buy.orders = await self.buy.open_position()
        self.state = State.BUYING
        self.buy.data.state_info.state = State.NEW

        self.buy.data.state_info.generate_next_monitor_time()
        self.buy.data.state_info.completeness = round(
            sum(order.realized_quantity for order in self.buy.orders)
            / sum(order.quantity for order in self.buy.orders),
            2,
        )

        self.buy.data.state_info.ui_state = UiState.OPEN

        self.logger.info("Orders sent, updating DB: %s", self.buy.orders)

        for order in self.buy.orders:
            self.db.upsert_order(
                order=order,
                hp_id=self.buy.data.config.hp_id,
                side=self.buy.data.state_info.side,
            )

        self.logger.info(
            "Orders sent, updating DB with price level: %s",
            self.buy.data.state_info,
        )
        self.db.upsert_buy_price_level(data=self.buy.data)
        pos_data = HPGuiDataBuy(
            data=HPBuyData(
                config=self.buy.data.config, state_info=self.buy.data.state_info
            ),
            hp_update=HPUpdate(hp_id=self.buy.data.config.hp_id, state=self.state),
        )
        self.logger.info("Orders sent, GUI with position data: %s", pos_data)
        self.ui_queue.put_nowait(pos_data)

    def conditions_for_cancelling_unfilled_buy_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.buy.data.state_info.state == State.NEW
            and self.sell.current_position.state_info.state == State.NEW
            and self.state == State.BUYING
            and self.buy.data.state_info.stagnation_counter
            >= self.buy.data.state_info.stagnation_limit
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
            and all(order.status == ORDER_STATUS_NEW for order in self.buy.orders)
        )
        if condition:
            self.logger.info(
                "[Cancel Unfilled BUY] %s, stag: %s/%s, last price: %s, trig price: %s, state: %s, buy state: %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.stagnation_counter,
                self.buy.data.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
                self.state,
                self.buy.data.state_info.state,
            )

        return condition

    async def cancel_unfilled_buy_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.buy.data.state_info.side.value)
        self.logger.info("Orders: %s", self.buy.orders)
        self.balance += self.get_remaining_quantity_buy()
        await self.buy.cancel_position()
        self.buy.data.state_info.state = State.NEW

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=HPUpdate(hp_id=self.buy.data.config.hp_id, state=self.state),
            )
        )

    def conditions_for_cancelling_partially_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.buy.data.state_info.stagnation_counter
            >= self.buy.data.state_info.stagnation_limit
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
        )
        if condition:
            self.logger.info(
                "[Cancel Part Filled BUY] %s, stagnation: %s/%s, last price: %s, trig price: %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.stagnation_counter,
                self.buy.data.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
            )

        return condition

    async def cancel_partially_bought_orders(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.buy.data.state_info.side.value)
        self.logger.info("Orders: %s", self.buy.orders)
        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT
        self.balance += self.get_remaining_quantity_buy()
        await self.buy.cancel_position()

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=HPUpdate(hp_id=self.buy.data.config.hp_id, state=self.state),
            )
        )

    def conditions_for_resending_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_buy()
        condition = (
            self.state == State.PARTIALLY_BOUGHT
            and self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.ticker_update.last_price <= trigger_send_orders_price
            and self.balance > self.buy.data.config.budget
        )
        if condition:
            self.logger.info(
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
        self.logger.info("Resending %s BUY", self.buy.data.config.symbol_info.symbol)
        self.balance -= self.get_remaining_quantity_buy()
        self.buy.data.state_info.stagnation_counter = 0

        await self.buy.open_position()
        self.state = State.BUYING
        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT
        self.buy.data.state_info.completeness = round(
            sum(order.realized_quantity for order in self.buy.orders)
            / sum(order.quantity for order in self.buy.orders),
            2,
        )
        self.buy.data.state_info.ui_state = UiState.OPEN

        self.logger.info("Will update orders: %s", self.buy.orders)

        for order in self.buy.orders:
            self.db.upsert_order(
                order=order,
                hp_id=self.buy.data.config.hp_id,
                side=self.buy.data.state_info.side,
            )
        self.db.upsert_buy_price_level(data=self.buy.data)

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=HPUpdate(hp_id=self.buy.data.config.hp_id, state=self.state),
            )
        )

    def calculate_trigger_send_orders_price_sell(self):
        return self.sell.current_position.config.symbol_info.adjust_price(
            0.96 * self.sell.current_position.config.sell_price
        )

    def conditions_for_sending_sell_orders_for_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Send sell orders] hp id: %s, %s, side: %s, state: %s",
                self.sell.current_position.config.hp_id,
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.side,
                self.sell.current_position.state_info.state,
            )

        return condition

    async def send_sell_order(self, *args, **kwargs) -> None:
        self.logger.info(
            "Sending %s SELL", self.sell.current_position.config.symbol_info.symbol
        )

        self.sell.prepare_sell_order(
            buy_realized_quantity=sum(
                order.realized_quantity for order in self.buy.orders
            ),
        )

        await self.sell.open_position()
        self.state = State.SELLING

        self.sell.current_position.state_info.generate_next_monitor_time()

        self.sell.current_position.state_info.completeness = (
            round(
                self.sell.current_position.sell_order.realized_quantity
                / self.sell.current_position.sell_order.quantity,
                2,
            )
            if self.sell.current_position.sell_order
            else 0
        )

        self.sell.current_position.state_info.ui_state = UiState.OPEN

        self.db.upsert_order(
            order=self.sell.current_position.sell_order,
            side=self.sell.current_position.state_info.side,
            hp_id=self.sell.current_position.config.hp_id,
        )
        self.db.upsert_buy_price_level(data=self.buy.data)

        gui_sell = HPGuiDataSell(
            data=HPSellData(
                config=self.sell.current_position.config,
                state_info=self.sell.current_position.state_info,
            ),
            hp_update=HPUpdate(
                hp_id=self.sell.current_position.config.hp_id,
                state=self.state,
                sell_price=self.sell.current_position.config.sell_price,
            ),
        )
        self.ui_queue.put_nowait(gui_sell)
        self.logger.info("Put gui data sell to the ui queue: %s", gui_sell)

    def conditions_for_all_orders_filled_buy(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.BUYING
            and self.sell.current_position.state_info.state == State.NEW
            and all(order.status == ORDER_STATUS_FILLED for order in self.buy.orders)
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            self.logger.info(
                "[All orders filled] %s %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
            )
        return condition

    async def close_filled_position_buy(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")

        self.buy.data.state_info.state = State.BOUGHT
        self.buy.data.state_info.completeness = round(
            sum(order.realized_quantity for order in self.buy.orders)
            / sum(order.quantity for order in self.buy.orders),
            2,
        )
        self.buy.data.state_info.ui_state = UiState.CLOSED

        self.logger.info("Sending HP update with state BOUGHT!!!: %s", self.state)
        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=HPUpdate(hp_id=self.buy.data.config.hp_id, state=self.state),
            )
        )

        self.db.upsert_buy_price_level(data=self.buy.data)

    def conditions_for_cancelling_unfilled_sell_orders_from_partially_bought_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.sell.current_position.state_info.stagnation_counter
            >= self.sell.current_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and self.sell.current_position.sell_order.status == ORDER_STATUS_NEW
        )
        if condition:
            self.logger.info(
                "[Cancel Unfilled SELL] %s, stagnation: %s/%s, last price: %s, trig price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.stagnation_counter,
                self.sell.current_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_unfilled_sell_orders(self, *args, **kwargs) -> None:
        self.logger.info(
            "Cancelling %s", self.sell.current_position.state_info.side.value
        )
        await self.sell.cancel_position()

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id, state=self.state
                ),
            )
        )

    def conditions_for_sending_sell_orders(self, *args, **kwargs) -> bool:
        assert isinstance(self.buy.data.config, HPBuyConfig)
        assert isinstance(self.sell.current_position.config, HPSellConfig)
        condition = (
            self.buy.data.state_info.state in [State.BOUGHT, State.PARTIALLY_BOUGHT]
            and self.sell.current_position.state_info.state == State.NEW
            and self.sell.current_position.config.sell_price
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Send sell orders] hp id: %s, %s, side: %s, state: %s",
                self.sell.current_position.config.hp_id,
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.side,
                self.sell.current_position.state_info.state,
            )

        return condition

    def conditions_for_cancelling_unfilled_sell_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.buy.data.state_info.state == State.BOUGHT
            and self.sell.current_position.state_info.state == State.NEW
            and self.sell.current_position.state_info.stagnation_counter
            >= self.sell.current_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Cancel Unfilled SELL] %s, stagnation: %s/%s, last price: %s, trig price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.stagnation_counter,
                self.sell.current_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    def conditions_for_resending_partially_sold_orders(self, *args, **kwargs) -> bool:
        trigger_send_orders_price = self.calculate_trigger_send_orders_price_sell()
        condition = (
            self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.buy.data.state_info.state == State.BOUGHT
            and self.ticker_update.last_price >= trigger_send_orders_price
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
            self.logger.info(
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
        self.logger.info("Sending %s SELL")

        await self.sell.open_position()
        self.state = State.SELLING
        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD
        self.sell.current_position.state_info.generate_next_monitor_time()
        self.sell.current_position.state_info.completeness = (
            round(
                self.sell.current_position.sell_order.realized_quantity
                / self.sell.current_position.sell_order.quantity,
                2,
            )
            if self.sell.current_position.sell_order
            else 0
        )
        self.sell.current_position.state_info.ui_state = UiState.OPEN

        self.logger.info("Will update order: %s", self.sell.current_position.sell_order)

        self.db.upsert_order(
            order=self.sell.current_position.sell_order,
            side=self.sell.current_position.state_info.side,
            hp_id=self.sell.current_position.config.hp_id,
        )
        self.db.upsert_sell_price_level(data=self.sell.current_position)

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id, state=self.state
                ),
            )
        )

    def conditions_for_cancelling_partially_sold_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.sell.current_position.state_info.stagnation_counter
            >= self.sell.current_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
            and self.sell.current_position.sell_order.status != ORDER_STATUS_NEW
            and self.buy.data.state_info.state == State.BOUGHT
        )
        if condition:
            self.logger.info(
                "[Cancel Part Filled SELL] %s, stagnation: %s/%s, last price: %s, trig price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.stagnation_counter,
                self.sell.current_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_partially_sold_orders(self, *args, **kwargs) -> None:
        self.logger.info(
            "Cancelling %s", self.sell.current_position.state_info.side.value
        )
        await self.sell.cancel_position()
        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id, state=self.state
                ),
            )
        )

    def conditions_for_all_orders_filled_sell(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.SELLING
            and self.buy.data.state_info.state == State.BOUGHT
            and self.sell.current_position.sell_order.status == ORDER_STATUS_FILLED
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        self.logger.info(
            "[All orders filled] %s %s",
            self.sell.current_position.config.symbol_info.symbol,
            self.sell.current_position.state_info.side,
        )
        return condition

    async def close_filled_position_sell(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")

        self.sell.current_position.state_info.state = State.SOLD

        self.sell.current_position.state_info.completeness = (
            round(
                self.sell.current_position.sell_order.realized_quantity
                / self.sell.current_position.sell_order.quantity,
                2,
            )
            if self.sell.current_position.sell_order
            else 0
        )
        self.sell.current_position.state_info.ui_state = UiState.CLOSED

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id, state=self.state
                ),
            )
        )
        self.db.upsert_sell_price_level(data=self.sell.current_position)

        self.logger.info("Going to send HPClose")
        self.config_queue.put_nowait(
            HPClose(
                config=self.sell.current_position.config,
                state_info=self.sell.current_position.state_info,
            )
        )

    def conditions_for_cancelling_partially_sold_and_bought_orders_sell_position(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.sell.current_position.state_info.stagnation_counter
            >= self.sell.current_position.state_info.stagnation_limit
            and self.ticker_update.last_price
            <= self.calculate_trigger_cancel_orders_price_sell()
        )
        if condition:
            self.logger.info(
                "[Cancel Part Filled SELL] %s, stagnation:%s/%s, last price: %s, trigger price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.stagnation_counter,
                self.sell.current_position.state_info.stagnation_limit,
                self.ticker_update.last_price,
                self.calculate_trigger_cancel_orders_price_sell(),
            )

        return condition

    async def cancel_sell_part_sold_part_bought(self, *args, **kwargs) -> None:
        self.logger.info(
            "Cancelling %s", self.sell.current_position.state_info.side.value
        )
        await self.sell.cancel_position()
        self.state = State.PARTIALLY_SOLD
        self.sell.current_position.state_info = StateInfo(
            side=PositionSide.SHORT, state=State.PARTIALLY_SOLD
        )

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id, state=self.state
                ),
            )
        )

    def conditions_for_resending_sell_orders_from_part_sold_and_bought_orders(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.PARTIALLY_SOLD
            and self.ticker_update.last_price
            >= self.calculate_trigger_send_orders_price_sell()
        )
        if condition:
            self.logger.info(
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
            self.logger.info(
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
            and self.buy.data.state_info.stagnation_counter
            >= self.buy.data.state_info.stagnation_limit
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
        )
        if condition:
            self.logger.info(
                "[Cancel Part Filled BUY] %s, stagnation: %s/%s, last price: %s, trigger price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.stagnation_counter,
                self.sell.current_position.state_info.stagnation_limit,
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
            self.logger.info(
                "[All orders filled] %s %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
            )
        return condition

    def conditions_for_closing_sold_position_which_is_part_bought(
        self, *args, **kwargs
    ) -> bool:
        condition = (
            self.state == State.SELLING
            and self.buy.data.state_info.state == State.PARTIALLY_BOUGHT
            and self.sell.current_position.state_info.state == State.SOLD
            and self.sell.current_position.sell_order.status == ORDER_STATUS_FILLED
            and self.signal_update == SignalUpdate(signal=Signal.HP_ALL_ORDERS_FILLED)
        )
        if condition:
            self.logger.info(
                "[All orders filled] %s %s",
                self.buy.data.config.symbol_info.symbol,
                self.buy.data.state_info.side,
            )
        return condition

    async def close_sold_position_which_is_part_bought(self, *args, **kwargs) -> None:
        self.logger.info("Close sold position which is partially bought")

        self.sell.current_position.state_info.state = State.SOLD

        self.sell.current_position.state_info.completeness = (
            round(
                self.sell.current_position.sell_order.realized_quantity
                / self.sell.current_position.sell_order.quantity,
                2,
            )
            if self.sell.current_position.sell_order
            else 0
        )
        self.sell.current_position.state_info.ui_state = UiState.CLOSED

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id, state=self.state
                ),
            )
        )
        self.db.upsert_sell_price_level(data=self.sell.current_position)

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
            self.logger.info(
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
            and self.sell.current_position.state_info.stagnation_counter
            >= self.sell.current_position.state_info.stagnation_limit
            and self.ticker_update.last_price >= self.buy.orders_cancel_price
        )
        if condition:
            self.logger.info(
                "[Cancel Part Filled BUY] %s, stagnation: %s/%s, last price: %s, trigger price: %s",
                self.sell.current_position.config.symbol_info.symbol,
                self.sell.current_position.state_info.stagnation_counter,
                self.sell.current_position.state_info.stagnation_limit,
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
            self.logger.info(
                "[Filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_filled_buy(self, *args, **kwargs) -> None:
        self.logger.debug("Entering handle order filled")

        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT
        if self.sell.current_position.state_info.state == State.SOLD:
            self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        await self.buy.handle_order_filled(execution_report=self.execution_report)

        self.db.upsert_buy_price_level(data=self.buy.data)

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=HPUpdate(
                    hp_id=self.buy.data.config.hp_id,
                    buy_price=self.buy.calculate_avg_buy_price(),
                    quantity=sum(order.realized_quantity for order in self.buy.orders)
                    - self.sell.current_position.sell_order.realized_quantity,
                    state=self.state,
                ),
            )
        )

        if all(order.status == ORDER_STATUS_FILLED for order in self.buy.orders):
            signal = Signal.HP_ALL_ORDERS_FILLED
            self.logger.info("All BUY orders filled, sending: %s", signal)
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
            self.logger.info(
                "[Partially filled buy order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_partially_filled_buy(self, *args, **kwargs):
        self.logger.debug("Entering handle order partially filled")

        self.buy.data.state_info.state = State.PARTIALLY_BOUGHT

        await self.buy.handle_order_partially_filled(
            execution_report=self.execution_report
        )

        self.db.upsert_buy_price_level(data=self.buy.data)

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=HPUpdate(
                    hp_id=self.buy.data.config.hp_id,
                    buy_price=self.buy.calculate_avg_buy_price(),
                    quantity=sum(order.realized_quantity for order in self.buy.orders)
                    - self.sell.current_position.sell_order.realized_quantity,
                    state=self.state,
                ),
            )
        )

    def conditions_for_order_filled_sell(self, *args, **kwargs) -> bool:
        assert self.sell
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_FILLED
            and self.execution_report.order_id
            == self.sell.current_position.sell_order.order_id
        )
        if condition:
            self.logger.info(
                "[Filled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_filled_sell(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle order filled sell")

        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        await self.sell.handle_order_filled(execution_report=self.execution_report)

        self.db.upsert_sell_price_level(data=self.sell.current_position)

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id,
                    state=self.state,
                    quantity=sum(order.realized_quantity for order in self.buy.orders)
                    - self.sell.current_position.sell_order.realized_quantity,
                ),
            ),
        )

        if self.sell.current_position.sell_order.status == ORDER_STATUS_FILLED:
            self.sell.current_position.state_info.state = State.SOLD
            self.sell.current_position.state_info.ui_state = UiState.CLOSED
            self.sell.current_position.state_info.completeness = 1.0

            signal = Signal.HP_ALL_ORDERS_FILLED
            self.logger.info("All SELL orders filled, sending: %s", signal)
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
            self.logger.info(
                "[Partially filled sell order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def handle_order_partially_filled_sell(self, *args, **kwargs):
        self.logger.debug("Entering handle order partially filled")

        self.sell.current_position.state_info.state = State.PARTIALLY_SOLD

        await self.sell.handle_order_partially_filled(
            execution_report=self.execution_report
        )

        self.logger.info("Sell order: %s", self.sell.current_position.sell_order)

        self.db.upsert_sell_price_level(data=self.sell.current_position)

        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id,
                    state=self.state,
                    quantity=sum(order.realized_quantity for order in self.buy.orders)
                    - self.sell.current_position.sell_order.realized_quantity,
                ),
            )
        )

    def conditions_for_position_stagnation_buy(self, *args, **kwargs) -> bool:
        date_time_now = datetime.now()

        condition = self.state == State.BUYING and date_time_now > datetime.strptime(
            self.buy.data.state_info.next_monitor_time, "%Y-%m-%d %H:%M:%S"
        )
        if condition:
            self.logger.info(
                "[Handle stagnation BUY]: %s, time now: %s, monitor time: %s",
                condition,
                date_time_now,
                self.buy.data.state_info.next_monitor_time,
            )
        return condition

    def increase_stagnation_counter_buy(self, *args, **kwargs) -> None:
        self.logger.info(
            "Entering increase stagnation coutner buy, counter before adding 1: %s",
            self.buy.data.state_info.stagnation_counter,
        )
        self.buy.data.state_info.stagnation_counter += 1

        if (
            self.buy.data.state_info.stagnation_counter
            < self.buy.data.state_info.stagnation_limit
        ):
            self.logger.info(
                "[%s]: stagnation counter increase to: %s, stagnation limit: %s",
                self.buy.data.config.hp_id,
                self.buy.data.state_info.stagnation_counter,
                self.buy.data.state_info.stagnation_limit,
            )
        else:
            self.logger.info(
                "[%s]: Stagnation limit reached, current price: %s, order cancel price: %s",
                self.buy.data.config.hp_id,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
            )

        self.buy.data.state_info.generate_next_monitor_time()

        self.buy.data.state_info.ui_state = UiState.OPEN
        self.buy.data.state_info.completeness = round(
            sum(order.realized_quantity for order in self.buy.orders)
            / sum(order.quantity for order in self.buy.orders),
            2,
        )

        self.logger.info("Orders: %s", self.buy.orders)

        self.ui_queue.put_nowait(
            HPGuiDataBuy(
                data=HPBuyData(
                    config=self.buy.data.config, state_info=self.buy.data.state_info
                ),
                hp_update=HPUpdate(hp_id=self.buy.data.config.hp_id, state=self.state),
            )
        )

        self.db.upsert_buy_price_level(data=self.buy.data)

    def conditions_for_position_stagnation_sell(self, *args, **kwargs) -> bool:
        assert self.sell
        date_time_now = datetime.now()

        condition = (
            self.sell is not None
            and self.state == State.SELLING
            and date_time_now
            > datetime.strptime(
                self.sell.current_position.state_info.next_monitor_time,
                "%Y-%m-%d %H:%M:%S",
            )
        )
        if condition:
            self.logger.info(
                "[Handle stagnation Sell]: %s, time now: %s, monitor time: %s",
                condition,
                date_time_now,
                self.sell.current_position.state_info.next_monitor_time,
            )

        return condition

    def increase_stagnation_counter_sell(self, *args, **kwargs) -> None:
        assert self.sell
        self.sell.current_position.state_info.stagnation_counter += 1

        if (
            self.sell.current_position.state_info.stagnation_counter
            < self.sell.current_position.state_info.stagnation_limit
        ):
            self.logger.info(
                "[%s]: stagnation counter increase to: %s, stagnation limit: %s",
                self.sell.current_position.config.hp_id,
                self.sell.current_position.state_info.stagnation_counter,
                self.sell.current_position.state_info.stagnation_limit,
            )
        else:
            self.logger.info(
                "[%s]: Stagnation limit reached, current price: %s, order cancel price: %s",
                self.sell.current_position.config.hp_id,
                self.ticker_update.last_price,
                self.buy.orders_cancel_price,
            )

        self.sell.current_position.state_info.generate_next_monitor_time()
        self.sell.current_position.state_info.ui_state = UiState.OPEN
        self.sell.current_position.state_info.completeness = (
            round(
                self.sell.current_position.sell_order.realized_quantity
                / self.sell.current_position.sell_order.quantity,
                2,
            )
            if self.sell.current_position.sell_order
            else 0
        )
        self.ui_queue.put_nowait(
            HPGuiDataSell(
                data=HPSellData(
                    config=self.sell.current_position.config,
                    state_info=self.sell.current_position.state_info,
                ),
                hp_update=HPUpdate(
                    hp_id=self.sell.current_position.config.hp_id, state=self.state
                ),
            )
        )
        self.db.upsert_sell_price_level(data=self.sell.current_position)

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
            self.logger.info(
                "[New Order] %s, order type: %s order status: %s",
                self.execution_report.symbol,
                self.execution_report.order_type,
                self.execution_report.current_order_status,
            )
        return condition

    async def confirm_new_order(self, *args, **kwargs) -> None:
        for order in self.buy.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "New order confirmation: %s", self.execution_report.order_id
                )

        if self.sell:
            if (
                self.sell.current_position.sell_order.order_id
                == self.execution_report.order_id
            ):
                self.sell.current_position.sell_order.status = (
                    self.execution_report.current_order_status
                )
                self.logger.debug(
                    "New order confirmation: %s", self.execution_report.order_id
                )

    def conditions_for_order_cancellation(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_CANCELED
            and self.execution_report.symbol == self.buy.data.config.symbol_info.symbol
        )
        if condition:
            self.logger.info(
                "[Cancelled order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.buy.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Cancelled order confirmation: %s", self.execution_report.order_id
                )
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
                self.logger.debug(
                    "Cancelled order confirmation: %s",
                    self.execution_report.order_id,
                )

    def conditions_for_order_expiration(self, *args, **kwargs) -> bool:
        condition = (
            self.execution_report.order_type == ORDER_TYPE_LIMIT
            and self.execution_report.current_order_status == ORDER_STATUS_EXPIRED
        )

        if condition:
            self.logger.info(
                "[Expired order] %s %s @ %s",
                self.execution_report.symbol,
                self.execution_report.side,
                self.execution_report.price,
            )
        return condition

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.buy.orders:
            if order.order_id == self.execution_report.order_id:
                order.status = self.execution_report.current_order_status
                order.order_id = self.execution_report.order_id
                self.logger.debug(
                    "Expired order confirmation: %s", self.execution_report.order_id
                )

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
                self.logger.debug(
                    "Expired order confirmation: %s", self.execution_report.order_id
                )

    def calculate_trigger_cancel_orders_price_sell(self):
        return self.sell.current_position.config.symbol_info.adjust_price(
            0.92 * self.sell.current_position.config.sell_price
        )

    async def allow_messages(self, *args, **kwargs) -> None:
        self.logger.info(
            "Ticker update from allow messages method: %s",
            self.ticker_update.last_price,
        )

    async def worker(self):
        self.logger.info("Worker start now, state: %s.", self.state)
        self.worker_active = True
        while not self.stop_event.is_set():
            try:
                event = self.worker_queue.get_nowait()
                assert isinstance(event, Event)

                self.logger.info("New event: %s", event)

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
                    await self.process_signal()  # pylint: disable=no-member

                self.worker_queue.task_done()
            except queue.Empty:
                # logger.info("Queue empty, waiting 0.1s")
                await asyncio.sleep(0.1)
        self.logger.info("Stop event IS SET, worker closed")
        self.worker_active = False
