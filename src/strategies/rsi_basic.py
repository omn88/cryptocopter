import numpy
import pandas

from src.common.identifiers import PositionSide, State, Signal
from src.features.rsi_basic import FeatureRsiBasic
from src.workers import handle_order
from src.workers.handle_order import prepare_and_send_orders, signal_to_state
from src.workers.trading_state_machine import TradingStateMachine


import logging

logger = logging.getLogger("BasicStrategy")


class BasicStrategy(TradingStateMachine):
    def __init__(self, client, balance, order_quantity_list, df, position, raw_data):

        super().__init__(client, position, df, balance, order_quantity_list, raw_data)
        self.feature_rsi_basic = FeatureRsiBasic(df=df)

        self.import_feature_configuration(feature=self.feature_rsi_basic)
        self.df = self.feature_rsi_basic.df
        self.df = self.signals_from_features_generate(self.df)
        # logger.info("DF: %s", self.df)

    def import_feature_configuration(self, feature: FeatureRsiBasic):
        self.machine.add_states(feature.states)
        self.signals.extend(self.feature_rsi_basic.signals)
        self.conditions.extend(self.feature_rsi_basic.conditions)

        updated_transitions = []
        for transition in feature.transitions:
            updated_transition = transition.copy()
            updated_transitions.append(updated_transition)

            self.machine.add_transition(**updated_transition)

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

    async def open_basic_dca_long(self, *args, **kwargs):
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

    async def open_basic_dca_short(self, *args, **kwargs):
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
