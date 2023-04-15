from src.features.rsi_basic import FeatureRsiBasic
from src.workers.trading_state_machine import TradingStateMachine


class BasicStrategy(TradingStateMachine, FeatureRsiBasic):
    def __init__(self, client, balance, order_quantity_list, df, position, raw_data):
        super().__init__(
            client=client,
            balance=balance,
            order_quantity_list=order_quantity_list,
            df=df,
            position=position,
            raw_data=raw_data,
        )
        self.add_states_and_transitions(
            FeatureRsiBasic.states, FeatureRsiBasic.transitions
        )
        self.add_conditions_and_signals(
            condition_lists=self.basic_signal_conditions,
            signal_lists=self.basic_signals_list,
        )
