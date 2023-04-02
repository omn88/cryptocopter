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
