from unittest.mock import patch

from src.common.identifiers import State
from src.producers.producers import KlineUpdate
from tests.common import get_orders_long, get_cancel_order, validation_orders
import logging

logger = logging.getLogger("test")


@patch("src.workers.handle_order.save_to_file")
async def test_rsi_basic_handle_kline_long_ext_long_null_short_ext_short_null_long_special(
    mock_save_to_file,
    special_rsi,
):
    special_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    special_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    special_rsi.strategy.client.futures_get_order.side_effect = validation_orders()
    mock_save_to_file.return_value = True

    # NO SIGNAL THEN NULL
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=["1672306200000", "19573.19", "19605.9", "17160.1", "16700.72", "0", "0"]
    )

    await special_rsi.strategy.process_kline()

    assert len(special_rsi.strategy.position.orders) == 0
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.FLAT

    # LONG EXT
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672307100000, 19573.19, 19605.9, 18360.1, 18500.72, 0, 0]
        ]
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert (
        len(special_rsi.strategy.position.orders)
        == special_rsi.strategy.number_of_orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.LONG_EXT

    # LONG
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308000000, 19573.19, 19605.9, 18360.1, 27000.72, 0, 0]
        ]
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.number_of_orders == len(
        special_rsi.strategy.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.LONG

    # NO SIGNAL THEN NULL LONGEXT LONG NULL
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672308900000, 19573.19, 19605.9, 18360.1, 29700.72, 0, 0]
        ]
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.number_of_orders == len(
        special_rsi.strategy.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG_EXT LONG NULL SHORT_EXT
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672309800000, 19573.19, 19605.9, 18360.1, 26200.72, 0, 0]
        ]
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.number_of_orders == len(
        special_rsi.strategy.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.SHORT_EXT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672310700000, 19573.19, 19605.9, 18360.1, 22200.72, 0, 0]
        ]
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.number_of_orders == len(
        special_rsi.strategy.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.SHORT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672311600000, 19573.19, 19605.9, 18360.1, 28200.72, 0, 0]
        ]
    )

    await special_rsi.strategy.process_kline()

    assert special_rsi.strategy.number_of_orders == len(
        special_rsi.strategy.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.SHORT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG
    special_rsi.strategy.kline_update = KlineUpdate(
        kline=[
            str(x) for x in [1672312500000, 19573.19, 19605.9, 18360.1, 56400.72, 0, 0]
        ]
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.number_of_orders == len(
        special_rsi.strategy.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position.state == State.LONG_SPECIAL
