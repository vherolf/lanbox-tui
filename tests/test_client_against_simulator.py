import asyncio

import pytest

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.errors import AuthenticationError, CommandRejected
from lanbox_tui.simulator.server import make_connection_handler
from lanbox_tui.simulator.state import LanBoxState
from lanbox_tui.transport.tcp import TcpTransport


@pytest.fixture
async def simulator():
    """Start the simulator on an OS-assigned free port; yield (host, port, state)."""
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


async def test_connect_rejects_wrong_password(simulator):
    host, port, _state = simulator
    client = LanBoxClient(TcpTransport(host, port), password="wrong")
    with pytest.raises(AuthenticationError):
        await client.connect()


async def test_get_app_id_reports_simulated_device(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        app_id = await client.get_app_id()
        assert app_id.device_code == state.device_code
        assert app_id.device_name == "LCX"
        assert app_id.firmware_version == pytest.approx(state.firmware_version)
    finally:
        await client.close()


async def test_set_16bit_mode_updates_simulator_state(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        assert state.sixteen_bit_mode is False
        await client.set_16bit_mode(True)
        assert state.sixteen_bit_mode is True
    finally:
        await client.close()


async def test_get_layers_returns_default_five_layers(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        layers = await client.get_layers()
        assert [layer.label for layer in layers] == ["A", "B", "C", "D", "E"]
        assert all(layer.attributes.output_enabled for layer in layers)
    finally:
        await client.close()


async def test_set_then_read_channel_data_round_trips(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_channel_data(layer=1, values={5: 200, 6: 50})
        values = await client.read_channel_data(layer=1, start_channel=5, count=2)
        assert values == {5: 200, 6: 50}

        statuses = await client.read_channel_status(layer=1, start_channel=5, count=2)
        assert statuses[5].output_to_mixer is True
        assert statuses[6].output_to_mixer is True
    finally:
        await client.close()


async def test_set_channel_output_enable_toggles_status(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_channel_data(layer=1, values={10: 100})
        await client.set_channel_output_enable(layer=1, values={10: False})
        statuses = await client.read_channel_status(layer=1, start_channel=10, count=1)
        assert statuses[10].output_to_mixer is False
    finally:
        await client.close()


async def test_set_channel_active_toggles_status(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_channel_data(layer=1, values={11: 100})
        await client.set_channel_active(layer=1, values={11: False})
        statuses = await client.read_channel_status(layer=1, start_channel=11, count=1)
        assert statuses[11].edit_enabled is False
    finally:
        await client.close()


async def test_set_channel_solo_toggles_status(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_channel_data(layer=1, values={12: 100})
        await client.set_channel_solo(layer=1, values={12: True})
        statuses = await client.read_channel_status(layer=1, start_channel=12, count=1)
        assert statuses[12].solo_mode is True
    finally:
        await client.close()


async def test_set_channel_active_all_channels_marker(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_channel_data(layer=1, values={1: 1, 2: 2, 3: 3})
        await client.set_channel_active(layer=1, values={0: False})
        statuses = await client.read_channel_status(layer=1, start_channel=1, count=3)
        assert all(status.edit_enabled is False for status in statuses.values())
    finally:
        await client.close()


async def test_unknown_layer_is_rejected(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        with pytest.raises(CommandRejected):
            await client.get_layer_status(layer_id=63)
    finally:
        await client.close()
