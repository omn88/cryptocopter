import logging
from src.common.common import insert_to_pandas, rsi_indicator_apply
from src.common.identifiers import (
    Signal,
    PositionMode,
    SignalUpdate,
    Event,
    EventName,
    State,
)
from src.features.rsi_basic import FeatureRsiBasic
from src.features.rsi_extended import FeatureRsiExtended
from src.features.rsi_special import FeatureRsiSpecial
from src.workers import handle_order
from src.workers.trading_state_machine import TradingStateMachine

logger = logging.getLogger("SpecialStrategy")


class SpecialStrategy(
    TradingStateMachine, FeatureRsiBasic, FeatureRsiExtended, FeatureRsiSpecial
):
    def __init__(
        self,
        client,
        balance,
        order_quantity_list,
        df,
        position,
        raw_data,
        ui_queue,
        queue,
    ):
        super().__init__(
            client=client,
            queue=queue,
            ui_queue=ui_queue,
            position=position,
            df=df,
            balance=balance,
            order_quantity_list=order_quantity_list,
            raw_data=raw_data,
        )

        self.import_feature_configuration(feature=FeatureRsiBasic())
        self.import_feature_configuration(feature=FeatureRsiExtended())
        self.import_feature_configuration(feature=FeatureRsiSpecial())

        self.df = self.add_columns_for_rsi_basic(df=self.df)
        self.df = self.add_columns_for_rsi_extended(df=self.df)
        self.df = self.add_columns_for_rsi_special(df=self.df)

        self.conditions = self.get_conditions_for_rsi_features(df=self.df)

        self.df = self.signals_from_features_generate(
            self.df, conditions=self.conditions, signals=self.signals
        )

    @staticmethod
    def get_conditions_for_rsi_features(df):
        conditions = [
            (df.RsiBelowThirty.diff() == 0) & (df.RsiBelowThirty.diff(periods=2) == -1),
            (df.RsiAboveSeventy.diff() == 0)
            & (df.RsiAboveSeventy.diff(periods=2) == -1),
            (df.RsiBelowTwenty.diff() == -1),
            (df.RsiAboveEighty.diff() == -1),
            (df.RsiBelowEighteen.diff() == 1),
            (df.RsiAboveEightyTwo.diff() == 1),
        ]
        return conditions

    async def open_special_long(self, *args, **kwargs):
        logger.debug("Opening %s", self.signal_update.signal)

        self.mode = PositionMode.FULL

        self.position = await handle_order.prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            mode=self.mode,
            ui_queue=self.ui_queue,
        )

    async def open_special_short(self, *args, **kwargs):
        logger.info("Opening %s", self.signal_update.signal)

        self.mode = PositionMode.FULL

        self.position = await handle_order.prepare_and_send_orders(
            client=self.client,
            entry_price=self.signal_update.price,
            signal=self.signal_update.signal,
            side=self.position.side,
            balance=self.balance,
            order_quantity_list=self.order_quantity_list,
            mode=self.mode,
            ui_queue=self.ui_queue,
        )

    async def close_special_position(self, *args, **kwargs):
        logger.info("Closing %s", self.position.status)
        self.position_old = await handle_order.close_special_position(
            client=self.client, position=self.position, ui_queue=self.ui_queue
        )

    async def handle_kline(self, *args, **kwargs):
        logger.info("Entering handle kline")

        expected_index = int(self.raw_data[-1][0]) + 900000
        # I need historical data here, then add the kline, generate temp dataframe, then copy last
        assert expected_index == int(self.kline_update.kline[0])

        if (
            self.position.status == State.SHORT_SPECIAL
            and self.df["RSI"] > 50 >= self.df["RSI"].shift(1)
        ) or (
            self.position.status == State.LONG_SPECIAL
            and self.df["RSI"] < 50 <= self.df["RSI"].shift(1)
        ):
            signal = Signal.CLOSE_SPECIAL

        else:
            self.raw_data.append(self.kline_update.kline)

            temp_df = insert_to_pandas(data=self.raw_data)
            temp_df = rsi_indicator_apply(df=temp_df)
            temp_df = self.add_columns_for_rsi_basic(df=temp_df)
            temp_df = self.add_columns_for_rsi_extended(df=temp_df)
            temp_df = self.add_columns_for_rsi_special(df=temp_df)

            self.conditions = self.get_conditions_for_rsi_features(df=temp_df)

            temp_df = self.signals_from_features_generate(
                df=temp_df, signals=self.signals, conditions=self.conditions
            )

            self.df = self.df.append(temp_df.tail(1))

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
            logger.info(
                "Added to queue, signal: %s, price: %s",
                self.signal_update.signal,
                self.signal_update.price,
            )
