import asyncio
import datetime
import logging

from binance.enums import (
    ORDER_STATUS_NEW,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELED,
)
import pytest

from src.common.identifiers.common import PositionSide
from src.common.symbol_info import SymbolInfo
from src.strategies.spot.hp_manager import HpManager
from src.common.identifiers.spot import State
from tests.spot import get_cancel_order, get_new_orders


logger = logging.getLogger("hp_e2e_test")

@pytest.mark.database_integration
async def test_default_buy_scenario(frontend_backend_setup):
    front, back = frontend_backend_setup

    logger.info("Front: %s, back: %s", front, back)
    await asyncio.sleep(1)
    logger.info("DONE")
