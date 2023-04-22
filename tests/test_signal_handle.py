from unittest.mock import patch

import pytest
import logging

from src.common.identifiers import Signal, SignalUpdate, State

logger = logging.getLogger("test_signal_handle")
