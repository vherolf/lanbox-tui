"""Serial/USB transport - the LanBox enumerates as a USB-serial modem.

pyserial is a blocking library, so every call is pushed through
`asyncio.to_thread` to avoid blocking the event loop.

The LanBox installs as a "USB modem" (LCedit manual p.5), i.e. a USB CDC-ACM
device, for which the serial baud rate is nominal and ignored. It is NOT
related to `CommonSetBaudRate`, which configures the MIDI port (5-pin DIN).
Unverified against real hardware: whether a real LanBox skips the password
handshake over USB (see `requires_auth` below and `transport/base.py`).
"""

from __future__ import annotations

import asyncio

import serial

from lanbox_tui.transport.base import Transport

DEFAULT_BAUDRATE = 115200  # nominal: USB CDC-ACM ignores it (see module docstring)


class SerialTransport(Transport):
    # The reference chart's password-prompt description lives under
    # "Network Connection", not "Serial Connection" - assumed to mean serial
    # skips the handshake. Sending it anyway would be harmless (framing
    # rules discard any bytes before the first '*'), but *not* sending it
    # avoids hanging forever if a real serial LanBox never replies to it.
    requires_auth = False

    def __init__(self, device: str, baudrate: int = DEFAULT_BAUDRATE) -> None:
        self._device = device
        self._baudrate = baudrate
        self._serial: serial.Serial | None = None

    async def connect(self) -> None:
        self._serial = await asyncio.to_thread(
            serial.Serial, self._device, self._baudrate, timeout=None
        )

    async def write(self, data: bytes) -> None:
        assert self._serial is not None, "connect() must be called first"
        await asyncio.to_thread(self._serial.write, data)

    async def read(self, max_bytes: int = 4096) -> bytes:
        assert self._serial is not None, "connect() must be called first"

        def _read() -> bytes:
            assert self._serial is not None
            first = self._serial.read(1)  # blocks (timeout=None) until >=1 byte or port closes
            if not first:
                return b""
            extra_count = min(self._serial.in_waiting, max_bytes - 1)
            extra = self._serial.read(extra_count) if extra_count > 0 else b""
            return first + extra

        return await asyncio.to_thread(_read)

    async def close(self) -> None:
        if self._serial is not None:
            await asyncio.to_thread(self._serial.close)
            self._serial = None
