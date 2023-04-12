import logging
from typing import Optional

import binance
import pandas

from src.common.identifiers import State, Signal, Position, SignalUpdate, PositionMode
from src.workers import handle_order
from src.workers.handle_order import prepare_and_send_orders

logger = logging.getLogger("feature_rsi_basic")


class FeatureRsiBasic:
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

    states = [State.LONG, State.SHORT]
    transitions = [
        {
            "trigger": "process_signal",
            "source": State.FLAT,
            "dest": State.LONG,
            "conditions": "conditions_for_opening_basic_long",
            "after": "open_basic_dca_long",
        },
        {
            "trigger": "process_signal",
            "source": State.FLAT,
            "dest": State.SHORT,
            "conditions": "conditions_for_opening_basic_short",
            "after": "open_basic_dca_short",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG,
            "dest": State.SHORT,
            "conditions": "conditions_for_switch_to_short",
            "before": "close_long",
            "after": "open_basic_dca_short",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT,
            "dest": State.LONG,
            "conditions": "conditions_for_switch_to_long",
            "before": "close_short",
            "after": "open_basic_dca_long",
        },
    ]

    def conditions_for_opening_long(self) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.LONG

    def conditions_for_opening_short(self) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.SHORT

    def conditions_for_switch_to_short(self) -> bool:
        return self.state == State.LONG and self.signal_update.signal == Signal.SHORT

    def conditions_for_switch_to_long(self) -> bool:
        return self.state == State.SHORT and self.signal_update.signal == Signal.LONG

    async def open_basic_dca_long(self):
        logger.debug("Opening %s", self.signal_update.signal)

        self.position = await prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            df=self.df,
            mode=self.mode,
        )

    async def open_basic_dca_short(self):
        logger.info("Opening %s", self.signal_update.signal)

        self.position = await prepare_and_send_orders(
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
