from src import features


def conditions_for_opening_long(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.FLAT and signal in [
        features.Signals.LONG,
        features.Signals.LONG_20,
    ]


def conditions_for_opening_short(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.FLAT and signal in [
        features.Signals.SHORT,
        features.Signals.SHORT_80,
    ]


def conditions_for_skipping_signal(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        (
            status == features.Signals.LONG
            and signal in [features.Signals.LONG, features.Signals.LONG_20]
        )
        or (status == features.Signals.LONG_20 and signal == features.Signals.LONG_20)
        or (
            status == features.Signals.SHORT
            and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
        )
        or (status == features.Signals.SHORT_80 and signal == features.Signals.SHORT_80)
        or (
            status == features.Signals.SHORT_SPECIAL
            and signal
            in [
                features.Signals.LONG,
                features.Signals.LONG_20,
                features.Signals.SHORT,
                features.Signals.SHORT_80,
            ]
        )
        or (
            status == features.Signals.LONG_SPECIAL
            and signal
            in [
                features.Signals.LONG,
                features.Signals.LONG_20,
                features.Signals.SHORT,
                features.Signals.SHORT_80,
            ]
        )
    )


def conditions_for_changing_status(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (status == features.Signals.LONG_20 and signal == features.Signals.LONG) or (
        status == features.Signals.SHORT_80 and signal == features.Signals.SHORT
    )


def conditions_for_switch_from_long_to_short(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        status == features.Signals.LONG
        and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
    ) or (
        status == features.Signals.LONG_20
        and signal in [features.Signals.SHORT, features.Signals.SHORT_80]
    )


def conditions_for_switch_from_short_to_long(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        status == features.Signals.SHORT
        and signal
        in [
            features.Signals.LONG,
            features.Signals.LONG_20,
        ]
    ) or (
        status == features.Signals.SHORT_80
        and signal in [features.Signals.LONG, features.Signals.LONG_20]
    )


def conditions_for_special_long_close_short(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.SHORT and signal == features.Signals.LONG_SPECIAL


def conditions_for_special_short_close_long(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.LONG and signal == features.Signals.SHORT_SPECIAL


def conditions_for_special_long(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.FLAT and signal == features.Signals.LONG_SPECIAL


def conditions_for_special_short(
    status: features.Signals, signal: features.Signals
) -> bool:
    return status == features.Signals.FLAT and signal == features.Signals.SHORT_SPECIAL


def condition_to_close_special_position(
    status: features.Signals, signal: features.Signals
) -> bool:
    return (
        status
        in [
            features.Signals.SHORT_SPECIAL,
            features.Signals.LONG_SPECIAL,
        ]
        and signal == features.Signals.CLOSE_SPECIAL
    )
