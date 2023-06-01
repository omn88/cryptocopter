import asyncio
import logging
import signal

import binance

from src.common.identifiers import Position
from src.workers.handle_order import futures_position_close


logger = logging.getLogger("shutdown_strategy_gracefully")


async def shutdown(
    client: binance.AsyncClient,
    posix_signal: signal.Signals,
    position: Position,
    balance: float,
    ui_queue: asyncio.Queue
):
    """Cleanup tasks tied to the service's shutdown."""
    logging.info("Received exit signal %s...", posix_signal.name)

    await futures_position_close(client=client, position=position, balance=balance, ui_queue=ui_queue)

    logging.info("Nacking outstanding messages")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    [task.cancel() for task in tasks]

    logging.info(f"Flushing metrics")
    await client.close_connection()
