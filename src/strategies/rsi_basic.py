from typing import List
import logging
import numpy
import pandas
from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import (
    Signal,
    SignalUpdate,
    Event,
    EventName,
    BinanceClient,
    State,
)
from src.strategies.base import BaseStrategy


logger = logging.getLogger("RsiBasic")


class RsiBasic(BaseStrategy):
    def __init__(
        self,
        client: BinanceClient,
        df: pandas.DataFrame,
        balance: float,
        order_quantity_list: List,
        raw_data,
        symbol: str,
        strategy_name: str,
    ):
        super().__init__(
            client=client,
            df=df,
            balance=balance,
            order_quantity_list=order_quantity_list,
            raw_data=raw_data,
            symbol=symbol,
            strategy_name=strategy_name,
        )
        self.df = self.add_columns_for_rsi_basic(df=self.df)
        self.signals += [Signal.LONG, Signal.SHORT]
        self.conditions += self.get_conditions_for_rsi_basic(df=self.df)

        self.states += [State.LONG, State.SHORT]
        self.df = self.signals_from_features_generate(
            df=self.df, conditions=self.conditions, signals=self.signals
        )
        self.transitions += [
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.LONG,
                "conditions": "conditions_for_opening_basic_long",
                "after": "open_dca_long",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.SHORT,
                "conditions": "conditions_for_opening_basic_short",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_to_short",
                "before": "close_long",
                "after": "open_dca_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_to_long",
                "before": "close_short",
                "after": "open_dca_long",
            },
        ]

    @staticmethod
    def add_columns_for_rsi_basic(df):
        df["RsiBelowThirty"] = numpy.where(df["RSI"] < 30, 1, 0)
        df["RsiAboveSeventy"] = numpy.where(df["RSI"] > 70, 1, 0)
        return df

    @staticmethod
    def get_conditions_for_rsi_basic(df):
        return [
            (df.RsiBelowThirty.diff() == 0) & (df.RsiBelowThirty.diff(periods=2) == -1),
            (df.RsiAboveSeventy.diff() == 0)
            & (df.RsiAboveSeventy.diff(periods=2) == -1),
        ]

    def conditions_for_opening_basic_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT and self.signal_update.signal == Signal.LONG
        )
        logger.info(
            "Open basic long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )

        return condition

    def conditions_for_opening_basic_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.FLAT.value and self.signal_update.signal == Signal.SHORT
        )
        logger.info(
            "Open basic short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        logger.info(
            "Self state = State FLAT: %s, signal = short: %s, type self state: %s",
            self.state == State.FLAT,
            self.signal_update.signal == Signal.SHORT,
            type(self.state),
        )

        return condition

    def conditions_for_switch_to_short(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.LONG and self.signal_update.signal == Signal.SHORT
        )
        logger.info(
            "Switch to short: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    def conditions_for_switch_to_long(self, *args, **kwargs) -> bool:
        condition = (
            self.state == State.SHORT and self.signal_update.signal == Signal.LONG
        )
        logger.info(
            "Switch to long: %s, state: %s signal: %s",
            condition,
            self.state,
            self.signal_update.signal,
        )
        return condition

    async def handle_kline(self, *args, **kwargs):
        logger.info("Entering handle kline")

        expected_index = int(self.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.kline[0])

        self.raw_data.append(self.kline_update.kline)

        temp_df = insert_to_pandas(data=self.raw_data)
        temp_df = rsi_indicator_apply(df=temp_df)
        temp_df = self.add_columns_for_rsi_basic(df=temp_df)
        self.conditions = self.get_conditions_for_rsi_basic(df=temp_df)

        temp_df = self.signals_from_features_generate(
            df=self.df, conditions=self.conditions, signals=self.signals
        )
        self.df = self.df.append(temp_df.tail(1))

        # Copy current position value
        self.df.iloc[-1, -1] = self.df.iloc[-2, -1]

        if self.signal_update.signal == 0:
            self.signal_update = SignalUpdate(
                signal=Signal.NULL,
                price=round(float(self.df.iloc[-1]["Close"]), 2),
            )
            self.skip_signal()
        else:
            self.signal_update = SignalUpdate(
                signal=self.df.iloc[-1]["Signal"],
                price=round(float(self.df.iloc[-1]["Close"]), 2),
            )
            await self.queue.put(
                Event(name=EventName.SIGNAL, content=self.signal_update)
            )
            logger.info(
                "Added to queue, signal: %s, price: %s",
                self.signal_update.signal,
                self.signal_update.price,
            )
