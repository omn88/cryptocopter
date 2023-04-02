from src.features.rsi_basic import FeatureRsiBasic
from src.features.rsi_extended import FeatureRsiExtended
from src.workers.trading_state_machine import TradingStateMachine


class BasicStrategy(TradingStateMachine, FeatureRsiBasic, FeatureRsiExtended):
    def __init__(self, client, balance, order_quantity_list, queue):
        super().__init__(client, balance, order_quantity_list, queue)
        self.add_states_and_transitions(
            FeatureRsiBasic.states, FeatureRsiBasic.transitions
        )
        self.add_states_and_transitions(
            FeatureRsiExtended.states, FeatureRsiExtended.transitions
        )
