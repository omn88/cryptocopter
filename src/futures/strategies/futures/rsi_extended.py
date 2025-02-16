import numpy

from logging_config import StrategyLogger

from src.identifiers.common import BinanceClient
from src.identifiers.futures import (
    State,
    StrategyConfig,
    Event,
    EventName,
    Signal,
    SignalUpdate,
)
from src.futures.df_handler.futures import DfHandler
from src.gui.gui_handler.futures import GuiHandler
from src.futures.strategies.futures.rsi_basic import RsiBasic


class RsiExtended(RsiBasic):
    def __init__(
        self,
        client: BinanceClient,
        balance: float,
        gui_handler: GuiHandler,
        logger: StrategyLogger,
        config: StrategyConfig,
        df_handler: DfHandler,
    ):
        super().__init__(
            client=client,
            balance=balance,
            gui_handler=gui_handler,
            logger=logger,
            config=config,
            df_handler=df_handler,
        )
        self.df_handler.df = self.add_columns_for_rsi_extended(df=self.df_handler.df)
        self.df_handler.signals.extend([Signal.LONG_EXT, Signal.SHORT_EXT])
        self.df_handler.conditions += self.get_conditions_for_rsi_extended(
            df=self.df_handler.df
        )

        self.states += [State.LONG_EXT, State.SHORT_EXT]
        self.df = self.df_handler.signals_from_features_generate(
            df=self.df_handler.df,
            conditions=self.df_handler.conditions,
            signals=self.df_handler.signals,
        )
        self.transitions += [
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.LONG_EXT,
                "conditions": "conditions_for_opening_extended_long",
                "after": "open_long",
            },
            {
                "trigger": "process_signal",
                "source": State.FLAT,
                "dest": State.SHORT_EXT,
                "conditions": "conditions_for_opening_extended_short",
                "after": "open_short",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_EXT,
                "dest": State.SHORT_EXT,
                "conditions": "conditions_for_switch_from_extended_long_to_extended_short",
                "before": "close_long",
                "after": "open_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_EXT,
                "dest": State.LONG_EXT,
                "conditions": "conditions_for_switch_from_extended_short_to_extended_long",
                "before": "close_short",
                "after": "open_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_EXT,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_from_extended_long_to_basic_short",
                "before": "close_long",
                "after": "open_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.LONG_EXT,
                "conditions": "conditions_for_switch_from_basic_short_to_extended_long",
                "before": "close_short",
                "after": "open_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT_EXT,
                "conditions": "conditions_for_switch_from_basic_long_to_extended_short",
                "before": "close_long",
                "after": "open_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_EXT,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_from_extended_short_to_basic_long",
                "before": "close_short",
                "after": "open_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_EXT,
                "dest": State.LONG,
                "conditions": "conditions_for_switch_from_extended_long_to_basic_long",
                "before": "change_position_state",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_EXT,
                "dest": State.SHORT,
                "conditions": "conditions_for_switch_from_extended_short_to_basic_short",
                "before": "change_position_state",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.LONG_EXT,
                "conditions": "conditions_for_skipping_extended_signal",
                "before": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.SHORT_EXT,
                "conditions": "conditions_for_skipping_extended_signal",
                "before": "skip_signal",
            },
        ]

    @staticmethod
    def add_columns_for_rsi_extended(df):
        df["RsiBelowTwenty"] = numpy.where(df["RSI"] < 20, 1, 0)
        df["RsiAboveEighty"] = numpy.where(df["RSI"] > 80, 1, 0)
        return df

    @staticmethod
    def get_conditions_for_rsi_extended(df):
        return [
            (df.RsiBelowTwenty.diff() == -1),
            (df.RsiAboveEighty.diff() == -1),
        ]

    @staticmethod
    def get_conditions_for_rsi_features(df):
        return [
            (df.RsiBelowThirty.diff() == 0) & (df.RsiBelowThirty.diff(periods=2) == -1),
            (df.RsiAboveSeventy.diff() == 0)
            & (df.RsiAboveSeventy.diff(periods=2) == -1),
            (df.RsiBelowTwenty.diff() == -1),
            (df.RsiAboveEighty.diff() == -1),
        ]

    async def handle_kline(self, *args, **kwargs):
        self.logger.info("Entering handle kline")

        expected_index = int(self.df_handler.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.start_time)

        self.df_handler.raw_data.append(list(self.kline_update))

        temp_df = self.df_handler.insert_to_pandas()
        temp_df = self.df_handler.rsi_indicator_apply(df=temp_df)
        temp_df = self.add_columns_for_rsi_basic(df=temp_df)
        temp_df = self.add_columns_for_rsi_extended(df=temp_df)

        self.df_handler.conditions = self.get_conditions_for_rsi_features(df=temp_df)

        temp_df = self.df_handler.signals_from_features_generate(
            df=temp_df,
            signals=self.df_handler.signals,
            conditions=self.df_handler.conditions,
        )

        self.df = self.df.append(temp_df.tail(1))

        # Copy current position value
        self.df.iloc[-1, -1] = self.df.iloc[-2, -1]

        signal = self.df.iloc[-1]["Signal"]

        if signal == 0:
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
            self.logger.info(
                "Added to queue, signal: %s, price: %s",
                self.signal_update.signal,
                self.signal_update.price,
            )

    def conditions_for_opening_extended_long(self, *args, **kwargs) -> bool:
        return (
            self.state == State.FLAT.value
            and self.signal_update.signal == Signal.LONG_EXT
        )

    def conditions_for_opening_extended_short(self, *args, **kwargs) -> bool:
        return (
            self.state == State.FLAT.value
            and self.signal_update.signal == Signal.SHORT_EXT
        )

    def conditions_for_switch_from_extended_long_to_extended_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.LONG_EXT
            and self.signal_update.signal == Signal.SHORT_EXT
        )

    def conditions_for_switch_from_extended_short_to_extended_long(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT_EXT
            and self.signal_update.signal == Signal.LONG_EXT
        )

    def conditions_for_switch_from_extended_long_to_basic_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.LONG_EXT and self.signal_update.signal == Signal.SHORT
        )

    def conditions_for_switch_from_basic_long_to_extended_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.LONG and self.signal_update.signal == Signal.SHORT_EXT
        )

    def conditions_for_switch_from_basic_short_to_extended_long(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT and self.signal_update.signal == Signal.LONG_EXT
        )

    def conditions_for_switch_from_extended_short_to_basic_long(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT_EXT and self.signal_update.signal == Signal.LONG
        )

    def conditions_for_switch_from_extended_long_to_basic_long(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.LONG_EXT and self.signal_update.signal == Signal.LONG

    def conditions_for_switch_from_extended_short_to_basic_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT_EXT and self.signal_update.signal == Signal.SHORT
        )

    def conditions_for_skipping_extended_signal(self, *args, **kwargs) -> bool:
        return (
            self.state == State.LONG
            and self.signal_update.signal == Signal.LONG_EXT
            or self.state == State.SHORT
            and self.signal_update.signal == Signal.SHORT_EXT
        )

    async def change_position_state(self, *args, **kwargs):
        self.logger.info("Changing status to %s", self.signal_update.signal)
        self.position_handler.position.state = State(self.signal_update.signal.value)
        self.df_handler.update_position_in_df(self.position_handler.position.state)
