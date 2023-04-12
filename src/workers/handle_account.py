from typing import Tuple

import pandas
from src.common import orders
import logging

from src.common.identifiers import AccountUpdate

logger = logging.getLogger("handle_account")


async def account_handle(
    df: pandas.DataFrame, position: orders.Position, account_update: AccountUpdate
) -> Tuple[pandas.DataFrame, orders.Position]:
    logger.info("Entering account handle")
    logger.info("Account update: %s", account_update)
    logger.info("Exiting account handle")
    return df, position
