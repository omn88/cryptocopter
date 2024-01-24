import asyncio
import dataclasses
from pprint import pformat
from typing import Tuple, Optional
import json
from datetime import datetime
import logging
from binance.enums import SIDE_SELL, SIDE_BUY

from src.common.common import signal_to_state
from src.common.constants import LEVERAGE
from src.common.identifiers import (
    OrderUpdate,
    Signal,
    PositionMode,
    Position,
    State,
    Order,
    Artifacts,
    BinanceClient,
)

logger = logging.getLogger("handle_order")


# async def close_special_position(
#     client: BinanceClient, position: Position, ui_queue: asyncio.Queue, symbol: str
# ) -> Position:
#     if position.state in [State.SHORT_SPECIAL, State.LONG_SPECIAL]:
#         close_side = (
#             client.SIDE_BUY
#             if position.state == State.SHORT_SPECIAL
#             else client.SIDE_SELL
#         )
#         logger.info("Closing special position, trying to Market %s", close_side)

#         await send_market_order(
#             client=client, position=position, side=close_side, symbol=symbol
#         )

#         position.orders = []

#     position.state = State.FLAT

#     await cancel_remaining_limit_orders(
#         client, position=position, ui_queue=ui_queue, symbol=symbol
#     )

#     logger.info("Exiting position close")
#     return position


# def save_to_file(artifacts: Artifacts):
#     """
#     Save the Artifacts instance to a file in JSON format. The file name will have the date and time of creation.
#     The file will be saved in the './artifacts/' directory.

#     :param artifacts: the Artifacts instance to be saved
#     """
#     current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#     file_path = f"./artifacts/artifacts_{current_time}.json"

#     with open(file_path, "w") as f:
#         json.dump(dataclasses.asdict(artifacts), f, default=str)
