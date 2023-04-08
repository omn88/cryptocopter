from src.features.features import State


class FeatureRsiSpecial:

    states = [State.FLAT, State.LONG, State.SHORT]
    transitions = [
        {
            "trigger": "go_flat",
            "source": [State.LONG, State.SHORT],
            "dest": State.FLAT,
        },
        {
            "trigger": "exit_flat",
            "source": State.FLAT,
            "dest": "*",
        },
    ]

    def conditions_for_skipping_signal(self) -> bool:
        long_signals = [Signal.LONG, Signal.LONG_20]
        short_signals = [Signal.SHORT, Signal.SHORT_80]

        return (
            (self.state == State.LONG and self.signal_update.signal in long_signals)
            or (
                self.state == State.LONG_20
                and self.signal_update.signal == Signal.LONG_20
            )
            or (
                self.state == State.SHORT and self.signal_update.signal in short_signals
            )
            or (
                self.state == State.SHORT_80
                and self.signal_update.signal == Signal.SHORT_80
            )
            or (
                self.state in [State.SHORT_SPECIAL, State.LONG_SPECIAL]
                and self.signal_update.signal in [long_signals, short_signals]
            )
        )
