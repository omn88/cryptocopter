import asyncio
import binance
import pandas
from binance import BinanceSocketManager

import logging

from src.common.constants import MARGIN_TYPE
from src.common.identifiers import BinanceClient
from src.producers.producers import (
    kline_futures_socket,
    futures_user_socket,
    futures_symbol_mark_price_socket,
)
from src.workers.trading_state_machine import TradingStateMachine
from src.workers.worker import worker

logger = logging.getLogger("initialize_trading_environment")


async def change_margin_type(client: BinanceClient, symbol: str) -> None:
    try:
        await client.futures_change_margin_type(symbol=symbol, marginType=MARGIN_TYPE)
    except binance.exceptions.BinanceAPIException as e:
        logger.debug("All: %s", e)


def prepare_producers(
    bsm: BinanceSocketManager,
    queue: asyncio.Queue,
    ui_queue: asyncio.Queue,
    main_ui_queue: asyncio.Queue,
    interval: str,
    df: pandas.DataFrame,
    tsm: TradingStateMachine,
    symbol: str,
):
    return [
        asyncio.create_task(
            kline_futures_socket(
                bsm=bsm,
                queue=queue,
                interval=interval,
                last_index=df.index[-1],
                symbol=symbol,
            )
        ),
        asyncio.create_task(futures_user_socket(bm=bsm, queue=queue, tsm=tsm)),
        asyncio.create_task(
            futures_symbol_mark_price_socket(
                bsm=bsm, ui_queue=ui_queue, symbol=symbol, main_ui_queue=main_ui_queue
            )
        ),
    ]


def prepare_workers(tsm: TradingStateMachine, queue: asyncio.Queue, symbol: str):
    return [asyncio.create_task(worker(tsm=tsm, queue=queue, symbol=symbol))]
