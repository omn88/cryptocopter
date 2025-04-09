# from datetime import datetime
# from unittest.mock import MagicMock
# from binance.enums import (
#     ORDER_STATUS_NEW,
#     ORDER_TYPE_LIMIT,
#     ORDER_STATUS_CANCELED,
#     ORDER_STATUS_EXPIRED,
#     ORDER_STATUS_FILLED,
#     ORDER_STATUS_PARTIALLY_FILLED,
# )
# from src.common.identifiers.spot import ExecutionReport, HPConfig, State, StateInfo
# from src.common.identifiers.common import Mode, PositionSide
# from src.common.symbol_info import SymbolInfo
# from src.position_handler.spot import PositionHandler
# from src.strategies.spot.hp_manager import HpManager
# from tests.spot import get_new_orders
# from tests.strategies.spot.hp_manager import get_default_buy_position, move_to_buy_position_active


# async def test_conditions_for_sending_buy_orders(trading_system_factory) -> None:
#     strategy: HpManager = get_default_buy_position(trading_system_factory)
#     strategy = await move_to_buy_position_active(strategy=strategy)
#     strategy.client.create_order.side_effect = get_new_orders(
#         price_low=strategy.buy_position.config.price_low,
#         price_high=strategy.buy_position.config.price_high,
#     )
#     strategy.buy_position.state_info.state = State.NEW
#     strategy.buy_position.state_info.side = PositionSide.LONG
#     strategy.ticker_update = MagicMock(last_price=1300)
#     assert strategy.conditions_for_sending_buy_orders()


# async def test_conditions_for_sending_sell_orders(trading_system_factory) -> None:
#     sell_state_info = StateInfo(side=PositionSide.SHORT)
#     strategy: HpManager = get_default_buy_position(trading_system_factory)
#     strategy = await move_to_buy_position_active(strategy=strategy)
#     sell_config = HPConfig(
#         hp_id=1000,
#         symbol_info=SymbolInfo(symbol="BTCUSDC"),
#         price_high=4200,
#         price_low=4200,
#         mode=Mode.SINGLE,
#         order_trigger=1.0,
#         budget=1000,
#     )
#     strategy.sell_position = PositionHandler(
#         client=strategy.client,
#         strategy_logger=strategy.logger,
#         config=sell_config,
#         ui_queue=strategy.buy_position.ui_queue,
#         db=strategy.db,
#         state_info=sell_state_info,
#     )
#     strategy.sell_position.orders = strategy.sell_position.order_handler.prepare_orders(
#         config=sell_config, state_info=sell_state_info
#     )
#     strategy.client.create_order.side_effect = get_new_orders(
#         price_low=strategy.sell_position.config.price_low,
#         price_high=strategy.sell_position.config.price_high,
#     )
#     strategy.sell_position.state_info.state = State.SELLING
#     strategy.sell_position.state_info.side = PositionSide.SHORT
#     strategy.ticker_update = MagicMock(last_price=4158)
#     assert strategy.conditions_for_sending_sell_orders()


# async def test_conditions_for_cancelling_buy_orders(trading_system_factory) -> None:
#     strategy: HpManager = get_default_buy_position(trading_system_factory)
#     strategy = await move_to_buy_position_active(strategy=strategy)
#     strategy.client.create_order.side_effect = get_new_orders(
#         price_low=strategy.buy_position.config.price_low,
#         price_high=strategy.buy_position.config.price_high,
#     )
#     strategy.buy_position.state_info.state = State.NEW
#     strategy.buy_position.state_info.side = PositionSide.LONG
#     strategy.ticker_update = MagicMock(last_price=1300)
#     assert strategy.conditions_for_sending_buy_orders()

#     strategy.buy_position.state_info.state = State.BUYING
#     strategy.buy_position.state_info.stagnation_counter = 8

#     # Condition met

#     strategy.ticker_update = MagicMock(last_price=1429)
#     assert strategy.conditions_for_cancelling_unfilled_buy_orders() is True

#     # Condition not met
#     strategy.ticker_update = MagicMock(last_price=1428)
#     assert strategy.conditions_for_cancelling_unfilled_buy_orders() is False


# # async def test_conditions_for_cancelling_sell_orders(trading_system_factory) -> None:
# #     sell_state_info = StateInfo(side=PositionSide.SHORT)
# #     strategy: HpManager = get_default_buy_position(trading_system_factory)
# #     strategy = await move_to_buy_position_active(strategy=strategy)
# #     sell_config = HPConfig(
# #         hp_id=1000,
# #         symbol_info=SymbolInfo(symbol="BTCUSDC"),
# #         price_high=4200,
# #         price_low=4200,
# #         mode=Mode.SINGLE,
# #         order_trigger=1.0,
# #         budget=1000,
# #     )
# #     strategy.sell_position = PositionHandler(
# #         client=strategy.client,
# #         strategy_logger=strategy.logger,
# #         config=sell_config,
# #         ui_queue=strategy.buy_position.ui_queue,
# #         db=strategy.db,
# #         state_info=StateInfo(side=PositionSide.SHORT),
# #     )
# #     strategy.sell_position.orders = strategy.sell_position.order_handler.prepare_orders(
# #         config=sell_config, state_info=sell_state_info
# #     )
# #     strategy.client.create_order.side_effect = get_new_orders(
# #         price_low=strategy.sell_position.config.price_low,
# #         price_high=strategy.sell_position.config.price_high,
# #     )
# #     strategy.sell_position.state_info.state = State.SELLING
# #     strategy.sell_position.state_info.side = PositionSide.SHORT
# #     strategy.ticker_update = MagicMock(last_price=4158)
# #     assert strategy.conditions_for_sending_sell_orders()
# #     strategy.sell_position.state_info.stagnation_counter = 8

# #     # Condition met
# #     strategy.ticker_update = MagicMock(
# #         last_price=4115
# #     )  # price_low * (1 - order_trigger / 100) - 1

# #     assert strategy.conditions_for_cancelling_unfilled_sell_orders() is True

# #     # Condition not met
# #     strategy.ticker_update = MagicMock(
# #         last_price=4116
# #     )  # price_low * (1 - order_trigger / 100)
# #     assert strategy.conditions_for_cancelling_unfilled_sell_orders() is False


# async def test_handle_ticker(trading_system_factory) -> None:
#     strategy: HpManager = get_default_buy_position(trading_system_factory)
#     strategy = await move_to_buy_position_active(strategy=strategy)

#     strategy.client.create_order.side_effect = get_new_orders(
#         price_low=strategy.buy_position.config.price_low,
#         price_high=strategy.buy_position.config.price_high,
#     )
#     strategy.buy_position.state_info.state = State.NEW
#     strategy.buy_position.state_info.side = PositionSide.LONG
#     strategy.ticker_update = MagicMock(last_price=1300)
#     assert strategy.conditions_for_sending_buy_orders()
#     strategy.buy_position.state_info.next_monitor_time = datetime.now().strftime(
#         "%Y-%m-%d %H:%M:%S"
#     )
#     assert strategy.buy_position.orders
#     await strategy.increase_stagnation_counter_buy()
#     assert strategy.buy_position.state_info.stagnation_counter == 1
