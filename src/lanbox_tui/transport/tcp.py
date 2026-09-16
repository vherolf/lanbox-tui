"""TCP transport - the default way to reach a LanBox (default port 777)."""

from __future__ import annotations

import asyncio

from lanbox_tui.transport.base import Transport

DEFAULT_PORT = 777


class TcpTransport(Transport):
    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self._host, self._port)

    async def write(self, data: bytes) -> None:
        assert self._writer is not None, "connect() must be called first"
        self._writer.write(data)
        await self._writer.drain()

    async def read(self, max_bytes: int = 4096) -> bytes:
        assert self._reader is not None, "connect() must be called first"
        return await self._reader.read(max_bytes)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            self._writer = None
            self._reader = None
