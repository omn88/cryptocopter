import pandas

from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import (
    PositionSide,
    State,
    Signal,
    SignalUpdate,
    Event,
    EventName,
)
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

        self.import_feature_configuration(feature=FeatureRsiBasic())
        self.df = self.add_columns_for_rsi_basic(df=self.df)
        self.conditions = self.get_conditions_for_rsi_basic(self.df)
        self.df = self.signals_from_features_generate(
            df=self.df, conditions=self.conditions, signals=self.signals
        )

    @staticmethod
    def get_conditions_for_rsi_basic(df):
        conditions = [
            (df.RsiBelowThirty.diff() == 0) & (df.RsiBelowThirty.diff(periods=2) == -1),
            (df.RsiAboveSeventy.diff() == 0)
            & (df.RsiAboveSeventy.diff(periods=2) == -1),
        ]
        return conditions

    async def handle_kline(self, *args, **kwargs):
        logger.info("Entering handle kline")

        expected_index = int(self.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.kline[0])

        self.raw_data.append(self.kline_update.kline)

        temp_df = insert_to_pandas(data=self.raw_data)
        temp_df = rsi_indicator_apply(df=temp_df)
        temp_df = self.add_columns_for_rsi_basic(df=temp_df)
        conditions = self.get_conditions_for_rsi_basic(df=temp_df)

        temp_df = self.signals_from_features_generate(
            df=temp_df, conditions=conditions, signals=self.signals
        )
        self.df = self.df.append(temp_df.tail(1))

        signal = (
            Signal.NULL
            if self.df.iloc[-1]["Signal"] == 0
            else self.df.iloc[-1]["Signal"]
        )

        signal_update = SignalUpdate(
            signal=signal,
            price=round(float(self.df.iloc[-1]["Close"]), 2),
        )

        await self.queue.put(Event(name=EventName.SIGNAL, content=signal_update))

        logger.info(
            "Added to queue, signal: %s, price: %s",
            signal_update.signal,
            signal_update.price,
        )
