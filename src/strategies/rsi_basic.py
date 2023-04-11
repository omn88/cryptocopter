from src.features.rsi_basic import FeatureRsiBasic
from src.workers.trading_state_machine import TradingStateMachine


class BasicStrategy(TradingStateMachine, FeatureRsiBasic):
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
