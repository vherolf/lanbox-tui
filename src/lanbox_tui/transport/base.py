"""Abstract async transport for talking to a LanBox.

The client and simulator both work purely in terms of this interface, so
the same code paths run whether the peer is a real LanBox over TCP, a real
LanBox over serial (future work), or the in-process simulator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Transport(ABC):
    """A bidirectional byte stream to a LanBox (or something speaking its protocol)."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection. Must be safe to call once."""

    @abstractmethod
    async def write(self, data: bytes) -> None:
        """Send raw bytes to the peer."""

    @abstractmethod
    async def read(self, max_bytes: int = 4096) -> bytes:
        """Read whatever bytes are currently available (may block until some arrive).

        Returns an empty bytes object if the connection has been closed.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close the connection. Safe to call multiple times."""
