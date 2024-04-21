import asyncio
from typing import List
from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    FUTURE_ORDER_TYPE_LIMIT,
    FUTURE_ORDER_TYPE_MARKET,
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_EXPIRED,
    ORDER_TYPE_LIMIT,
    ORDER_TYPE_MARKET,
)
from logging_config import StrategyLogger
from src.common.common import signal_to_state
from src.common.identifiers import (
    AccountUpdate,
    PositionMode,
    PositionSide,
    PositionStatus,
    SignalUpdate,
    OrderUpdate,
    KlineUpdate,
    Signal,
    BinanceClient,
    State,
    StrategyConfig,
)
from src.df_handler import DfHandler
from src.gui.gui_handler import GuiHandlerFutures, GuiHandlerSpot
from src.position_handler import PositionHandlerFutures, PositionHandlerSpot


class BaseStrategy:
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        logger: StrategyLogger,
        df_handler: DfHandler,
        balance: float,
    ):
        self.client = client
        self.config = config
        self.logger = logger
        self.df_handler = df_handler
        self.balance = balance
        self.queue: asyncio.Queue = asyncio.Queue()

        # Initialize any other common attributes
        self.signal_update: SignalUpdate = SignalUpdate()
        self.order_update: OrderUpdate = OrderUpdate()
        self.kline_update: KlineUpdate = KlineUpdate()
        self.account_update: AccountUpdate = AccountUpdate(account_update={})
        self.transitions: List = []


