import asyncio
import logging
import signal

from src.common.identifiers.futures import BinanceClient


logger = logging.getLogger("shutdown_strategy_gracefully")


async def shutdown(
    client: BinanceClient,
    posix_signal: signal.Signals,
    position_handler: PositionHandler,
):
    """Cleanup tasks tied to the service's shutdown."""
    logging.info("Received exit signal %s...", posix_signal.name)

    await position_handler.close_position()

    logging.info("Nacking outstanding messages")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    results = [task.cancel() for task in tasks]

    logging.info("Flushing metrics")
    await client.close_connection()
