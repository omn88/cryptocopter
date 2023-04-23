import pandas

from src.common.identifiers import Signal, SignalUpdate, Position, State


def generate_signal(signal: Signal, df: pandas.DataFrame) -> SignalUpdate:
    entry_price = round(float(df.at[df.index[-1], "Close"]), 1)
    return SignalUpdate(signal=signal, price=entry_price)


def assert_dca_long_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert state == position.status
    assert all(order.price <= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)


def assert_dca_short_opened(
    position: Position,
    balance: float,
    state: State,
    signal_update: SignalUpdate,
    df: pandas.DataFrame,
):
    assert 4 == len(position.orders)
    assert 1000 == balance
    assert state == State(signal_update.signal.value)
    assert (
        state == position.status
    ), f"State: {state}, position.status: {position.status}"
    assert all(order.price >= signal_update.price for order in position.orders)
    assert df.at[df.index[-1], "Position"] == State(signal_update.signal.value)
