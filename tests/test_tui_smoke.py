"""Headless end-to-end smoke test: drive the real Textual app against the simulator.

This is what catches widget-wiring bugs (bad query_one selectors, missing
ids, CSS typos) that the protocol-level tests can't see.
"""

import asyncio
import os
import pty

import pytest
from textual.widgets import DataTable, Input, ListView, Static

from test_serial_transport import SimulatorPeer

from lanbox_tui.protocol.cue_steps import STEP_SHOW_SCENE
from lanbox_tui.simulator.server import make_connection_handler
from lanbox_tui.simulator.state import LanBoxState
from lanbox_tui.tui.app import LanBoxApp
from lanbox_tui.tui.screens.cue_lists import CueListsScreen, SceneEditorScreen
from lanbox_tui.tui.screens.global_settings import GlobalSettingsScreen
from lanbox_tui.tui.screens.layer_config import LayerConfigScreen
from lanbox_tui.tui.screens.main import MainScreen
from lanbox_tui.tui.widgets.channel_grid import ChannelGrid


@pytest.fixture
async def simulator_address():
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


async def test_connect_screen_reaches_main_screen(simulator_address):
    host, port, _state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        pilot.app.screen.query_one("#host", Input).value = host
        pilot.app.screen.query_one("#port", Input).value = str(port)
        pilot.app.screen.query_one("#password", Input).value = "777"
        await pilot.click("#connect")
        await pilot.pause()
        # allow the connect worker's awaits (connect/16bit/app-id/push_screen) to settle
        for _ in range(10):
            if isinstance(pilot.app.screen, MainScreen):
                break
            await pilot.pause(0.05)
        assert isinstance(pilot.app.screen, MainScreen)


async def test_main_screen_lists_layers_and_polls_channels(simulator_address):
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        pilot.app.screen.query_one("#host", Input).value = host
        pilot.app.screen.query_one("#port", Input).value = str(port)
        await pilot.click("#connect")
        for _ in range(10):
            if isinstance(pilot.app.screen, MainScreen):
                break
            await pilot.pause(0.05)
        screen = pilot.app.screen
        assert isinstance(screen, MainScreen)

        list_view = screen.query_one("#layers", ListView)
        for _ in range(10):
            if len(list_view.children) > 0:
                break
            await pilot.pause(0.05)
        assert len(list_view.children) == 5  # default simulated Layers A-E

        # Select Layer A and let a poll cycle run.
        await pilot.pause(0.3)
        list_view.index = 0
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert screen.selected_layer_id == 1

        # Drive a value through the simulator directly and confirm the grid picks it up.
        state.layers[1].channel(1).value = 42
        state.layers[1].channel(1).output_to_mixer = True
        await pilot.pause(0.3)
        grid = screen.query_one("#grid", ChannelGrid)
        assert grid.get_cell("1", "value") == "42"

        status = screen.query_one("#device-status", Static)
        assert "LCX" in str(status.render())


async def _reach_main_screen_with_layer_a_selected(pilot, host, port):
    pilot.app.screen.query_one("#host", Input).value = host
    pilot.app.screen.query_one("#port", Input).value = str(port)
    await pilot.click("#connect")
    for _ in range(10):
        if isinstance(pilot.app.screen, MainScreen):
            break
        await pilot.pause(0.05)
    screen = pilot.app.screen
    assert isinstance(screen, MainScreen)
    list_view = screen.query_one("#layers", ListView)
    for _ in range(10):
        if len(list_view.children) > 0:
            break
        await pilot.pause(0.05)
    list_view.index = 0
    await pilot.press("enter")
    await pilot.pause(0.1)
    assert screen.selected_layer_id == 1
    return screen


