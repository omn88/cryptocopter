from typing import List, Optional
from logging_config import StrategyLogger
from src.common.common import generate_position_id
from src.common.identifiers import Position, PositionMode, PositionSide, PositionStatus
from src.order_handler import OrderHandler


class PositionHandler:
    def __init__(self, client, strategy_logger: StrategyLogger):
        self.position: Optional[Position] = None
        self.closed_positions: List[Position] = []
        self.order_handler = OrderHandler(
            client=client, strategy_logger=strategy_logger
        )
        self.strategy_logger = strategy_logger
        self.archived_positions = {}  # Dictionary to hold archived positions

    async def open_position(
        self,
        side: PositionSide,
        entry_price: float,
        number_of_orders: int,
        symbol: str,
        mode: PositionMode,
        strategy_name: str,
    ) -> None:
        self.position = Position(id=generate_position_id(strategy_name=strategy_name))

        self.position.orders = self.order_handler.prepare_orders(
            side=side,
            mode=mode,
            entry_price=entry_price,
            number_of_orders=number_of_orders,
        )

        self.position.orders = self.order_handler.create_orders(
            side=side, orders=self.position.orders, symbol=symbol
        )

    async def update_position(self, position_id, update_info):
        pass
        # Logic to update an existing position based on some update_info
        # ...

    async def confirm_position(self, position_id):
        # Logic to confirm that all actions related to the old position are completed
        position = self.positions.get(position_id)
        if position:
            position.status = PositionStatus.CONFIRMED
            # Perform any additional logic needed after confirmation
            self.strategy_logger.info(f"Position {position_id} confirmed.")

    async def close_long(
        client: BinanceClient,
        position: Position,
        ui_queue: asyncio.Queue,
        main_ui_queue: asyncio.Queue,
        symbol: str,
        strategy_name: str,
    ) -> Position:
        close_side = SIDE_SELL
        position, position_was_opened = await cancel_remaining_limit_orders(
            client, position=position, ui_queue=ui_queue, symbol=symbol
        )

        logger.info("sending close position to ui")
        position_data = PositionData(
            symbol=symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            mark_price=0,
            liquidation_price=position.liquidation_price,
            pnl=0,
            state=position.state,
            status=PositionStatus.CLOSED,
        )

        await ui_queue.put(position_data)

        await main_ui_queue.put(
            StrategyData(strategy_name=strategy_name, position_data=position_data)
        )

        if position_was_opened:
            logger.info("Entering position close, trying to Market %s", close_side)
            position = await send_market_order(
                client=client, position=position, side=close_side, symbol=symbol
            )

            position.take_profit_order.status = await cancel_order(
                client=client,
                order=position.take_profit_order,
                side=position.side,
                ui_queue=ui_queue,
                symbol=symbol,
            )
            logger.info("Cancelled take profit order")

        logger.info("Exiting close long")
        return position

        # SOOOO CONTINUE ON MOVING STUFF FROM HANDLER_ORDER TO POSITION HANDLER~!!!

    async def close_short(
        client: BinanceClient,
        position: Position,
        ui_queue: asyncio.Queue,
        main_ui_queue: asyncio.Queue,
        strategy_name: str,
        symbol: str,
    ) -> Position:
        close_side = client.SIDE_BUY
        position, position_was_opened = await cancel_remaining_limit_orders(
            client, position=position, ui_queue=ui_queue, symbol=symbol
        )

        logger.info("sending close position to ui")
        position_data = PositionData(
            symbol=symbol,
            quantity=position.quantity,
            entry_price=position.entry_price,
            mark_price=0,
            liquidation_price=position.liquidation_price,
            pnl=0,
            status=PositionStatus.CLOSED,
            state=position.state,
        )
        await ui_queue.put(position_data)

        await main_ui_queue.put(
            StrategyData(strategy_name=strategy_name, position_data=position_data)
        )

        if position_was_opened:
            logger.info("Entering position close, trying to Market %s", close_side)
            await send_market_order(
                client=client, position=position, side=close_side, symbol=symbol
            )

            position.take_profit_order.status = await cancel_order(
                client=client,
                order=position.take_profit_order,
                side=position.side,
                ui_queue=ui_queue,
                symbol=symbol,
            )
            logger.info("Cancelled take profit order")

        logger.info("Exiting close short")
        return position

        # SOOOO CONTINUE ON MOVING STUFF FROM HANDLER_ORDER TO POSITION HANDLER~!!! CONTINUE FROM THE ONES ABOVE, CLOSE LONG/SHORT

    async def close_position(self):
        pass
        # await self.order_handler.
        # if position and position.status == PositionStatus.CONFIRMED:
        #     # Proceed with closing the position
        #     position.status = PositionStatus.CLOSING
        #     # ... logic to close the position ...
        #     position.status = PositionStatus.CLOSED
        #     self.strategy_logger.info(f"Position {position_id} closed.")
        # else:
        #     self.strategy_logger.warning(
        #         f"Attempted to close unconfirmed position {position_id}."
        #     )

    def archive_position(self, position_id):
        if position_id in self.positions:
            position = self.positions.pop(position_id)
            self.archived_positions[position_id] = position
            self.strategy_logger.info(f"Position {position_id} archived.")

    # ... other methods ...


# Usage example:
# position_handler = PositionHandler(order_handler, strategy_logger)
# position_id = await position_handler.open_position(side, entry_price, number_of_orders, symbol)
# ... some time later, after the position is closed ...
# position_handler.archive_position(position_id)


# Usage example:
# position_handler = PositionHandler(order_handler, strategy_logger)
# position_id = await position_handler.open_position(side, entry_price, number_of_orders, symbol)
# ... some time later, after receiving confirmations ...
# await position_handler.confirm_position(position_id)
# await position_handler.close_position(position_id)
