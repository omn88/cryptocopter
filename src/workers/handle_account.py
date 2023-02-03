from typing import Tuple

import pandas
from src import orders
import logging

logger = logging.getLogger("handle_account")


async def account_handle(
    df: pandas.DataFrame, position: orders.RsiBasedFutures
) -> Tuple[pandas.DataFrame, orders.RsiBasedFutures]:
    logger.info("Entering account handle")
    logger.info("Exiting account handle")
    return df, position
