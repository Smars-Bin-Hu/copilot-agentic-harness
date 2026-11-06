"""The outbox lives in core (1.7.7: the task module reads it for the board); this name stays for the gate and the tests."""

from core.outbox import *  # noqa: F401,F403
from core import outbox as _core


def __getattr__(name):
    return getattr(_core, name)
