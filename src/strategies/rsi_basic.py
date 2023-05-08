from src.common.identifiers import PositionSide, State, Signal
from src.features.rsi_basic import FeatureRsiBasic
from src.workers import handle_order
from src.workers.handle_order import prepare_and_send_orders, signal_to_state
from src.workers.trading_state_machine import TradingStateMachine


import logging

logger = logging.getLogger("BasicStrategy")


class BasicStrategy(TradingStateMachine, FeatureRsiBasic):
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
        self.df = self.signals_from_features_generate(self.df)