async def test_cue_list_workflow_end_to_end(simulator_address):
    """Create a Cue List, add a Show Scene step, edit its scene, run it with
    Go, and exercise pause/resume/previous-step - all through real key presses
    against the real screens, backed by the simulator."""
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)

        await pilot.press("c")
        for _ in range(10):
            if isinstance(pilot.app.screen, CueListsScreen):
                break
            await pilot.pause(0.05)
        cue_screen = pilot.app.screen
        assert isinstance(cue_screen, CueListsScreen)

        # Create Cue List 1 (seeded with a placeholder Hold step).
        await pilot.press("n")
        await pilot.pause()
        cue_screen.query_one("#step-input", Input).value = "1"
        await pilot.press("enter")
        for _ in range(10):
            if cue_screen.selected_cue_list == 1 and cue_screen.steps:
                break
            await pilot.pause(0.05)
        assert cue_screen.selected_cue_list == 1
        assert len(cue_screen.steps) == 1

        # Append a Show Scene step (fade 0.2s, hold 1.0s).
        await pilot.press("s")
        await pilot.pause()
        cue_screen.query_one("#step-input", Input).value = "0.2,1.0"
        await pilot.press("enter")
        for _ in range(10):
            if len(cue_screen.steps) == 2:
                break
            await pilot.pause(0.05)
        assert len(cue_screen.steps) == 2
        assert cue_screen.steps[1].kind == STEP_SHOW_SCENE

        # Select the Show Scene step and open its Scene editor.
        steps_table = cue_screen.query_one("#steps-table", DataTable)
        steps_table.focus()
        steps_table.move_cursor(row=1)
        await pilot.pause()
        await pilot.press("e")
        for _ in range(10):
            if isinstance(pilot.app.screen, SceneEditorScreen):
                break
            await pilot.pause(0.05)
        scene_screen = pilot.app.screen
        assert isinstance(scene_screen, SceneEditorScreen)

        scene_grid = scene_screen.query_one("#scene-grid", ChannelGrid)
        scene_grid.focus()
        await pilot.pause()
        await pilot.press("v")  # edit Channel 1 (the cursor's default row)
        await pilot.pause()
        scene_screen.query_one("#scene-value-input", Input).value = "123"
        await pilot.press("enter")
        await pilot.pause()
        assert scene_screen.values.get(1) == 123
        await pilot.press("s")  # save the scene
        await pilot.pause()
        assert "Saved" in str(scene_screen.query_one("#scene-status", Static).render())

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(pilot.app.screen, CueListsScreen)
        await pilot.press("escape")
        for _ in range(10):
            if pilot.app.screen is main_screen:
                break
            await pilot.pause(0.05)
        assert pilot.app.screen is main_screen

        # Run the Cue List on Layer A, going straight to the Show Scene step.
        await pilot.press("g")
        await pilot.pause()
        main_screen.query_one("#value-input", Input).value = "1.2"
        await pilot.press("enter")
        for _ in range(20):
            main_grid = main_screen.query_one("#grid", ChannelGrid)
            if main_grid.get_cell("1", "value") == "123":
                break
            await pilot.pause(0.1)
        assert main_screen.query_one("#grid", ChannelGrid).get_cell("1", "value") == "123"
        assert state.layers[1].active_cue_step == 2

        # Pause / resume.
        await pilot.press("p")
        for _ in range(10):
            if state.layers[1].paused:
                break
            await pilot.pause(0.05)
        assert state.layers[1].paused is True
        await pilot.press("p")
        for _ in range(10):
            if not state.layers[1].paused:
                break
            await pilot.pause(0.05)
        assert state.layers[1].paused is False

        # Previous step: back to step 1 (the Hold placeholder).
        await pilot.press("comma")
        for _ in range(10):
            if state.layers[1].active_cue_step == 1:
                break
            await pilot.pause(0.05)
        assert state.layers[1].active_cue_step == 1


async def test_layer_config_screen_edits_apply(simulator_address):
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)

        await pilot.press("l")
        for _ in range(10):
            if isinstance(pilot.app.screen, LayerConfigScreen):
                break
            await pilot.pause(0.05)
        layer_screen = pilot.app.screen
        assert isinstance(layer_screen, LayerConfigScreen)
        for _ in range(10):
            if layer_screen.attributes is not None:
                break
            await pilot.pause(0.05)
        assert layer_screen.attributes.output_enabled is True

        await pilot.press("1")  # toggle Output off
        for _ in range(10):
            if state.layers[1].output_enabled is False:
                break
            await pilot.pause(0.05)
        assert state.layers[1].output_enabled is False

        await pilot.press("m")  # cycle Mix Mode: Copy(1) -> HTP(2)
        for _ in range(10):
            if state.layers[1].mix_mode == 2:
                break
            await pilot.pause(0.05)
        assert state.layers[1].mix_mode == 2

        await pilot.press("t")
        await pilot.pause()
        layer_screen.query_one("#layer-input", Input).value = "128"
        await pilot.press("enter")
        for _ in range(10):
            if state.layers[1].transparency_depth == 128:
                break
            await pilot.pause(0.05)
        assert state.layers[1].transparency_depth == 128

        await pilot.press("r")
        await pilot.pause()
        layer_screen.query_one("#layer-input", Input).value = "Z"
        await pilot.press("enter")
        for _ in range(10):
            if 1 not in state.layers:
                break
            await pilot.pause(0.05)
        assert 1 not in state.layers
        new_id = layer_screen.layer_id
        assert state.layers[new_id].layer_id == new_id

        await pilot.press("escape")
        for _ in range(10):
            if pilot.app.screen is main_screen:
                break
            await pilot.pause(0.05)
        assert pilot.app.screen is main_screen