class BaseFuturesStrategy(BaseStrategy):
    def __init__(
        self,
        client: BinanceClient,
        balance: float,
        config: StrategyConfig,
        gui_handler: GuiHandlerFutures,
        logger: StrategyLogger,
        df_handler: DfHandler,
    ):
        super().__init__(client, config, logger, df_handler, balance)
        self.gui_handler: GuiHandlerFutures = gui_handler
        self.position_handler = PositionHandlerFutures(
            client=client,
            strategy_logger=logger,
            config=config,
            gui_handler=gui_handler,
        )
        self.state = State.FLAT
        self.mode = PositionMode.DCA
        self.states = [State.LONG, State.SHORT]
        self.transitions = [
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_no_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_skipping_same_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_kline",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.FLAT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "after": "handle_kline",
            },
            {
                "trigger": "process_account",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.FLAT,
                    State.SHORT_SPECIAL,
                    State.LONG_SPECIAL,
                ],
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "confirm_new_order",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.FLAT,
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "confirm_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "confirm_expired_order",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_partial_position_liquidation",
                "before": "handle_partial_liquidation",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": State.FLAT,
                "conditions": "conditions_for_position_liquidation",
                "before": "handle_liquidation",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_target_partially_reached",
                "before": "handle_target_partially_reached",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": State.FLAT,
                "conditions": "conditions_for_target_reached",
                "before": "handle_target_reached",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled",
                "before": "confirm_market_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled_partially",
                "before": "confirm_market_order_filled_partially",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [
                    State.LONG,
                    State.LONG_EXT,
                    State.SHORT,
                    State.SHORT_EXT,
                    State.LONG_SPECIAL,
                    State.SHORT_SPECIAL,
                ],
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled",
                "before": "handle_order_partially_filled",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.LONG,
                "conditions": "conditions_for_opening_basic_long",
                "after": "open_long",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.SHORT,
                "conditions": "conditions_for_opening_basic_short",
                "after": "open_short",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_to_short",
                "before": "close_long",
                "after": "open_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_to_long",
                "before": "close_short",
                "after": "open_long",
            },
        ]

    def conditions_for_no_signal(self, *args, **kwargs) -> bool:
        condition = self.signal_update.signal == Signal.NULL

        self.logger.info(
            "Skip no signal: %s, signal: %s", condition, self.signal_update.signal
        )

        return condition

    def conditions_for_skipping_same_signal(self, *args, **kwargs) -> bool:
        condition = self.state == signal_to_state(self.signal_update.signal).value
        self.logger.info(
            "Skip same signal: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def conditions_for_position_liquidation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == "LIQUIDATION"
            and self.order_update.status == ORDER_STATUS_FILLED
        )
        self.logger.info(
            "Position liquidation: %s, order update type: %s",
            condition,
            self.order_update.order_type,
        )
        return condition

    def conditions_for_partial_position_liquidation(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == "LIQUIDATION"
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )

        self.logger.info(
            "Partial position liquidation: %s, order update type: %s",
            condition,
            self.order_update.order_type,
        )
        return condition

    def conditions_for_new_order_confirmation(self, *args, **kwargs) -> bool:
        # This has to figure out whether this is new target order or just limit dca, or not?

        condition = (
            self.order_update.order_type
            in [
                FUTURE_ORDER_TYPE_LIMIT,
                FUTURE_ORDER_TYPE_MARKET,
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
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
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
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_EXPIRED
        )
        self.logger.info(
            "Order expired: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position_handler.position.take_profit_order.price
            == self.order_update.price
            and self.order_update.status == ORDER_STATUS_FILLED
            and self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
        )
        self.logger.info(
            "Target reached: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_partially_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position_handler.position.take_profit_order.price
            == self.order_update.price
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
        )
        self.logger.info(
            "Target partially reached: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == ORDER_STATUS_FILLED
        )
        self.logger.info(
            "Market order filled: %s, state: %s order update status: %s",
            condition,
            self.position_handler.position.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled_partially(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_MARKET
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.info(
            "Market order partially filled: %s, state: %s order update status: %s",
            condition,
            self.position_handler.position.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_order_filled(self, *args, **kwargs):
        condition = (
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
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
            self.order_update.order_type == FUTURE_ORDER_TYPE_LIMIT
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.info(
            "Order partially filled: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_opening_basic_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.LONG
        )
        self.logger.info(
            "Open basic long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_opening_basic_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.SHORT
        )
        self.logger.info(
            "Open basic short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_switch_to_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.LONG and self.signal_update.signal == Signal.SHORT
        )
        self.logger.info(
            "Switch to short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def conditions_for_switch_to_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.SHORT and self.signal_update.signal == Signal.LONG
        )
        self.logger.info(
            "Switch to long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def skip_signal(self, *args, **kwargs) -> None:
        self.logger.info("Skipping signal: %s", self.signal_update.signal)
        self.df_handler.df.at[
            self.df_handler.df.index[-1], "Position"
        ] = self.df_handler.df.at[self.df_handler.df.index[-2], "Position"]

    async def open_long(self, *args, **kwargs):
        self.logger.debug("Opening %s", self.signal_update.signal)

        side = PositionSide.LONG

        await self.position_handler.open_position_futures(
            side=side,
            config=self.config,
            mode=self.mode,
            signal_update=self.signal_update,
        )

        self.df_handler.update_position_in_df(
            update=State(self.signal_update.signal.value)
        )

    async def open_short(self, *args, **kwargs) -> None:
        self.logger.info("Opening %s", self.signal_update.signal)

        side = PositionSide.SHORT

        await self.position_handler.open_position_futures(
            side=side,
            config=self.config,
            mode=self.mode,
            signal_update=self.signal_update,
        )
        self.df_handler.update_position_in_df(
            update=self.position_handler.position.state
        )

    async def close_long(self, *args, **kwargs) -> None:
        self.logger.info("Closing %s", self.position_handler.position.state)

        await self.position_handler.close_position()

        self.df_handler.update_position_in_df(
            update=State(self.signal_update.signal.value)
        )

    async def close_short(self, *args, **kwargs) -> None:
        self.logger.info("Closing %s", self.position_handler.position.state)
        await self.position_handler.close_position()

        self.df_handler.update_position_in_df(
            update=State(self.signal_update.signal.value)
        )

    async def confirm_new_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "New order confirmation: %s", self.order_update.order_id
                )

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Cancelled order confirmation: %s", self.order_update.order_id
                )

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Expired order confirmation: %s", self.order_update.order_id
                )
                await self.gui_handler.update_order(
                    order=order,
                    symbol=self.position_handler.position.symbol,
                    side=self.position_handler.position.side,
                )

    async def handle_account(self, *args, **kwargs) -> None:
        self.logger.info("Account update: %s", self.account_update.account_update)

    async def handle_liquidation(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle liquidation")
        self.balance = await self.position_handler.position_liquidation(
            balance=self.balance
        )
        self.position_handler.position.state = State.FLAT

        await self.gui_handler.update_position(
            position=self.position_handler.closed_positions[-1]
        )

    async def handle_partial_liquidation(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle partial liquidation")
        await self.position_handler.partial_position_liquidation(
            order_update=self.order_update
        )

    async def enter_flat(self, *args, **kwargs) -> None:
        self.logger.info("Entering Flat")
        self.df_handler.update_position_in_df(update=State.FLAT)

    async def handle_target_reached(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle target order filled")
        self.balance = await self.position_handler.target_reached(
            order_update=self.order_update, balance=self.balance
        )

        self.position_handler.position.state = State.FLAT

    async def handle_target_partially_reached(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle target order partially filled")

        self.balance = await self.position_handler.target_partially_reached(
            order_update=self.order_update,
            balance=self.balance,
        )

    async def confirm_market_order_filled(self, *args, **kwargs) -> None:
        self.logger.info("MARKET order filled!")
        market_order = self.position_handler.closed_positions[-1].market_order

        assert market_order is not None

        market_order.status = self.order_update.status
        market_order.price = self.order_update.price
        market_order.quantity = self.order_update.quantity
        market_order.realized_quantity = self.order_update.realized_quantity
        self.position_handler.closed_positions[-1].status = PositionStatus.CLOSED
        self.position_handler.position.state = State.FLAT

        await self.gui_handler.update_position(position=self.position_handler.position)
        await self.gui_handler.update_strategy(
            position=self.position_handler.position, strategy_name=self.config.name
        )

    async def confirm_market_order_filled_partially(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle market order partially filled")

        market_order = self.position_handler.closed_positions[-1].market_order

        market_order.status = self.order_update.status
        market_order.price = self.order_update.price
        market_order.quantity = self.order_update.quantity
        market_order.realized_quantity = self.order_update.realized_quantity
        self.logger.info(
            "Market order realization in progress: %s!",
            self.position_handler.closed_positions[-1].market_order,
        )

    async def handle_order_filled(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle order filled")

        await self.position_handler.handle_order_filled(order_update=self.order_update)

    async def handle_order_partially_filled(self, *args, **kwargs) -> None:
        self.logger.info("Entering handle order partially filled")

        await self.position_handler.handle_order_partially_filled(
            order_update=self.order_update
        )


class BaseSpotStrategy(BaseStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        gui_handler: GuiHandlerSpot,
        logger: StrategyLogger,
        df_handler: DfHandler,
    ):
        super().__init__(client, config, logger, df_handler)
        self.gui_handler = gui_handler
        self.position_handler = PositionHandlerSpot(
            client=client,
            strategy_logger=logger,
            config=config,
            gui_handler=gui_handler,
        )
        self.state = State.FLAT
        self.mode = PositionMode.DCA
        self.states = [State.LONG, State.SHORT]

        self.transitions = [
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_no_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_skipping_same_signal",
                "after": "skip_signal",
            },
            {
                "trigger": "process_kline",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "after": "handle_kline",
            },
            {
                "trigger": "process_account",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "confirm_new_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "confirm_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "confirm_expired_order",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_target_partially_reached",
                "before": "handle_target_partially_reached",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": State.FLAT,
                "conditions": "conditions_for_target_reached",
                "before": "handle_target_reached",
                "after": "enter_flat",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled",
                "before": "confirm_market_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_market_order_filled_partially",
                "before": "confirm_market_order_filled_partially",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": [State.LONG, State.SHORT, State.FLAT],
                "dest": "=",
                "conditions": "conditions_for_order_partially_filled",
                "before": "handle_order_partially_filled",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.LONG,
                "conditions": "conditions_for_opening_basic_long",
                "after": "open_long",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.SHORT,
                "conditions": "conditions_for_opening_basic_short",
                "after": "open_short",
            },
        ]

    def conditions_for_no_signal(self, *args, **kwargs) -> bool:
        condition = self.signal_update.signal == Signal.NULL

        self.logger.info(
            "Skip no signal: %s, signal: %s", condition, self.signal_update.signal
        )

        return condition

    def conditions_for_skipping_same_signal(self, *args, **kwargs) -> bool:
        condition = self.state == signal_to_state(self.signal_update.signal).value
        self.logger.info(
            "Skip same signal: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

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

    def conditions_for_target_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position_handler.position.take_profit_order.price
            == self.order_update.price
            and self.order_update.status == ORDER_STATUS_FILLED
            and self.order_update.order_type == ORDER_TYPE_LIMIT
        )
        self.logger.info(
            "Target reached: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_target_partially_reached(self, *args, **kwargs) -> bool:
        condition = (
            self.position_handler.position.take_profit_order.price
            == self.order_update.price
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
            and self.order_update.order_type == ORDER_TYPE_LIMIT
        )
        self.logger.info(
            "Target partially reached: %s, order update status: %s",
            condition,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == ORDER_TYPE_MARKET
            and self.order_update.status == ORDER_STATUS_FILLED
        )
        self.logger.info(
            "Market order filled: %s, state: %s order update status: %s",
            condition,
            self.position_handler.position.state,
            self.order_update.status,
        )
        return condition

    def conditions_for_market_order_filled_partially(self, *args, **kwargs) -> bool:
        condition = (
            self.order_update.order_type == ORDER_TYPE_MARKET
            and self.order_update.status == ORDER_STATUS_PARTIALLY_FILLED
        )
        self.logger.info(
            "Market order partially filled: %s, state: %s order update status: %s",
            condition,
            self.position_handler.position.state,
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

    def conditions_for_opening_basic_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.LONG
        )
        self.logger.info(
            "Open basic long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_opening_basic_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.SHORT
        )
        self.logger.info(
            "Open basic short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def skip_signal(self, *args, **kwargs) -> None:
        self.logger.info("Skipping signal: %s", self.signal_update.signal)
        self.df_handler.df.at[
            self.df_handler.df.index[-1], "Position"
        ] = self.df_handler.df.at[self.df_handler.df.index[-2], "Position"]

    async def open_long(self, *args, **kwargs):
        self.logger.debug("Opening %s", self.signal_update.signal)

        side = PositionSide.LONG

        await self.position_handler.open_position_spot(
            side=side,
            config=self.config,
            mode=self.mode,
            signal_update=self.signal_update,
        )

        # self.df_handler.update_position_in_df(
        #     update=State(self.signal_update.signal.value)
        # )

    async def open_short(self, *args, **kwargs):
        self.logger.info("Opening %s", self.signal_update.signal)

        side = PositionSide.SHORT

        await self.position_handler.open_position_spot(
            side=side,
            config=self.config,
            mode=self.mode,
            signal_update=self.signal_update,
        )
        # self.df_handler.update_position_in_df(
        #     update=self.position_handler.position.state
        # )

    async def close_long(self, *args, **kwargs):
        self.logger.info("Closing %s", self.position_handler.position.state)

        await self.position_handler.close_position_spot()

        # self.df_handler.update_position_in_df(
        #     update=State(self.signal_update.signal.value)
        # )

    async def close_short(self, *args, **kwargs):
        self.logger.info("Closing %s", self.position_handler.position.state)
        await self.position_handler.close_position_spot()

        # self.df_handler.update_position_in_df(
        #     update=State(self.signal_update.signal.value)
        # )

    async def confirm_new_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "New order confirmation: %s", self.order_update.order_id
                )

    async def confirm_cancelled_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Cancelled order confirmation: %s", self.order_update.order_id
                )

    async def confirm_expired_order(self, *args, **kwargs) -> None:
        for order in self.position_handler.position.orders:
            if order.order_id == self.order_update.order_id:
                order.status = self.order_update.status
                order.order_id = self.order_update.order_id
                self.logger.info(
                    "Expired order confirmation: %s", self.order_update.order_id
                )
                await self.gui_handler.update_order(
                    order=order,
                    symbol=self.position_handler.position.symbol,
                    side=self.position_handler.position.side,
                )

    async def handle_account(self, *args, **kwargs):
        self.logger.info("Account update: %s", self.account_update.account_update)

    async def enter_flat(self, *args, **kwargs):
        self.logger.info("Entering Flat")
        # self.df_handler.update_position_in_df(update=State.FLAT)

    async def handle_target_reached(self, *args, **kwargs):
        self.logger.info("Entering handle target order filled")
        self.balance = await self.position_handler.target_reached_spot(
            order_update=self.order_update, balance=self.balance
        )

        self.position_handler.position.state = State.FLAT

    async def handle_target_partially_reached(self, *args, **kwargs):
        self.logger.info("Entering handle target order partially filled")

        self.balance = await self.position_handler.target_partially_reached_spot(
            order_update=self.order_update,
            balance=self.balance,
        )

    async def confirm_market_order_filled(self, *args, **kwargs):
        self.logger.info("MARKET order filled!")
        market_order = self.position_handler.closed_positions[-1].market_order

        assert market_order is not None

        market_order.status = self.order_update.status
        market_order.price = self.order_update.price
        market_order.quantity = self.order_update.quantity
        market_order.realized_quantity = self.order_update.realized_quantity
        self.position_handler.closed_positions[-1].status = PositionStatus.CLOSED
        self.position_handler.position.state = State.FLAT

        await self.gui_handler.update_position(position=self.position_handler.position)
        await self.gui_handler.update_strategy(
            position=self.position_handler.position, strategy_name=self.config.name
        )

    async def confirm_market_order_filled_partially(self, *args, **kwargs):
        self.logger.info("Entering handle market order partially filled")

        market_order = self.position_handler.closed_positions[-1].market_order

        market_order.status = self.order_update.status
        market_order.price = self.order_update.price
        market_order.quantity = self.order_update.quantity
        market_order.realized_quantity = self.order_update.realized_quantity
        self.logger.info(
            "Market order realization in progress: %s!",
            self.position_handler.closed_positions[-1].market_order,
        )

    async def handle_order_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order filled")

        await self.position_handler.handle_order_filled(order_update=self.order_update)

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order partially filled")

        await self.position_handler.handle_order_partially_filled_spot(
            order_update=self.order_update
        )
