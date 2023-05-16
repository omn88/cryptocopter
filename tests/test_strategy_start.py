import pytest

from src.common.common import (
    insert_to_pandas,
    rsi_indicator_apply,
)
from src.common.identifiers import Signal, SignalUpdate, Position, Event
from src.common.initialize_trading_environment import (
    create_async_queue,
)
from src.common.orders import order_quantity_list_prepare
from src.strategies.rsi_extended import ExtendedStrategy
from tests.data.sample_dataframes import raw_data_generate


@pytest.mark.parametrize(
    "signal",
    [Signal.LONG, Signal.LONG_EXT, Signal.SHORT, Signal.SHORT_EXT],
)
async def test_determine_start_position(signal, basic_rsi):
    raw_data = raw_data_generate(desired_signal=signal)
    df = insert_to_pandas(data=raw_data)
    df = rsi_indicator_apply(df=df)
    position = Position()
    queue = await create_async_queue()

    tsm = ExtendedStrategy(
        client=basic_rsi.client,
        balance=1000,
        order_quantity_list=order_quantity_list_prepare(),
        df=df,
        position=position,
        raw_data=raw_data,
        queue=queue,
    )
    tsm.signals_from_features_generate(
        df=df, conditions=tsm.conditions, signals=tsm.signals
    )
    tsm.signal_update = SignalUpdate(signal=signal, price=0)

    await tsm.determine_start_position()

    assert tsm.queue.qsize() == 1
    event = await tsm.queue.get()
    assert isinstance(event, Event)
    assert event.content.signal == signal
    assert tsm.queue.qsize() == 0

    await tsm.client.close_connection()
