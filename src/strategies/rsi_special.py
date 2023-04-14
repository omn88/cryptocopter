from src.features.rsi_basic import FeatureRsiBasic
from src.features.rsi_extended import FeatureRsiExtended
from src.features.rsi_special import FeatureRsiSpecial
from src.workers.trading_state_machine import TradingStateMachine


class SpecialStrategy(
    TradingStateMachine, FeatureRsiBasic, FeatureRsiExtended, FeatureRsiSpecial
):
    def __init__(
        self, client, balance, order_quantity_list, queue, df, position, raw_data
    ):
        super().__init__(
            client=client,
            balance=balance,
            order_quantity_list=order_quantity_list,
            queue=queue,
            df=df,
            position=position,
            raw_data=raw_data,
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
        self.add_conditions_and_signals(
            condition_lists=self.basic_signal_conditions,
            signal_lists=self.basic_signals_list,
        )
        self.add_conditions_and_signals(
            condition_lists=self.extended_signal_conditions,
            signal_lists=self.extended_signals_list,
        )
        self.add_conditions_and_signals(
            condition_lists=self.special_signal_conditions,
            signal_lists=self.special_signals_list,
        )
