from src.features.rsi_basic import FeatureRsiBasic
from src.features.rsi_extended import FeatureRsiExtended
from src.workers.trading_state_machine import TradingStateMachine


class ExtendedStrategy(TradingStateMachine, FeatureRsiBasic, FeatureRsiExtended):
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