async def test_main_screen_add_move_delete_layer(simulator_address):
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)

        list_view = main_screen.query_one("#layers", ListView)
        initial_count = len(list_view.children)

        await pilot.press("plus")
        await pilot.pause()
        main_screen.query_one("#value-input", Input).value = "Q"
        await pilot.press("enter")
        for _ in range(10):
            if len(list_view.children) == initial_count + 1:
                break
            await pilot.pause(0.05)
        assert len(list_view.children) == initial_count + 1
        assert 17 in state.layers  # "Q" -> Layer ID 17
        assert state.layer_order[0] == 17  # new Layers land on top

        # Select the new top Layer (Q) and move it down one slot. Focus must
        # move back to the list explicitly - submitting the Add Layer prompt
        # returns focus to the Channel grid, same as every other prompt.
        list_view.focus()
        await pilot.pause()
        list_view.index = 0
        await pilot.press("enter")
        await pilot.pause()
        assert main_screen.selected_layer_id == 17
        await pilot.press("n")
        for _ in range(10):
            if state.layer_order[0] != 17:
                break
            await pilot.pause(0.05)
        assert state.layer_order[1] == 17

        await pilot.press("minus")
        for _ in range(10):
            if 17 not in state.layers:
                break
            await pilot.pause(0.05)
        assert 17 not in state.layers
        assert len(list_view.children) == initial_count


async def test_channel_active_and_solo_toggles(simulator_address):
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)

        state.layers[1].channel(1).value = 42
        state.layers[1].channel(1).output_to_mixer = True
        await pilot.pause(0.3)

        grid = main_screen.query_one("#grid", ChannelGrid)
        grid.focus()
        assert state.layers[1].channel(1).edit_enabled is True
        await pilot.press("a")
        for _ in range(20):
            if grid.get_cell("1", "active") == "-":
                break
            await pilot.pause(0.1)
        assert state.layers[1].channel(1).edit_enabled is False
        assert grid.get_cell("1", "active") == "-"

        assert state.layers[1].channel(1).solo_mode is False
        await pilot.press("s")
        for _ in range(20):
            if grid.get_cell("1", "solo") == "on":
                break
            await pilot.pause(0.1)
        assert state.layers[1].channel(1).solo_mode is True
        assert grid.get_cell("1", "solo") == "on"


async def test_global_settings_screen_edits_apply(simulator_address):
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)

        await pilot.press("d")
        for _ in range(10):
            if isinstance(pilot.app.screen, GlobalSettingsScreen):
                break
            await pilot.pause(0.05)
        settings_screen = pilot.app.screen
        assert isinstance(settings_screen, GlobalSettingsScreen)
        for _ in range(10):
            if settings_screen.data is not None:
                break
            await pilot.pause(0.05)
        assert settings_screen.data.name == state.name

        await pilot.press("n")
        await pilot.pause()
        settings_screen.query_one("#settings-input", Input).value = "My LanBox"
        await pilot.press("enter")
        for _ in range(10):
            if state.name == "My LanBox":
                break
            await pilot.pause(0.05)
        assert state.name == "My LanBox"
        assert "My LanBox" in str(settings_screen.query_one("#settings-summary", Static).render())

        await pilot.press("o")
        await pilot.pause()
        settings_screen.query_one("#settings-input", Input).value = "256"
        await pilot.press("enter")
        for _ in range(10):
            if state.dmx_out_offset == 256:
                break
            await pilot.pause(0.05)
        assert state.dmx_out_offset == 256

        summary = settings_screen.query_one("#settings-summary", Static)
        assert "MIDI (31250 baud)" in str(summary.render())  # factory default 0x83, not "131"
        await pilot.press("b")
        for _ in range(10):
            if state.baud_rate_param == 0x02:
                break
            await pilot.pause(0.05)
        assert state.baud_rate_param == 0x02  # MIDI mode -> serial out at 9600
        for _ in range(10):
            if "9600" in str(summary.render()):
                break
            await pilot.pause(0.05)
        assert "9600" in str(summary.render())

        await pilot.press("escape")
        for _ in range(10):
            if pilot.app.screen is main_screen:
                break
            await pilot.pause(0.05)
        assert pilot.app.screen is main_screen


