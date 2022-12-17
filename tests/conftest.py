import pandas
import pytest
import binance
import asyncio
import logging
from dataclasses import dataclass

from src.features import Signals
from src.producers.producers import determine_start_position, Event
from tests.data.sample_dataframes import dataframe_gen

logger = logging.getLogger("conftest")


@dataclass()
class Base:
    df: pandas.DataFrame
    client: binance.AsyncClient
    queue: asyncio.Queue = asyncio.Queue()
    symbol: str = "BTCUSDT"


@pytest.fixture
async def base():
    desired_signal = Signals.NULL
    df = dataframe_gen(desired_signal=desired_signal)
    df["position"] = Signals.FLAT
    base = Base(client=binance.AsyncClient(), df=df)
    base.df = await determine_start_position(df=base.df, queue=base.queue)
    event = await base.queue.get()
    assert isinstance(event, Event)
    assert event.content["last_signal"] == desired_signal

    yield base

    await base.client.close_connection()
