import logging
from typing import Optional, Union

import binance
import pandas

from src.common.orders import Position, PositionMode
from src.features.features import State, Signal
from src.producers.producers import SignalUpdate
from src.workers import handle_order

logger = logging.getLogger("feature_rsi_extended")


class FeatureRsiSpecial:
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

    states = [State.LONG_SPECIAL, State.SHORT_SPECIAL]
    transitions = [
        {
            "trigger": "process_signal",
            "source": State.LONG,
            "dest": State.SHORT_SPECIAL,
            "conditions": "conditions_for_opening_special_short",
            "after": "open_special_short",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT,
            "dest": State.LONG_SPECIAL,
            "conditions": "conditions_for_opening_special_long",
            "after": "open_special_long",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG_SPECIAL,
            "dest": State.FLAT,
            "conditions": "conditions_for_closing_special_position",
            "before": "close_special_position",
            "after": "enter_flat",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT_SPECIAL,
            "dest": State.FLAT,
            "conditions": "conditions_for_closing_special_position",
            "before": "close_special_position",
            "after": "enter_flat",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG_SPECIAL,
            "dest": [State.SHORT, State.SHORT_80],
            "conditions": "conditions_for_skipping_when_long_special",
            "before": "skip_signal",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT_SPECIAL,
            "dest": [State.LONG, State.LONG_20],
            "conditions": "conditions_for_skipping_when_short_special",
            "before": "skip_signal",
        },
    ]

    def conditions_for_opening_special_short(self) -> bool:
        return (
            self.state == State.LONG
            and self.signal_update.signal == Signal.SHORT_SPECIAL
        )

    def conditions_for_opening_special_long(self) -> bool:
        return (
            self.state == State.SHORT
            and self.signal_update.signal == Signal.LONG_SPECIAL
        )

    def conditions_for_skipping_when_long_special(self) -> bool:
        return self.state == State.LONG_SPECIAL and self.signal_update.signal in [
            Signal.SHORT,
            Signal.SHORT_80,
        ]

    def conditions_for_skipping_when_short_special(self) -> bool:
        return self.state == State.SHORT_SPECIAL and self.signal_update.signal in [
            Signal.LONG,
            Signal.LONG_20,
        ]

    def conditions_for_closing_special_position(self) -> bool:
        return (
            self.state in [State.SHORT_SPECIAL, State.LONG_SPECIAL]
            and self.signal_update.signal == Signal.CLOSE_SPECIAL
        )

    async def open_special_long(self):
        logger.debug("Opening %s", self.signal_update.signal)

        self.mode = PositionMode.FULL

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

    async def open_special_short(self):
        logger.info("Opening %s", self.signal_update.signal)

        self.mode = PositionMode.FULL

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

    async def close_special_position(self):
        logger.info("Closing %s", self.position.status)
        self.position_old = await handle_order.close_special_position(
            client=self.client, position=self.position
        )