async def test_connect_screen_reaches_main_screen_over_serial():
    """Same connect flow as the TCP smoke test, but through the new
    serial-device field - exercises _connect()'s serial branch, which has
    no other test coverage."""
    from lanbox_tui.simulator.state import LanBoxState

    master_fd, slave_fd = pty.openpty()
    device_path = os.ttyname(slave_fd)
    state = LanBoxState(password="777")
    peer = SimulatorPeer(master_fd, state)
    try:
        app = LanBoxApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            pilot.app.screen.query_one("#serial-device", Input).value = device_path
            await pilot.click("#connect")
            for _ in range(10):
                if isinstance(pilot.app.screen, MainScreen):
                    break
                await pilot.pause(0.05)
            assert isinstance(pilot.app.screen, MainScreen)
    finally:
        peer.close()
        os.close(slave_fd)
        os.close(master_fd)


# --- Regression scenarios from the 2026-10 audit (see tests/test_regressions.py) ---


async def test_main_screen_follows_a_renamed_layer(simulator_address):
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)
        await pilot.press("l")
        for _ in range(10):
            if isinstance(pilot.app.screen, LayerConfigScreen):
                break
            await pilot.pause(0.05)
        layer_screen = pilot.app.screen
        for _ in range(10):
            if layer_screen.attributes is not None:
                break
            await pilot.pause(0.05)
        await pilot.press("r")
        await pilot.pause()
        layer_screen.query_one("#layer-input", Input).value = "Z"
        await pilot.press("enter")
        for _ in range(10):
            if 26 in state.layers:
                break
            await pilot.pause(0.05)
        await pilot.press("escape")
        list_view = main_screen.query_one("#layers", ListView)
        for _ in range(20):
            if main_screen.selected_layer_id == 26 and any(i.layer_label == "Z" for i in list_view.children):
                break
            await pilot.pause(0.05)
        assert main_screen.selected_layer_id == 26
        assert [item.layer_label for item in list_view.children][0] == "Z"
        await pilot.pause(0.5)  # a few poll cycles against the renamed Layer
        assert "Poll failed" not in str(main_screen.query_one("#grid-status", Static).render())


async def test_too_long_device_name_is_rejected_without_crashing(simulator_address):
    host, port, state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await _reach_main_screen_with_layer_a_selected(pilot, host, port)
        await pilot.press("d")
        for _ in range(10):
            if isinstance(pilot.app.screen, GlobalSettingsScreen) and pilot.app.screen.data is not None:
                break
            await pilot.pause(0.05)
        settings_screen = pilot.app.screen
        await pilot.press("n")
        await pilot.pause()
        settings_screen.query_one("#settings-input", Input).value = "a name that is far too long"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert pilot.app.is_running
        assert "Invalid input" in str(settings_screen.query_one("#settings-message", Static).render())
        assert state.name == "LanBox LCX"


async def test_out_of_range_go_is_rejected_without_crashing(simulator_address):
    host, port, _state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)
        await pilot.press("g")
        await pilot.pause()
        main_screen.query_one("#value-input", Input).value = "5.300"
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert pilot.app.is_running
        assert "step 0-99" in str(main_screen.query_one("#grid-status", Static).render())


async def test_lost_connection_is_reported_instead_of_crashing(simulator_address):
    host, port, _state = simulator_address
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        main_screen = await _reach_main_screen_with_layer_a_selected(pilot, host, port)

        async def reset_by_peer(max_bytes: int = 4096) -> bytes:
            raise ConnectionResetError("simulated: LanBox rebooted")

        main_screen.client._transport.read = reset_by_peer
        status = main_screen.query_one("#grid-status", Static)
        for _ in range(20):
            if "Connection lost" in str(status.render()):
                break
            await pilot.pause(0.05)
        assert pilot.app.is_running
        assert "Connection lost" in str(status.render())


async def test_cue_list_with_out_of_table_time_code_displays(simulator_address):
    from lanbox_tui.protocol.cue_steps import CueStep

    host, port, state = simulator_address
    # Show Scene with fade code 0x00, which isn't in Appendix A's table.
    state.cue_lists[1] = [CueStep(wait=False, kind=0x01, params=(0, 0x00, 0x1B, 0, 0, 0))]
    app = LanBoxApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await _reach_main_screen_with_layer_a_selected(pilot, host, port)
        await pilot.press("c")
        for _ in range(10):
            if isinstance(pilot.app.screen, CueListsScreen):
                break
            await pilot.pause(0.05)
        cue_screen = pilot.app.screen
        directory = cue_screen.query_one("#cue-list-table", DataTable)
        for _ in range(10):
            if directory.row_count:
                break
            await pilot.pause(0.05)
        directory.focus()
        await pilot.press("enter")
        steps_table = cue_screen.query_one("#steps-table", DataTable)
        for _ in range(10):
            if steps_table.row_count:
                break
            await pilot.pause(0.05)
        assert pilot.app.is_running
        assert "code 0x00" in str(steps_table.get_cell("1", "description"))
