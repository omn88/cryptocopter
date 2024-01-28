import asyncio
import numpy

import pandas
from logging_config import StrategyLogger
from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import (
    BinanceClient,
    Event,
    EventName,
    PositionMode,
    PositionSide,
    Signal,
    SignalUpdate,
    State,
    StrategyConfig,
)
from src.gui.gui_handler import GuiHandler
from src.strategies.rsi_extended import RsiExtended


class RsiSpecial(RsiExtended):
    def __init__(
        self,
        client: BinanceClient,
        df: pandas.DataFrame,
        balance: float,
        raw_data,
        gui_handler: GuiHandler,
        logger: StrategyLogger,
        config: StrategyConfig,
    ):
        super().__init__(
            client=client,
            df=df,
            balance=balance,
            raw_data=raw_data,
            config=config,
            gui_handler=gui_handler,
            logger=logger,
        )
        self.df = self.add_columns_for_rsi_special(df=self.df)
        self.signals += [Signal.LONG_SPECIAL, Signal.SHORT_SPECIAL]
        self.conditions = (
            self.get_conditions_for_rsi_basic(df=self.df)
            + self.get_conditions_for_rsi_extended(df=self.df)
            + self.get_conditions_for_rsi_special(df=self.df)
        )

        self.states += [State.LONG_SPECIAL, State.LONG_SPECIAL]
        self.df = self.signals_from_features_generate(
            df=self.df, conditions=self.conditions, signals=self.signals
        )
        self.transitions += [
            {
                "trigger": "process_signal",
                "source": State.LONG,
                "dest": State.SHORT_SPECIAL,
                "conditions": "conditions_for_opening_special_short",
                "before": "close_long",
                "after": "open_special_short",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT,
                "dest": State.LONG_SPECIAL,
                "conditions": "conditions_for_opening_special_long",
                "before": "close_short",
                "after": "open_special_long",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_SPECIAL,
                "dest": State.FLAT,
                "conditions": "conditions_for_closing_special_position",
                "before": "close_special_position",
                "after": "enter_flat",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_SPECIAL,
                "dest": State.FLAT,
                "conditions": "conditions_for_closing_special_position",
                "before": "close_special_position",
                "after": "enter_flat",
            },
            {
                "trigger": "process_signal",
                "source": State.LONG_SPECIAL,
                "dest": [State.SHORT, State.SHORT_EXT],
                "conditions": "conditions_for_skipping_when_long_special",
                "before": "skip_signal",
            },
            {
                "trigger": "process_signal",
                "source": State.SHORT_SPECIAL,
                "dest": [State.LONG, State.LONG_EXT],
                "conditions": "conditions_for_skipping_when_short_special",
                "before": "skip_signal",
            },
        ]

    @staticmethod
    def add_columns_for_rsi_special(df):
        df["RsiBelowEighteen"] = numpy.where(df["RSI"] < 18, 1, 0)
        df["RsiAboveEightyTwo"] = numpy.where(df["RSI"] > 82, 1, 0)

        return df

    @staticmethod
    def get_conditions_for_rsi_special(df):
        conditions = [
            (df.RsiAboveEightyTwo.diff() == 1),
            (df.RsiBelowEighteen.diff() == 1),
        ]
        return conditions

    def conditions_for_opening_special_short(self, *args, **kwargs) -> bool:
        return (
            self.state == State.LONG
            and self.signal_update.signal == Signal.SHORT_SPECIAL
        )

    def conditions_for_opening_special_long(self, *args, **kwargs) -> bool:
        return (
            self.state == State.SHORT
            and self.signal_update.signal == Signal.LONG_SPECIAL
        )

    def conditions_for_skipping_when_long_special(self, *args, **kwargs) -> bool:
        return self.state == State.LONG_SPECIAL and self.signal_update.signal in [
            Signal.SHORT,
            Signal.SHORT_EXT,
        ]

    def conditions_for_skipping_when_short_special(self, *args, **kwargs) -> bool:
        return self.state == State.SHORT_SPECIAL and self.signal_update.signal in [
            Signal.LONG,
            Signal.LONG_EXT,
        ]

    def conditions_for_closing_special_position(self, *args, **kwargs) -> bool:
        return (
            self.state in [State.SHORT_SPECIAL, State.LONG_SPECIAL]
            and self.signal_update.signal == Signal.CLOSE_SPECIAL
        )

    async def open_special_long(self, *args, **kwargs):
        self.logger.debug("Opening %s", self.signal_update.signal)

        self.mode = PositionMode.FULL

        await self.position_handler.open_position(
            side=PositionSide.LONG,
            signal_update=self.signal_update,
            mode=self.mode,
            symbol=self.config.symbol,
            number_of_orders=self.position_handler.config.number_of_orders,
            strategy_name=self.config.name,
        )

    async def open_special_short(self, *args, **kwargs):
        self.logger.info("Opening %s", self.signal_update.signal)

        self.mode = PositionMode.FULL

        await self.position_handler.open_position(
            side=PositionSide.SHORT,
            signal_update=self.signal_update,
            mode=self.mode,
            symbol=self.config.symbol,
            number_of_orders=self.position_handler.config.number_of_orders,
            strategy_name=self.config.name,
        )

    async def close_special_position(self, *args, **kwargs):
        self.logger.info("Closing %s", self.position_handler.position.state)
        await self.position_handler.close_position()

    async def handle_kline(self, *args, **kwargs):
        self.logger.info("Entering handle kline")

        expected_index = int(self.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.start_time)

        if (
            self.position_handler.position.state == State.SHORT_SPECIAL
            and self.df["RSI"] > 50 >= self.df["RSI"].shift(1)
        ) or (
            self.position_handler.position.state == State.LONG_SPECIAL
            and self.df["RSI"] < 50 <= self.df["RSI"].shift(1)
        ):
            signal = Signal.CLOSE_SPECIAL

        else:
            self.raw_data.append(list(self.kline_update))

            temp_df = insert_to_pandas(data=self.raw_data)
            temp_df = rsi_indicator_apply(df=temp_df)
            temp_df = self.add_columns_for_rsi_basic(df=temp_df)
            temp_df = self.add_columns_for_rsi_extended(df=temp_df)
            temp_df = self.add_columns_for_rsi_special(df=temp_df)

            self.conditions = self.get_conditions_for_rsi_features(
                df=temp_df
            ) + self.get_conditions_for_rsi_special(df=temp_df)

            temp_df = self.signals_from_features_generate(
                df=temp_df, signals=self.signals, conditions=self.conditions
            )

            self.df = self.df.append(temp_df.tail(1))

            # Copy current position value
            self.df.iloc[-1, -1] = self.df.iloc[-2, -1]

            signal = (
                Signal.NULL
                if self.df.iloc[-1]["Signal"] == 0
                else self.df.iloc[-1]["Signal"]
            )

        self.signal_update = SignalUpdate(
            signal=signal,
            price=round(float(self.df.iloc[-1]["Close"]), 2),
        )
        await self.queue.put(Event(name=EventName.SIGNAL, content=self.signal_update))
        self.logger.info(
            "Added to queue, signal: %s, price: %s",
            self.signal_update.signal,
            self.signal_update.price,
        )
