"""The approvals live in core (1.7.7: the task module reads them for the board); this name stays for the gate and the tests."""

from core.approvals import *  # noqa: F401,F403
from core import approvals as _core


def __getattr__(name):  # the private helpers too (the tests read the file through them)
    return getattr(_core, name)
