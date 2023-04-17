import logging
from typing import Optional

import binance
import numpy
import pandas

from src.common.identifiers import Position, State, SignalUpdate, Signal, PositionMode
from src.workers import handle_order

logger = logging.getLogger("feature_rsi_extended")


class FeatureRsiExtended:
    def __init__(self, df, client, balance, order_quantity_list, position, mode):
        self.client: binance.AsyncClient = client
        self.balance: float = balance
        self.df = df
        self.position: Position = position
        self.position_old: Optional[Position] = None
        self.order_quantity_list: pandas.DataFrame = order_quantity_list
        self.state: State = State.FLAT
        self.signal_update: SignalUpdate = SignalUpdate(signal=Signal.NULL, price=0)
        self.mode: PositionMode = mode
        self.extended_signal_conditions = []
        self.extended_signals_list = []

    states = [State.LONG_20, State.SHORT_80]
    transitions = [
        {
            "trigger": "process_signal",
            "source": State.FLAT,
            "dest": State.LONG_20,
            "conditions": "conditions_for_opening_extended_long",
            "after": "open_extended_dca_long",
        },
        {
            "trigger": "process_signal",
            "source": State.FLAT,
            "dest": State.SHORT_80,
            "conditions": "conditions_for_opening_extended_short",
            "after": "open_extended_dca_short",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG_20,
            "dest": State.SHORT_80,
            "conditions": "conditions_for_switch_from_extended_long_to_extended_short",
            "before": "close_long",
            "after": "open_extended_dca_short",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT_80,
            "dest": State.LONG_20,
            "conditions": "conditions_for_switch_from_extended_short_to_extended_long",
            "before": "close_short",
            "after": "open_extended_dca_long",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG_20,
            "dest": State.SHORT,
            "conditions": "conditions_for_switch_from_extended_long_to_basic_short",
            "before": "close_long",
            "after": "open_basic_dca_short",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT_80,
            "dest": State.LONG,
            "conditions": "conditions_for_switch_from_extended_short_to_basic_long",
            "before": "close_short",
            "after": "open_basic_dca_long",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG_20,
            "dest": State.LONG,
            "conditions": "conditions_for_switch_from_extended_long_to_basic_long",
            "before": "change_position_state",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT_80,
            "dest": State.SHORT,
            "conditions": "conditions_for_switch_from_extended_short_to_basic_short",
            "before": "change_position_state",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG,
            "dest": State.LONG_20,
            "conditions": "conditions_for_skipping_extended_signal",
            "before": "skip_signal",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT,
            "dest": State.SHORT_80,
            "conditions": "conditions_for_skipping_extended_signal",
            "before": "skip_signal",
        },
    ]

    signals = [Signal.LONG_20, Signal.SHORT_80]

    conditions = [
        lambda df: (df.RsiBelowTwenty.diff() == -1),
        lambda df: (df.RsiAboveEighty.diff() == -1),
    ]

    @staticmethod
    def add_columns_for_rsi_extended(df):
        df["RsiBelowTwenty"] = numpy.where(df["RSI"] < 20, 1, 0)
        df["RsiAboveEighty"] = numpy.where(df["RSI"] > 80, 1, 0)
        return df

    def conditions_for_opening_extended_long(self) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.LONG_20

    def conditions_for_opening_extended_short(self) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.SHORT_80

    def conditions_for_switch_from_extended_long_to_extended_short(self) -> bool:
        return (
            self.state == State.LONG_20 and self.signal_update.signal == Signal.SHORT_80
        )

    def conditions_for_switch_from_extended_short_to_extended_long(self) -> bool:
        return (
            self.state == State.SHORT_80 and self.signal_update.signal == Signal.LONG_20
        )

    def conditions_for_switch_from_extended_long_to_basic_short(self) -> bool:
        return self.state == State.LONG_20 and self.signal_update.signal == Signal.SHORT

    def conditions_for_switch_from_extended_short_to_basic_long(self) -> bool:
        return self.state == State.SHORT_80 and self.signal_update.signal == Signal.LONG

    def conditions_for_switch_from_extended_long_to_basic_long(self) -> bool:
        return self.state == State.LONG_20 and self.signal_update.signal == Signal.LONG

    def conditions_for_switch_from_extended_short_to_basic_short(self) -> bool:
        return (
            self.state == State.SHORT_80 and self.signal_update.signal == Signal.SHORT
        )

    def conditions_for_skipping_extended_signal(self) -> bool:
        return (
            self.state == State.LONG
            and self.signal_update.signal == Signal.LONG_20
            or self.state == State.SHORT
            and self.signal_update.signal == Signal.SHORT_80
        )

    async def open_extended_dca_long(self):
        logger.debug("Opening %s", self.signal_update.signal)

        self.position = await handle_order.prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            df=self.df,
            mode=self.mode,
        )

    async def open_extended_dca_short(self):
        logger.info("Opening %s", self.signal_update.signal)

        self.position = await handle_order.prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            df=self.df,
            mode=self.mode,
        )

    async def close_long(self):
        logger.info("Closing %s", self.position.status)
        self.position_old = await handle_order.close_long(
            client=self.client, balance=self.balance, position=self.position
        )

    async def close_short(self):
        logger.info("Closing %s", self.position.status)
        self.position_old = await handle_order.close_short(
            client=self.client, balance=self.balance, position=self.position
        )

    async def change_position_state(self):
        logger.info("Changing status to %s", self.signal_update.signal)
        self.position.status = self.signal_update.signal
