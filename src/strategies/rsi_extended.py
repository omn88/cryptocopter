import numpy

from src.features.rsi_basic import FeatureRsiBasic
from src.features.rsi_extended import FeatureRsiExtended
from src.workers.trading_state_machine import TradingStateMachine


class ExtendedStrategy(TradingStateMachine, FeatureRsiBasic, FeatureRsiExtended):
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
        self.add_states_and_transitions(
            FeatureRsiExtended.states, FeatureRsiExtended.transitions
        )
        self.signals = FeatureRsiBasic.signals + FeatureRsiExtended.signals

    def signals_from_features_generate(self, df):
        df = self.add_columns_for_rsi_basic(df)
        df = self.add_columns_for_rsi_extended(df)
        self.conditions = [
            condition(df=df)
            for condition in (
                FeatureRsiBasic.conditions + FeatureRsiExtended.conditions
            )
        ]

        df["Signal"] = numpy.select(self.conditions, self.signals)

        return df
