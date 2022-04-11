import enum
import indicators


class Status(enum.Enum):
    PREPARED: enum.auto()
    NEW: enum.auto()
    LONG: enum.auto()
    SHORT: enum.auto()
    LONG_FULL: enum.auto()
    SHORT_FULL: enum.auto()
    SHORT_FILLED: enum.auto()
    LONG_FILLED: enum.auto()
    CANCELLED: enum.auto()


class Strategy:
    def __init__(self, client, bm):
        self.client = client
        self.bm = bm
        self.status: Status = Status.PREPARED


class RsiSignal(indicators.Signal):
    def get_trigger(self):
        pass

    def decide(self):
        pass


async def rsi_based_futures():

    df = indicators.get_historical_data("BTCUSDT", "15m", "1440")
    df = indicators.apply_technicals(df)

    rsi_signal = RsiSignal(df, lags=14)
