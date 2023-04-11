from src.features.rsi_basic import FeatureRsiBasic
from src.features.rsi_extended import FeatureRsiExtended
from src.features.rsi_special import FeatureRsiSpecial
from src.workers.trading_state_machine import TradingStateMachine


class SpecialStrategy(TradingStateMachine, FeatureRsiBasic, FeatureRsiExtended):
    def __init__(self, client, balance, order_quantity_list, queue, df, position):
        super().__init__(
            client=client,
            balance=balance,
            order_quantity_list=order_quantity_list,
            queue=queue,
            df=df,
            position=position,
        )
        self.add_states_and_transitions(
            FeatureRsiBasic.states, FeatureRsiBasic.transitions
        )
        self.add_states_and_transitions(
            FeatureRsiExtended.states, FeatureRsiExtended.transitions
        )
        self.add_states_and_transitions(
            FeatureRsiSpecial.states, FeatureRsiSpecial.transitions
        )
