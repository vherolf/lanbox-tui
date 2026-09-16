import asyncio

import pytest

from lanbox_tui.client import LanBoxClient
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


async def _connected_client(host: str, port: int) -> LanBoxClient:
    client = LanBoxClient(TcpTransport(host, port), password="777")
    await client.connect()
    return client


async def test_boolean_layer_attributes_toggle(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_layer_output(1, False)
        assert state.layers[1].output_enabled is False
        await client.set_layer_fading(1, False)
        assert state.layers[1].fading_enabled is False
        await client.set_layer_solo(1, True)
        assert state.layers[1].solo_mode is True
        await client.set_layer_auto_output(1, False)
        assert state.layers[1].auto_activate is False
        await client.set_layer_locked(1, True)
        assert state.layers[1].locked is True
    finally:
        await client.close()


async def test_mix_chase_and_fade_values_round_trip(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_layer_mix_mode(1, 4)
        assert state.layers[1].mix_mode == 4
        await client.set_layer_transparency_depth(1, 51)
        assert state.layers[1].transparency_depth == 51
        await client.set_layer_chase_mode(1, 2)
        assert state.layers[1].chase_mode == 2
        await client.set_layer_chase_speed(1, 170)
        assert state.layers[1].chase_speed == 170
        await client.set_layer_fade_type(1, 3)
        assert state.layers[1].fade_type == 3
        await client.set_layer_fade_time(1, 2.0)
        assert state.layers[1].fade_time_code == 0x1B  # Appendix A: 2.00s

        status = await client.get_layer_status(1)
        assert status.mix_status == 4
        assert status.chase_mode == 2
        assert status.layer_speed_percent == 170
        assert status.manual_fade_type == 3
        assert status.manual_fade_time_code == 0x1B
        assert status.transparency_depth_percent == 51
    finally:
        await client.close()


async def test_rename_layer_id(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_layer_id(1, 30)
        assert 1 not in state.layers
        assert state.layers[30].layer_id == 30
        layers = await client.get_layers()
        assert layers[0].layer_id == 30  # still on top of the mixing order
    finally:
        await client.close()


async def test_create_and_delete_layer(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.create_layer(10)
        layers = await client.get_layers()
        assert layers[0].layer_id == 10  # new Layer lands on top
        assert layers[0].attributes.output_enabled is True
        assert layers[0].attributes.auto_activate is True

        await client.delete_layer(10)
        layers = await client.get_layers()
        assert all(layer.layer_id != 10 for layer in layers)
        assert 10 not in state.layers
    finally:
        await client.close()


async def test_create_layer_with_explicit_attributes_and_cue(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.create_layer(20, attributes=0x00, start_cue_list=5, start_cue_step=2)
        layer = state.layers[20]
        assert layer.output_enabled is False
        assert layer.active_cue_list == 5
        assert layer.active_cue_step == 2
    finally:
        await client.close()


async def test_move_layer_reorders_mixing_stack(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        assert state.layer_order == [1, 2, 3, 4, 5]
        # Place Layer 5 directly above Layer 1 -> [5, 1, 2, 3, 4]
        await client.move_layer_above(destination=1, source=5)
        assert state.layer_order == [5, 1, 2, 3, 4]
        layers = await client.get_layers()
        assert [layer.layer_id for layer in layers] == [5, 1, 2, 3, 4]
    finally:
        await client.close()
