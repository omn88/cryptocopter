import queue
from typing import NamedTuple

from src.domain.enums import SubscriptionTarget, SubscriptionType


class SubscriptionInfo(NamedTuple):
    data_type: SubscriptionType
    symbol: str
    target: SubscriptionTarget
    queue: queue.Queue
