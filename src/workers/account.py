from typing import Tuple

import pandas
import orders
import logging

logger = logging.getLogger("account_handle")


async def account_handle(
    df: pandas.DataFrame, position: orders.Position
) -> Tuple[pandas.DataFrame, orders.Position]:

    return df, position
