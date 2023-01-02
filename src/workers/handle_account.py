from typing import Tuple

import pandas
from src import orders
import logging

logger = logging.getLogger("handle_account")


async def account_handle(
    df: pandas.DataFrame, position: orders.Position
) -> Tuple[pandas.DataFrame, orders.Position]:
    logger.info("Entering account handle")
    logger.info("Exiting account handle")
    return df, position
