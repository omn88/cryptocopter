import logging
import numpy

from src.common.identifiers import State, Signal, PositionSide
from src.workers import handle_order
from src.workers.handle_order import prepare_and_send_orders, signal_to_state

logger = logging.getLogger("feature_rsi_basic")


class FeatureRsiBasic:
    def __init__(self, df):

        self.df = self.add_columns_for_rsi_basic(df=df)
        self.signals = [Signal.LONG, Signal.SHORT]
        self.conditions = [
            (self.df.RsiBelowThirty.diff() == 0)
            & (self.df.RsiBelowThirty.diff(periods=2) == -1),
            (self.df.RsiAboveSeventy.diff() == 0)
            & (self.df.RsiAboveSeventy.diff(periods=2) == -1),
        ]

        self.states = [State.LONG, State.SHORT]
        self.transitions = [
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.LONG,
                "conditions": "conditions_for_opening_basic_long",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.SHORT,
                "conditions": "conditions_for_opening_basic_short",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_to_short",
                "before": "close_long",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_to_long",
                "before": "close_short",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": "*",
                "dest": "=",
                "conditions": "conditions_for_no_signal",
                "after": "skip_signal",
            },
        ]

    @staticmethod
    def add_columns_for_rsi_basic(df):
        df["RsiBelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
        df["RsiAboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)
        return df

    def conditions_for_opening_basic_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT and self.signal_update.signal == Signal.LONG
        )
        logger.info(
            "Open basic long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_opening_basic_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT and self.signal_update.signal == Signal.SHORT
        )
        logger.info(
            "Open basic short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_no_signal(self, *args, **kwargs) -> bool:
        condition = (
            self.state in [State.LONG, State.SHORT, State.FLAT]
            and self.signal_update.signal == Signal.NULL
        )
        logger.info(
            "Skip no signal (NULL): %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def conditions_for_switch_to_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.LONG and self.signal_update.signal == Signal.SHORT
        )
        logger.info(
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
        logger.info(
            "Switch to long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    async def open_dca_long(self, *args, **kwargs):
        logger.debug("Opening %s", self.signal_update.signal)

        self.position.side = PositionSide.LONG

        self.position = await prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            mode=self.mode,
        )

        self.update_position_in_df(update=State(self.signal_update.signal.value))

    async def open_dca_short(self, *args, **kwargs):
        logger.info("Opening %s", self.signal_update.signal)

        self.position.side = PositionSide.SHORT

        self.position = await prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            mode=self.mode,
        )

        self.update_position_in_df(
            update=signal_to_state(signal=self.signal_update.signal)
        )

    async def close_long(self, *args, **kwargs):
        logger.info("Closing %s", self.position.status)
        self.position_old = await handle_order.close_long(
            client=self.client, balance=self.balance, position=self.position
        )

    async def close_short(self, *args, **kwargs):
        logger.info("Closing %s", self.position.status)
        self.position_old = await handle_order.close_short(
            client=self.client, balance=self.balance, position=self.position
        )

    def skip_signal(self, *args, **kwargs) -> None:
        logger.info("Skipping signal: %s", self.signal_update.signal)
