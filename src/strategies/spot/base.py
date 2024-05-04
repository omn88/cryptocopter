from datetime import datetime, timedelta
from typing import Dict
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
from src.common.identifiers.spot import State, StrategyConfig
from src.common.identifiers.common import BinanceClient, PositionSide
from src.df_handler.futures import DfHandler
from src.gui.gui_handler.spot import GuiHandler
from src.position_handler.spot import PositionHandler
from src.strategies.base import BaseStrategy

STAGNATION_LIMIT = 8


class BaseSpotStrategy(BaseStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: StrategyConfig,
        gui_handler: GuiHandler,
        logger: StrategyLogger,
        df_handler: DfHandler,
        balance: float,
    ):
        super().__init__(client, logger, df_handler, balance)
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

        self.min_order_values = None
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
                    State.NEW,
                    State.OPEN,
                    State.STAGNATED,
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
                "trigger": "process_order",
                "source": State.OPEN,
                "dest": State.CLOSED,
                "conditions": "conditions_for_all_orders_filled",
                "before": "handle_position_closure",
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
                "trigger": "process_signal",
                "source": [State.NEW, State.STAGNATED],
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_long_orders",
                "after": "open_long",
            },
            {
                "trigger": "process_signal",
                "source": [State.NEW, State.STAGNATED],
                "dest": State.OPEN,
                "conditions": "conditions_for_sending_short_orders",
                "after": "open_short",
            },
            {
                "trigger": "process_signal",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_long_orders",
                "after": "cancel_long",
            },
            {
                "trigger": "process_signal",
                "source": State.OPEN,
                "dest": State.STAGNATED,
                "conditions": "conditions_for_cancelling_short_orders",
                "after": "cancel_short",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_increasing_stagnation",
                "after": "increase_stagnation",
            },
            {
                "trigger": "process_ticker",
                "source": State.OPEN,
                "dest": "=",
                "conditions": "conditions_for_zeroing_out_stagnation",
                "after": "zero_out_stagnation",
            },
        ]

    async def initialize(self):
        # Now you can await the _get_minimum_order_values method
        self.min_order_values = await self._get_minimum_order_values()
        # Additional initialization code can go here

    async def _get_minimum_order_values(self) -> Dict:
        exchange_info = await self.client.get_exchange_info()
        min_values = {}

        for symbol_info in exchange_info["symbols"]:
            filters = {f["filterType"]: f for f in symbol_info["filters"]}
            if "MIN_NOTIONAL" in filters:
                min_values[symbol_info["symbol"]] = {
                    "minNotional": filters["MIN_NOTIONAL"]["minNotional"]
                }

        return min_values

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
        condition = all(
            order.status == ORDER_STATUS_FILLED
            for order in self.position_handler.position.orders
        )

        self.logger.info("All orders filled: %s, order update status: %s", condition)
        return condition

    def conditions_for_sending_long_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state in [State.NEW, State.STAGNATED]
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

    def conditions_for_sending_short_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state in [State.NEW, State.STAGNATED]
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

    def conditions_for_cancelling_long_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.position_handler.position.side == PositionSide.LONG
            and self.position_handler.stagnation_counter == STAGNATION_LIMIT
            and self.ticker_update.last_price > self.trigger_orders_price
        )
        self.logger.info(
            "Cancel %s orders due to stagnation: %s, last price: %s",
            self.position_handler.position.side.value,
            condition,
            self.ticker_update.last_price,
        )

        return condition

    def conditions_for_cancelling_short_orders(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and self.position_handler.position.side == PositionSide.SHORT
            and self.position_handler.stagnation_counter == STAGNATION_LIMIT
            and self.ticker_update.last_price < self.trigger_orders_price
        )
        self.logger.info(
            "Cancel %s orders due to stagnation: %s, last price: %s",
            self.position_handler.position.side.value,
            condition,
            self.ticker_update.last_price,
        )

        return condition

    def conditions_for_increasing_stagnation(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.OPEN
            and datetime.now() > self.position_handler.next_monitor_position_time
        )
        self.logger.info("Stagnation counter increase due to")

        return condition

    async def open_long(
        self,
        symbol: str,
        side: PositionSide,
        price_high: float,
        price_low: float,
        budget: float,
        name: str,
        *args,
        **kwargs
    ) -> None:
        self.logger.debug("Opening %s", side.value)

        assert self.min_order_values

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
        side: PositionSide,
        price_high: float,
        price_low: float,
        budget: float,
        name: str,
        *args,
        **kwargs
    ) -> None:
        self.logger.debug("Opening %s", side.value)

        assert self.min_order_values

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

    async def cancel_long(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.position_handler.position.side)

        await self.position_handler.cancel_position()

    async def cancel_short(self, *args, **kwargs) -> None:
        self.logger.info("Cancelling %s", self.position_handler.position.side)
        await self.position_handler.cancel_position()

    async def handle_position_closure(self, *args, **kwargs) -> None:
        self.logger.info("All order filled, archiving position")

    async def increase_stagnation(self, *args, **kwargs) -> None:
        self.position_handler.stagnation_counter += 1
        self.position_handler.next_monitor_position_time += timedelta(hours=1)

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

        self.position_handler.stagnation_counter = 0
        self.position_handler.next_monitor_position_time = datetime.now() + timedelta(
            hours=1
        )

        await self.position_handler.handle_order_filled(order_update=self.order_update)

    async def handle_order_partially_filled(self, *args, **kwargs):
        self.logger.info("Entering handle order partially filled")

        self.position_handler.stagnation_counter = 0
        self.position_handler.next_monitor_position_time = datetime.now() + timedelta(
            hours=1
        )

        await self.position_handler.handle_order_partially_filled(
            order_update=self.order_update
        )


