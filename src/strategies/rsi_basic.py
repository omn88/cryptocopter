import numpy
import pandas

from src.features.rsi_basic import FeatureRsiBasic
from src.workers.trading_state_machine import TradingStateMachine


import logging

logger = logging.getLogger("BasicStrategy")


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
            new_states=FeatureRsiBasic.states,
            new_transitions=FeatureRsiBasic.transitions,
        )
        self.signals = FeatureRsiBasic.signals

    def signals_from_features_generate(self, df) -> pandas.DataFrame:
        df = self.add_columns_for_rsi_basic(df)
        self.conditions = [condition(df=df) for condition in FeatureRsiBasic.conditions]

        df["Signal"] = numpy.select(self.conditions, self.signals)

        return df
