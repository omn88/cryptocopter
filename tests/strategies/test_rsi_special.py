from src.common.identifiers import State
from src.producers.producers import KlineUpdate
from tests.common import get_orders_long, get_cancel_order, validation_orders
import logging

logger = logging.getLogger("test")


async def test_rsi_basic_handle_kline_long_ext_long_null_short_ext_short_null_long_special(
    special_rsi,
):
    special_rsi.strategy.client.futures_create_order.side_effect = get_orders_long()
    special_rsi.strategy.client.futures_cancel_order.return_value = get_cancel_order()
    special_rsi.strategy.client.futures_get_order.side_effect = validation_orders()

    # NO SIGNAL THEN NULL
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672306200000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="17160.1",
        close_price="16700.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()

    assert len(special_rsi.strategy.position_handler.position.orders) == 0
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.FLAT

    # NO SIGNAL THEN NULL LONG EXT
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672307100000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="18500.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert (
        len(special_rsi.strategy.position_handler.position.orders)
        == special_rsi.strategy.position_handler.config.number_of_orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.LONG_EXT

    # NO SIGNAL THEN NULL LONG EXT LONG
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308000000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="27000.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.position_handler.config.number_of_orders == len(
        special_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG20 LONG NULL
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672308900000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="29700.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.position_handler.config.number_of_orders == len(
        special_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.LONG

    # NO SIGNAL THEN NULL LONG_EXT LONG NULL SHORT_EXT
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672309800000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="26200.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.position_handler.config.number_of_orders == len(
        special_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.SHORT_EXT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672310700000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="22200.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.position_handler.config.number_of_orders == len(
        special_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.SHORT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672311600000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="28200.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()

    assert special_rsi.strategy.position_handler.config.number_of_orders == len(
        special_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.SHORT

    # NO SIGNAL THEN NULL LONG20 LONG NULL SHORT80 SHORT NULL SPECIAL_LONG
    special_rsi.strategy.kline_update = KlineUpdate(
        start_time="1672312500000",
        open_price="19573.19",
        high_price="19605.9",
        low_price="18360.1",
        close_price="56400.72",
        volume="0",
        open_interest="0",
    )

    await special_rsi.strategy.process_kline()
    await special_rsi.strategy.process_signal()

    assert special_rsi.strategy.position_handler.config.number_of_orders == len(
        special_rsi.strategy.position_handler.position.orders
    )
    assert 1000 == special_rsi.strategy.balance
    assert special_rsi.strategy.position_handler.position.state == State.LONG_SPECIAL
