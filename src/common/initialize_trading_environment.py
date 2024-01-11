import asyncio
import binance
import pandas
from binance import BinanceSocketManager

import logging

from src.common.constants import MARGIN_TYPE
from src.common.identifiers import BinanceClient, Event, EventName, Signal, SignalUpdate
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
        asyncio.create_task(futures_user_socket(bm=bsm, queue=queue)),
        asyncio.create_task(
            futures_symbol_mark_price_socket(
                bsm=bsm, ui_queue=ui_queue, symbol=symbol, main_ui_queue=main_ui_queue
            )
        ),
    ]


def prepare_workers(tsm: TradingStateMachine, queue: asyncio.Queue, symbol: str):
    return [asyncio.create_task(worker(tsm=tsm, queue=queue, symbol=symbol))]


async def determine_start_position(df, queue):
    logger.info("Start determining strategy start position.")
    signal = Signal.NULL
    price = 0
    signal_index = 0

    for index, row in df[::-1].iterrows():
        if row["Signal"] not in [
            0,
            Signal.LONG_SPECIAL,
            Signal.SHORT_SPECIAL,
            Signal.CLOSE_SPECIAL,
        ]:
            signal = row["Signal"]
            price = row["Close"]
            # Adding extra lines to see what happened before signal
            signal_index += 4
            break

        price = row["Close"]
        signal_index += 1

    try:
        assert signal_index <= len(df.index)
        df = df.iloc[len(df.index) - signal_index : :]
        logger.debug("New DF shortened to last signal + 3 rows: \n%s", df.to_string())
    except AssertionError:
        logger.exception(
            "Last signal almost on top of df, leaving df as is: \n%s",
            df.to_string(),
        )

    signal_update = SignalUpdate(signal=signal, price=round(float(price), 2))
    await queue.put(Event(name=EventName.SIGNAL, content=signal_update))
