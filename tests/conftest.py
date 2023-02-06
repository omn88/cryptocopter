import pandas
import pytest
import binance
import asyncio
import logging
from dataclasses import dataclass

from src.orders import Position
from src.features import Signals
from src.producers.producers import determine_start_position
from tests.data.sample_dataframes import dataframe_gen

logger = logging.getLogger("conftest")


@dataclass()
class Base:
    df: pandas.DataFrame
    client: binance.AsyncClient
    position: Position
    queue: asyncio.Queue = asyncio.Queue()
    symbol: str = "BTCUSDT"


@pytest.fixture
async def base():
    df = dataframe_gen(desired_signal=Signals.NULL)
    df["position"] = Signals.FLAT
    base = Base(
        df=df,
        client=binance.AsyncClient(),
        position=Position(balance=1000),
    )
    base.df = await determine_start_position(df=base.df, queue=base.queue)

    yield base

    await base.client.close_connection()
