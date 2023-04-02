from src.features.features import State


class FeatureRsiBasic:
    states = [State.FLAT, State.LONG, State.SHORT]
    transitions = [
        {
            "trigger": "process_signal",
            "source": "*",
            "dest": "=",
            "conditions": "conditions_for_skipping_signal",
            "after": "skip_signal",
        },
        {
            "trigger": "process_signal",
            "source": State.FLAT,
            "dest": State.LONG,
            "conditions": "conditions_for_opening_long",
            "after": "open_position",
        },
        {
            "trigger": "process_signal",
            "source": State.FLAT,
            "dest": State.SHORT,
            "conditions": "conditions_for_opening_short",
            "after": "open_position",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG,
            "dest": State.SHORT,
            "conditions": "conditions_for_switch_to_short",
            "after": "switch_to_short",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT,
            "dest": State.LONG,
            "conditions": "conditions_for_switch_to_long",
            "after": "switch_to_long",
        },
    ]
