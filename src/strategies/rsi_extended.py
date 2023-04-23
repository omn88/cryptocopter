import logging

from src.common.identifiers import State, Signal
from src.features.rsi_extended import FeatureRsiExtended
from src.strategies.rsi_basic import BasicStrategy


logger = logging.getLogger("ExtendedStrategy")


class ExtendedStrategy(BasicStrategy):
    def __init__(self, client, balance, order_quantity_list, df, position, raw_data):

        super().__init__(
            client=client,
            position=position,
            df=df,
            balance=balance,
            order_quantity_list=order_quantity_list,
            raw_data=raw_data,
        )
        self.feature_rsi_extended = FeatureRsiExtended(df=df)

        self.import_feature_configuration(feature=self.feature_rsi_extended)
        self.df = self.signals_from_features_generate(self.feature_rsi_extended.df)

    def conditions_for_opening_extended_long(self, *args, **kwargs) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.LONG_20

    def conditions_for_opening_extended_short(self, *args, **kwargs) -> bool:
        return self.state == State.FLAT and self.signal_update.signal == Signal.SHORT_80

    def conditions_for_switch_from_extended_long_to_extended_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.LONG_20 and self.signal_update.signal == Signal.SHORT_80
        )

    def conditions_for_switch_from_extended_short_to_extended_long(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT_80 and self.signal_update.signal == Signal.LONG_20
        )

    def conditions_for_switch_from_extended_long_to_basic_short(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.LONG_20 and self.signal_update.signal == Signal.SHORT

    def conditions_for_switch_from_extended_short_to_basic_long(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.SHORT_80 and self.signal_update.signal == Signal.LONG

    def conditions_for_switch_from_extended_long_to_basic_long(
        self, *args, **kwargs
    ) -> bool:
        return self.state == State.LONG_20 and self.signal_update.signal == Signal.LONG

    def conditions_for_switch_from_extended_short_to_basic_short(
        self, *args, **kwargs
    ) -> bool:
        return (
            self.state == State.SHORT_80 and self.signal_update.signal == Signal.SHORT
        )

    def conditions_for_skipping_extended_signal(self, *args, **kwargs) -> bool:
        return (
            self.state == State.LONG
            and self.signal_update.signal == Signal.LONG_20
            or self.state == State.SHORT
            and self.signal_update.signal == Signal.SHORT_80
        )

    async def change_position_state(self, *args, **kwargs):
        logger.info("Changing status to %s", self.signal_update.signal)
        self.position.status = State(self.signal_update.signal.value)
        self.update_position_in_df(self.position.status)
