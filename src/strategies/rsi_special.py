import logging

from src.common.identifiers import State, Signal, PositionMode

from src.strategies.rsi_extended import ExtendedStrategy
from src.workers import handle_order


logger = logging.getLogger("SpecialStrategy")


class SpecialStrategy(ExtendedStrategy):
    def __init__(self, client, balance, order_quantity_list, df, position, raw_data):
        super().__init__(
            client=client,
            balance=balance,
            order_quantity_list=order_quantity_list,
            df=df,
            position=position,
            raw_data=raw_data,
        )

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
            mode=self.mode,
        )

    async def close_special_position(self):
        logger.info("Closing %s", self.position.status)
        self.position_old = await handle_order.close_special_position(
            client=self.client, position=self.position
        )
