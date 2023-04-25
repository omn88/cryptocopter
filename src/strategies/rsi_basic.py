from src.common.identifiers import PositionSide, State, Signal
from src.features.rsi_basic import FeatureRsiBasic
from src.workers import handle_order
from src.workers.handle_order import prepare_and_send_orders, signal_to_state
from src.workers.trading_state_machine import TradingStateMachine


import logging

logger = logging.getLogger("BasicStrategy")


class BasicStrategy(TradingStateMachine, FeatureRsiBasic):
    def __init__(self, client, balance, order_quantity_list, df, position, raw_data):

        super().__init__(
            client=client,
            position=position,
            df=df,
            balance=balance,
            order_quantity_list=order_quantity_list,
            raw_data=raw_data,
        )

        self.import_feature_configuration(feature=FeatureRsiBasic(df=self.df))
        self.df = self.signals_from_features_generate(self.df)

    def import_feature_configuration(self, feature):
        self.machine.add_states(feature.states)
        self.signals.extend(feature.signals)
        self.conditions.extend(feature.conditions)

        updated_transitions = []
        for transition in feature.transitions:
            updated_transition = transition.copy()
            updated_transitions.append(updated_transition)

            self.machine.add_transition(**updated_transition)
