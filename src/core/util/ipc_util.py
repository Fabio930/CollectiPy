# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectiPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Inter-process queue helpers."""
from __future__ import annotations

from multiprocessing.connection import wait
from typing import Any, Iterable


def wait_readable(queues: Iterable[Any], timeout: float | None = None) -> list:
    """
    Block until at least one queue has data (or the timeout expires) and return
    the readable ones, so processes can sleep instead of polling in a loop.

    Works with multiprocessing queues (watched through their read end) and with
    pipe-backed queues exposing `fileno()`.
    """
    by_handle = {getattr(q, "_reader", q): q for q in queues}
    return [by_handle[handle] for handle in wait(list(by_handle), timeout)]
