import asyncio

import pytest

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.errors import AuthenticationError
from lanbox_tui.simulator.server import make_connection_handler
from lanbox_tui.simulator.state import LanBoxState
from lanbox_tui.transport.tcp import TcpTransport


@pytest.fixture
async def simulator():
    state = LanBoxState(password="777")
    server = await asyncio.start_server(make_connection_handler(state), "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    async with server:
        task = asyncio.create_task(server.serve_forever())
        try:
            yield host, port, state
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def _connected_client(host: str, port: int, password: str = "777") -> LanBoxClient:
    client = LanBoxClient(TcpTransport(host, port), password=password)
    await client.connect()
    return client


async def test_get_global_data_reflects_defaults(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        data = await client.get_global_data()
        assert data.name == state.name
        assert data.ip_address == state.ip_address
        assert data.subnet_mask == state.subnet_mask
        assert data.gateway == state.gateway
        assert data.dmx_out_offset == state.dmx_out_offset
        assert data.dmx_channel_count == state.dmx_channel_count
        assert data.baud_rate_param == state.baud_rate_param
    finally:
        await client.close()


async def test_set_name(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_name("My LanBox")
        assert state.name == "My LanBox"
        data = await client.get_global_data()
        assert data.name == "My LanBox"
    finally:
        await client.close()


async def test_set_dmx_offset_and_channel_count(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_dmx_offset(256)
        await client.set_num_dmx_channels(255)
        assert state.dmx_out_offset == 256
        assert state.dmx_channel_count == 255
    finally:
        await client.close()


async def test_set_ip_config(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_ip_config(ip=(192, 168, 1, 76), subnet=(255, 255, 0, 0), gateway=(192, 168, 1, 1))
        assert state.ip_address == (192, 168, 1, 76)
        assert state.subnet_mask == (255, 255, 0, 0)
        assert state.gateway == (192, 168, 1, 1)
    finally:
        await client.close()


async def test_set_baud_rate(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_baud_rate(2)
        assert state.baud_rate_param == 2
        data = await client.get_global_data()
        assert data.baud_rate_param == 2
    finally:
        await client.close()


async def test_set_password_changes_auth(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_password(1012)
        assert state.password == "1012"
    finally:
        await client.close()

    # The old password should no longer work; the new one should.
    with pytest.raises(AuthenticationError):
        stale_client = LanBoxClient(TcpTransport(host, port), password="777")
        await stale_client.connect()

    new_client = await _connected_client(host, port, password="1012")
    await new_client.close()


async def test_reboot_and_save_data_are_accepted(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        await client.save_data()
        await client.reboot()
    finally:
        await client.close()
