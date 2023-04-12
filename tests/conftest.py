import pandas
import pytest
import binance
import asyncio
import logging
from dataclasses import dataclass

from src.common.orders import Position
from src.features.features import Signal, State
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
    df = dataframe_gen(desired_signal=Signal.NULL)
    df["position"] = State.FLAT
    base = Base(
        df=df,
        client=binance.AsyncClient(),
        position=Position(),
    )
    base.df = await determine_start_position(df=base.df, queue=base.queue)

    yield base

    await base.client.close_connection()
