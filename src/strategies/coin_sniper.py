import datetime
from logging_config import StrategyLogger
from src.common.identifiers import (
    BinanceClient,
    CoinSniperConfig,
    PositionSide,
    PositionStatus,
    Signal,
    StateSpot,
    TickerUpdate,
)
from src.df_handler import DfHandler
from src.gui.gui_handler import GuiHandlerSpot
from src.strategies.base import BaseSpotStrategy


class CoinSniper(BaseSpotStrategy):
    def __init__(
        self,
        client: BinanceClient,
        config: CoinSniperConfig,
        gui_handler: GuiHandlerSpot,
        logger: StrategyLogger,
        df_handler: DfHandler,
        balance: float,
    ):
        super().__init__(client, config, gui_handler, logger, df_handler, balance)
        self.config = config
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

        self.transitions += [
            {
                "trigger": "process_ticker",
                "source": [StateSpot.NEW, StateSpot.OPEN],
                "dest": "=",
                "after": "handle_ticker",
            },
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_skipping_same_signal",
                "after": "skip_signal",
            },
        ]

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

    async def monitor_position(self):
        stagnation_limit = 4

        orders_not_filled = all(
            order.status == self.client.ORDER_STATUS_NEW
            for order in self.position_handler.position.orders
        )

        if self.position_handler.stagnation_counter == stagnation_limit:
            self.position_handler.close_position()
        else:
            # 1. check whether one hour from sending orders has passed or whether all opened orders are filled.
            if orders_not_filled:
                self.position_handler.stagnation_counter += 1
            else:
                if all(
                    any(
                        prev_order.order_id == order.order_id
                        and prev_order.realized_quantity == order.realized_quantity
                        for order in self.position_handler.position.orders
                    )
                    for prev_order in self.position_handler.prev_orders
                ):
                    self.position_handler.stagnation_counter += 1
                else:
                    self.position_handler.stagnation_counter = 0
                    self.position_handler.prev_orders = (
                        self.position_handler.position.orders
                    )

    async def notify(self, event: TickerUpdate):
        self.ticker_update = event

        self.logger.info(
            "Handle ticker, ticker last price: %s, trigger order price: %s, side: %s",
            self.ticker_update.last_price,
            self.trigger_orders_price,
            self.config.side,
        )

        # if self.position_handler.position.status == PositionStatus.NEW:
        #     if (
        #         self.config.side == PositionSide.LONG
        #         and self.ticker_update.last_price < self.trigger_orders_price
        #     ):
        #         await self.position_handler.open_position(
        #             side=self.config.side,
        #             symbol=self.config.symbol,
        #             name=self.config.name,
        #             budget=self.config.budget,
        #             price_low=self.config.price_low,
        #             price_high=self.config.price_high,
        #             min_notional=float(
        #                 self.min_order_values[self.config.symbol]["minNotional"]
        #             ),
        #         )

        # if self.position_handler.position.status == PositionStatus.NEW:
        #     if (
        #         self.config.side == PositionSide.SHORT
        #         and self.ticker_update.last_price > self.trigger_orders_price
        #     ):
        #         await self.position_handler.open_position(
        #             side=self.config.side,
        #             symbol=self.config.symbol,
        #             name=self.config.name,
        #             budget=self.config.budget,
        #             price_low=self.config.price_low,
        #             price_high=self.config.price_high,
        #             min_notional=float(
        #                 self.min_order_values[self.config.symbol]["minNotional"]
        #             ),
        #         )

        else:
            # To Close it if the target is not reached and the price is again far from threshold
            all_orders_filled = all(
                order.status == self.client.ORDER_STATUS_FILLED
                for order in self.position_handler.position.orders
            )
            if all_orders_filled:
                self.position_handler.close_position()
            else:
                if (
                    datetime.datetime.now()
                    < self.position_handler.next_monitor_position_time
                ):
                    time_left = (
                        self.position_handler.next_monitor_position_time
                        - datetime.datetime.now()
                    )
                    minutes_left = time_left.total_seconds() / 60
                    self.logger.info(
                        f"{minutes_left:.2f} minutes left until next position monitoring."
                    )
                else:
                    self.position_handler.next_monitor_position_time += (
                        datetime.timedelta(hours=1)
                    )
                    await self.monitor_position()

    async def handle_ticker(self):
        pass