# import datetime
# from logging_config import StrategyLogger
# from src.common.identifiers.futures import (
#     PositionSide,
#     PositionStatus,
# )
# from src.common.identifiers.spot import CoinSniperConfig, State
# from src.df_handler.futures import DfHandler
# from src.gui.gui_handler import GuiHandlerSpot
# from src.common.identifiers.common import BinanceClient
# from src.strategies.spot.base import BaseSpotStrategy


# class CoinSniper(BaseSpotStrategy):
#     def __init__(
#         self,
#         client: BinanceClient,
#         config: CoinSniperConfig,
#         gui_handler: GuiHandlerSpot,
#         logger: StrategyLogger,
#         df_handler: DfHandler,
#         balance: float,
#     ):
#         super().__init__(client, config, gui_handler, logger, df_handler, balance)
#         self.config = config
#         self.trigger_orders_price = (
#             round(
#                 self.config.price_low * (1 - (self.config.order_trigger_buffer / 100)),
#                 2,
#             )
#             if self.config.side == PositionSide.SHORT
#             else round(
#                 self.config.price_high * (1 + (self.config.order_trigger_buffer / 100)),
#                 2,
#             )
#         )

#         self.transitions += [
#             {
#                 "trigger": "process_ticker",
#                 "source": [State.NEW, State.OPEN],
#                 "dest": "=",
#                 "after": "handle_ticker",
#             },
#             {
#                 "trigger": "process_signal",
#                 "source": "*",
#                 "dest": "=",
#                 "conditions": "conditions_for_skipping_same_signal",
#                 "after": "skip_signal",
#             },
#         ]

#     async def monitor_position(self):
#         stagnation_limit = 4

#         orders_not_filled = all(
#             order.status == self.client.ORDER_STATUS_NEW
#             for order in self.position_handler.position.orders
#         )

#         if self.position_handler.stagnation_counter == stagnation_limit:
#             self.position_handler.close_position()
#         else:
#             # 1. check whether one hour from sending orders has passed or whether all opened orders are filled.
#             if orders_not_filled:
#                 self.position_handler.stagnation_counter += 1
#             else:
#                 if all(
#                     any(
#                         prev_order.order_id == order.order_id
#                         and prev_order.realized_quantity == order.realized_quantity
#                         for order in self.position_handler.position.orders
#                     )
#                     for prev_order in self.position_handler.prev_orders
#                 ):
#                     self.position_handler.stagnation_counter += 1
#                 else:
#                     self.position_handler.stagnation_counter = 0
#                     self.position_handler.prev_orders = (
#                         self.position_handler.position.orders
#                     )

#     async def notify(self, event: TickerUpdate):
#         self.ticker_update = event

#         self.logger.info(
#             "Handle ticker, ticker last price: %s, trigger order price: %s, side: %s",
#             self.ticker_update.last_price,
#             self.trigger_orders_price,
#             self.config.side,
#         )

#                 if (
#                     datetime.datetime.now()
#                     < self.position_handler.next_monitor_position_time
#                 ):
#                     time_left = (
#                         self.position_handler.next_monitor_position_time
#                         - datetime.datetime.now()
#                     )
#                     minutes_left = time_left.total_seconds() / 60
#                     self.logger.info(
#                         f"{minutes_left:.2f} minutes left until next position monitoring."
#                     )
#                 else:
#                     self.position_handler.next_monitor_position_time += (
#                         datetime.timedelta(hours=1)
#                     )
#                     await self.monitor_position()
