from enum import Enum


class State(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    STAGNATED = "STAGNATED"
    CLOSED = "CLOSED"
