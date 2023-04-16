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
        (
            basic_signals,
            basic_conditions,
        ) = FeatureRsiBasic.rsi_generate_basic_signals_and_conditions(self)
        self.add_signals_and_conditions(
            signal_list=basic_signals, condition_list=basic_conditions
        )
