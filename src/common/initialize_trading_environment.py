import asyncio
import logging
import binance
from binance import BinanceSocketManager


from src.common.identifiers import BinanceClient
from src.gui.gui_handler import GuiHandler
from src.producers.producers import (
    kline_futures_socket,
    futures_user_socket,
    futures_symbol_mark_price_socket,
)

logger = logging.getLogger("initialize_trading_environment")


async def change_margin_type(
    client: BinanceClient, symbol: str, margin_type: str
) -> None:
    try:
        await client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s", e)


def prepare_producers(
    socket_manager: BinanceSocketManager,
    queue: asyncio.Queue,
    gui_handler: GuiHandler,
    interval: str,
    symbol: str,
    stop_event: asyncio.Event,
):
    return [
        asyncio.create_task(
            kline_futures_socket(
                socket_manager=socket_manager,
                queue=queue,
                interval=interval,
                symbol=symbol,
                stop_event=stop_event,
            )
        ),
        asyncio.create_task(
            futures_user_socket(
                socket_manager=socket_manager, queue=queue, stop_event=stop_event
            )
        ),
        asyncio.create_task(
            futures_symbol_mark_price_socket(
                socket_manager=socket_manager,
                ui_queue=gui_handler.ui_queue,
                symbol=symbol,
                main_ui_queue=gui_handler.main_ui_queue,
                stop_event=stop_event,
            )
        ),
    ]
