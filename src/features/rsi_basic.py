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
            "after": "open_long",
        },
        {
            "trigger": "process_signal",
            "source": State.FLAT,
            "dest": State.SHORT,
            "conditions": "conditions_for_opening_short",
            "after": "open_short",
        },
        {
            "trigger": "process_signal",
            "source": State.LONG,
            "dest": State.SHORT,
            "conditions": "conditions_for_switch_to_short",
            "before": "close_long",
            "after": "open_short",
        },
        {
            "trigger": "process_signal",
            "source": State.SHORT,
            "dest": State.LONG,
            "conditions": "conditions_for_switch_to_long",
            "before": "close_short",
            "after": "open_long",
        },
        {
            "trigger": "process_signal",
            "source": [State.SHORT, State.LONG],
            "dest": State.FLAT,
            "conditions": "conditions_for_liquidation",
            "before": "handle_liquidation",
            "after": "enter_flat",
        },
        {
            "trigger": "process_signal",
            "source": [State.SHORT, State.LONG],
            "dest": State.FLAT,
            "conditions": "conditions_for_target_reached",
            "before": "handle_target_reached",
            "after": "enter_flat",
        },
    ]
