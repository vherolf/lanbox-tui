"""Tests SerialTransport against a real OS pty pair - no real hardware,
no external tools (socat etc.) required. pty is POSIX-only, which matches
this project's Linux/Unix-first scope.
"""

from __future__ import annotations

import asyncio
import os
import pty

import pytest

from lanbox_tui.client import LanBoxClient
from lanbox_tui.simulator.server import RequestReader, dispatch
from lanbox_tui.simulator.state import LanBoxState
from lanbox_tui.transport.serial import SerialTransport


class EchoPeer:
    """Master-side of a pty pair that echoes back whatever it reads."""

    def __init__(self, master_fd: int) -> None:
        self._master_fd = master_fd
        asyncio.get_running_loop().add_reader(master_fd, self._on_readable)

    def _on_readable(self) -> None:
        try:
            chunk = os.read(self._master_fd, 4096)
        except OSError:
            return
        if chunk:
            os.write(self._master_fd, chunk)

    def close(self) -> None:
        asyncio.get_running_loop().remove_reader(self._master_fd)


class SimulatorPeer:
    """Master-side of a pty pair speaking the real LanBox protocol, reusing
    the simulator's own request parsing/dispatch (RequestReader/dispatch) -
    the same functions the TCP simulator uses, just fed from a pty instead
    of a socket."""

    def __init__(self, master_fd: int, state: LanBoxState) -> None:
        self._master_fd = master_fd
        self._state = state
        self._request_reader = RequestReader()
        asyncio.get_running_loop().add_reader(master_fd, self._on_readable)

    def _on_readable(self) -> None:
        try:
            chunk = os.read(self._master_fd, 4096)
        except OSError:
            return
        if not chunk:
            return
        for body in self._request_reader.feed(chunk):
            os.write(self._master_fd, dispatch(body, self._state))

    def close(self) -> None:
        asyncio.get_running_loop().remove_reader(self._master_fd)


@pytest.fixture
def pty_pair():
    master_fd, slave_fd = pty.openpty()
    device_path = os.ttyname(slave_fd)
    try:
        yield master_fd, slave_fd, device_path
    finally:
        try:
            os.close(slave_fd)
        except OSError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass


async def test_serial_transport_write_and_read_round_trip(pty_pair):
    master_fd, _slave_fd, device_path = pty_pair
    peer = EchoPeer(master_fd)
    transport = SerialTransport(device_path, baudrate=115200)
    try:
        await transport.connect()
        await transport.write(b"hello")
        received = b""
        while len(received) < 5:
            received += await transport.read()
        assert received == b"hello"
    finally:
        await transport.close()
        peer.close()


async def test_serial_transport_does_not_require_auth():
    assert SerialTransport.requires_auth is False


async def test_lanbox_client_connects_and_talks_over_serial(pty_pair):
    master_fd, _slave_fd, device_path = pty_pair
    state = LanBoxState(password="777")
    peer = SimulatorPeer(master_fd, state)
    client = LanBoxClient(SerialTransport(device_path, baudrate=115200))
    try:
        await client.connect()  # no password should be sent or expected
        assert client.connected is True

        app_id = await client.get_app_id()
        assert app_id.device_name == "LCX"

        layers = await client.get_layers()
        assert [layer.label for layer in layers] == ["A", "B", "C", "D", "E"]

        await client.set_channel_data(layer=1, values={5: 200})
        values = await client.read_channel_data(layer=1, start_channel=5, count=1)
        assert values[5] == 200
    finally:
        await client.close()
        peer.close()
