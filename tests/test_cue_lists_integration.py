import asyncio

import pytest

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.cue_steps import CueStep, STEP_CLEAR_LAYER
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


async def test_cue_list_directory_starts_empty_then_lists_created_lists(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        assert await client.get_cue_list_directory() == []
        steps = [CueStep.hold(1.0)]
        await client.write_cue_list(5, steps)
        await client.write_cue_list(1, steps)
        directory = await client.get_cue_list_directory()
        assert [info.number for info in directory] == [1, 5]
        assert all(info.step_count == 1 for info in directory)
    finally:
        await client.close()


async def test_write_then_read_cue_list_round_trips(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        steps = [
            CueStep.show_scene(fade_type=3, fade_seconds=2.0, hold_seconds=2.0),
            CueStep.hold(0.10),
            CueStep.go_cue_step(1),
        ]
        await client.write_cue_list(42, steps)
        read_back = await client.read_cue_list(42)
        assert read_back == steps
    finally:
        await client.close()


async def test_remove_cue_list_and_step(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        steps = [CueStep.hold(1.0), CueStep.hold(2.0), CueStep.hold(3.0)]
        await client.write_cue_list(7, steps)

        await client.remove_cue_list_step(7, 2)
        remaining = await client.read_cue_list(7)
        assert [s.hold_seconds for s in remaining] == [1.0, 3.0]

        await client.remove_cue_list(7)
        assert state.cue_lists.get(7) is None
        assert (await client.get_cue_list_directory()) == []
    finally:
        await client.close()


async def test_cue_scene_round_trips_and_pages_over_250(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        await client.write_cue_list(1, [CueStep.show_scene(fade_type=0, fade_seconds=0, hold_seconds=1.0)])
        values = {channel: channel % 256 for channel in range(1, 301)}  # 300 channels, forces 2 pages
        await client.write_cue_scene(1, 1, values)
        read_back = await client.read_cue_scene(1, 1)
        assert read_back == values
    finally:
        await client.close()


async def test_layer_go_applies_show_scene_immediately(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        steps = [
            CueStep.show_scene(fade_type=0, fade_seconds=0, hold_seconds=1.0),
            CueStep.show_scene(fade_type=0, fade_seconds=0, hold_seconds=1.0),
        ]
        await client.write_cue_list(1, steps)
        await client.write_cue_scene(1, 1, {10: 100})
        await client.write_cue_scene(1, 2, {10: 200})

        await client.layer_go(layer=1, cue_list=1, cue_step=1)
        values = await client.read_channel_data(1, 10, 1)
        assert values[10] == 100

        await client.layer_next_step(layer=1)
        values = await client.read_channel_data(1, 10, 1)
        assert values[10] == 200

        await client.layer_previous_step(layer=1)
        values = await client.read_channel_data(1, 10, 1)
        assert values[10] == 100
    finally:
        await client.close()


async def test_layer_pause_and_resume_toggle_state(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.write_cue_list(1, [CueStep.hold(1.0)])
        await client.layer_go(layer=1, cue_list=1, cue_step=1)
        assert state.layers[1].paused is False

        await client.layer_pause(1)
        assert state.layers[1].paused is True

        await client.layer_resume(1)
        assert state.layers[1].paused is False
    finally:
        await client.close()


async def test_layer_clear_empties_channels(simulator):
    host, port, state = simulator
    client = await _connected_client(host, port)
    try:
        await client.set_channel_data(1, {1: 50})
        await client.layer_clear(1)
        assert state.layers[1].channels == {}
    finally:
        await client.close()


async def test_layer_control_cue_step_type_round_trips_through_simulator(simulator):
    host, port, _state = simulator
    client = await _connected_client(host, port)
    try:
        steps = [CueStep.layer_control(STEP_CLEAR_LAYER, layer_id=2)]
        await client.write_cue_list(9, steps)
        read_back = await client.read_cue_list(9)
        assert read_back == steps
    finally:
        await client.close()
