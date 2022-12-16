from typing import Tuple

import pandas
from src import orders
import logging

logger = logging.getLogger("worker_account")


async def account_handle(
    df: pandas.DataFrame, position: orders.Position
) -> Tuple[pandas.DataFrame, orders.Position]:

    return df, position
