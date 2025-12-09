"""
Messaging infrastructure (server and per-manager proxy).
"""

from core.messaging.message_proxy import MessageProxy, NullMessageProxy
from core.messaging.message_server import MessageServer, run_message_server

__all__ = [
    "MessageProxy",
    "MessageServer",
    "NullMessageProxy",
    "run_message_server",
]
