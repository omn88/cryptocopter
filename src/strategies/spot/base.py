import asyncio
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
from src.common.common import signal_to_state
from src.common.identifiers.futures import (
    PositionSide,
    Signal,
    BinanceClient,
    State,
    StateSpot,
    StrategyConfig,
)
from src.df_handler import DfHandler
from src.gui.gui_handler import GuiHandlerSpot
from src.position_handler import PositionHandlerSpot
from src.strategies.base import BaseStrategy


class BaseSpotStrategy(BaseStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        gui_handler: GuiHandlerSpot,
        logger: StrategyLogger,
        df_handler: DfHandler,
        balance: float,
    ):
        super().__init__(client, config, logger, df_handler, balance)
        self.gui_handler = gui_handler
        self.position_handler = PositionHandlerSpot(
            client=client,
            strategy_logger=logger,
            config=config,
            gui_handler=gui_handler,
        )
        self.state = StateSpot.NEW
        self.states = [
            StateSpot.NEW,
            StateSpot.OPEN,
            StateSpot.STAGNATED,
            StateSpot.CLOSED,
        ]

        self.min_order_values = asyncio.create_task(self._get_minimum_order_values())
        self.trigger_orders_price = (
            round(
                self.config.price_low * (1 - (self.config.order_trigger_buffer / 100)),
                2,
            )
            if self.config.side == PositionSide.SHORT
            else round(
                self.config.price_high * (1 + (self.config.order_trigger_buffer / 100)),
                2,
            )
        )

        self.transitions = [
            {
                "trigger": "process_account",
                "source": [
                    StateSpot.NEW,
                    StateSpot.OPEN,
                    StateSpot.STAGNATED,
                ],
                "dest": "=",
                "after": "handle_account",
            },
            {
                "trigger": "process_order",
                "source": [StateSpot.OPEN, StateSpot.STAGNATED],
                "dest": "=",
                "conditions": "conditions_for_new_order_confirmation",
                "after": "confirm_new_order",
            },
            {
                "trigger": "process_order",
                "source": [StateSpot.OPEN, StateSpot.STAGNATED],
                "dest": "=",
                "conditions": "conditions_for_order_cancellation",
                "after": "confirm_cancelled_order",
            },
            {
                "trigger": "process_order",
                "source": StateSpot.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_expiration",
                "after": "confirm_expired_order",
            },
            {
                "trigger": "process_order",
                "source": StateSpot.OPEN,
                "dest": "=",
                "conditions": "conditions_for_order_filled",
                "before": "handle_order_filled",
            },
            {
                "trigger": "process_order",
                "source": StateSpot.OPEN,
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

    async def _get_minimum_order_values(self):
        exchange_info = await self.client.get_exchange_info()
        min_values = {}

        for symbol_info in exchange_info["symbols"]:
            filters = {f["filterType"]: f for f in symbol_info["filters"]}
            if "MIN_NOTIONAL" in filters:
                min_values[symbol_info["symbol"]] = {
                    "minNotional": filters["MIN_NOTIONAL"]["minNotional"]
                }

        return min_values

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
            self.state in [StateSpot.NEW, StateSpot.STAGNATED]
            and self.config.side == PositionSide.LONG
            and self.ticker_update.last_price < self.trigger_orders_price
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
            self.state in [StateSpot.NEW, StateSpot.STAGNATED]
            and self.config.side == PositionSide.SHORT
            and self.ticker_update.last_price > self.trigger_orders_price
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

    async def open_long(
        self,
        symbol: str,
        side: str,
        price_high: float,
        price_low: float,
        budget: float,
        name: str,
        *args,
        **kwargs
    ):
        self.logger.debug("Opening %s", self.signal_update.signal)

        side = PositionSide.LONG

        await self.position_handler.open_position(
            side=side,
            budget=budget,
            price_high=price_high,
            price_low=price_low,
            name=name,
            symbol=symbol,
            min_notional=float(
                self.min_order_values[self.config.symbol]["minNotional"]
            ),
        )

    async def open_short(
        self,
        symbol: str,
        side: str,
        price_high: float,
        price_low: float,
        budget: float,
        name: str,
        *args,
        **kwargs
    ):
        self.logger.info("Opening %s", self.signal_update.signal)

        side = PositionSide.SHORT

        await self.position_handler.open_position(
            side=side,
            min_notional=float(
                self.min_order_values[self.config.symbol]["minNotional"]
            ),
            budget=budget,
            price_high=price_high,
            price_low=price_low,
            name=name,
            symbol=symbol,
        )

    async def close_long(self, *args, **kwargs):
        self.logger.info("Closing %s", self.position_handler.position.state)

        await self.position_handler.close_position()

    async def close_short(self, *args, **kwargs):
        self.logger.info("Closing %s", self.position_handler.position.state)
        await self.position_handler.close_position()

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

    async def handle_order_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order filled")

        await self.position_handler.handle_order_filled(order_update=self.order_update)

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order partially filled")

        await self.position_handler.handle_order_partially_filled(
            order_update=self.order_update
        )
