import logging

from src.common.identifiers import State, Signal
from src.features.rsi_basic import FeatureRsiBasic
from src.features.rsi_extended import FeatureRsiExtended
from src.strategies.rsi_basic import BasicStrategy
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("ExtendedStrategy")


class ExtendedStrategy(TradingStateMachine, FeatureRsiBasic, FeatureRsiExtended):
    def __init__(
        self, client, queue, balance, order_quantity_list, df, position, raw_data
    ):

        super().__init__(
            client=client,
            queue=queue,
            position=position,
            df=df,
            balance=balance,
            order_quantity_list=order_quantity_list,
            raw_data=raw_data,
        )

        self.import_feature_configuration(feature=FeatureRsiBasic(df=self.df))
        self.import_feature_configuration(feature=FeatureRsiExtended(df=self.df))
        self.df = self.signals_from_features_generate(self.df)
