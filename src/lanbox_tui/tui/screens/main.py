"""Main screen: Layer sidebar + live Channel grid for the selected Layer."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, ListItem, ListView, Static

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.commands import AppId, LayerSummary
from lanbox_tui.protocol.errors import LanBoxError
from lanbox_tui.protocol.framing import layer_label_to_id
from lanbox_tui.tui.widgets.channel_grid import ChannelGrid

POLL_INTERVAL_SECONDS = 0.2


class LayerListItem(ListItem):
    def __init__(self, layer: LayerSummary) -> None:
        marker = "●" if layer.attributes.output_enabled else "○"
        super().__init__(Label(f"{marker} {layer.label}"))
        self.layer_id = layer.layer_id
        self.layer_label = layer.label


class MainScreen(Screen):
    DEFAULT_CSS = """
    #layers {
        width: 12;
        border-right: solid $accent;
    }
    #content {
        padding: 0 1;
    }
    #value-input {
        display: none;
        margin-top: 1;
    }
    #value-input.visible {
        display: block;
    }
    """

    BINDINGS = [
        ("o", "toggle_output", "Toggle output"),
        ("a", "toggle_active", "Toggle active"),
        ("s", "toggle_solo", "Toggle solo"),
        ("v", "edit_value", "Set value"),
        ("[", "page_prev", "Prev page"),
        ("]", "page_next", "Next page"),
        ("c", "open_cue_lists", "Cue Lists"),
        ("g", "layer_go", "Go"),
        ("p", "toggle_pause", "Pause/Resume"),
        ("full_stop", "next_step", "Next step"),
        ("comma", "previous_step", "Prev step"),
        ("l", "open_layer_config", "Layer settings"),
        ("plus", "add_layer", "Add Layer"),
        ("minus", "delete_layer", "Delete Layer"),
        ("u", "move_layer_up", "Move Layer up"),
        ("n", "move_layer_down", "Move Layer down"),
        ("d", "open_global_settings", "Device settings"),
        ("escape", "cancel_edit", "Cancel edit"),
    ]

    def __init__(self, client: LanBoxClient, app_id: AppId) -> None:
        super().__init__()
        self.client = client
        self.app_id = app_id
        self.selected_layer_id: int | None = None
        self.selected_layer_label: str | None = None
        self._pending_action: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield ListView(id="layers")
            with Vertical(id="content"):
                yield Static(
                    f"{self.app_id.device_name} - firmware {self.app_id.firmware_version:.2f}",
                    id="device-status",
                )
                yield ChannelGrid(id="grid")
                yield Static("Select a Layer to view its Channels", id="grid-status")
                yield Input(placeholder="New value 0-255, Enter to apply", id="value-input")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load_layers(), exclusive=True)
        self.set_interval(POLL_INTERVAL_SECONDS, self._poll_channels)

    async def on_unmount(self) -> None:
        # Release the socket promptly instead of waiting for garbage collection -
        # matters both for a clean app quit and for tests tearing down a simulator.
        await self.client.close()

    async def _load_layers(self) -> None:
        status = self.query_one("#grid-status", Static)
        try:
            layers = await self.client.get_layers()
        except LanBoxError as exc:
            status.update(f"Failed to load Layers: {exc}")
            return
        list_view = self.query_one("#layers", ListView)
        await list_view.clear()
        for layer in layers:
            await list_view.append(LayerListItem(layer))

    @on(ListView.Selected, "#layers")
    def handle_layer_selected(self, event: ListView.Selected) -> None:
        assert isinstance(event.item, LayerListItem)
        self.selected_layer_id = event.item.layer_id
        self.selected_layer_label = event.item.layer_label
        grid = self.query_one("#grid", ChannelGrid)
        grid.set_window_start(1)
        self.query_one("#grid-status", Static).update(f"Layer {event.item.layer_label}")
        grid.focus()

    async def _poll_channels(self) -> None:
        if self.selected_layer_id is None:
            return
        grid = self.query_one("#grid", ChannelGrid)
        try:
            values = await self.client.read_channel_data(
                self.selected_layer_id, grid.window_start, grid.window_size
            )
            statuses = await self.client.read_channel_status(
                self.selected_layer_id, grid.window_start, grid.window_size
            )
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Poll failed: {exc}")
            return
        grid.update_values(values, statuses)

    def action_page_prev(self) -> None:
        self.query_one("#grid", ChannelGrid).page(-1)

    def action_page_next(self) -> None:
        self.query_one("#grid", ChannelGrid).page(1)

    def action_toggle_output(self) -> None:
        self._toggle_channel_flag("output_to_mixer", self.client.set_channel_output_enable)

    def action_toggle_active(self) -> None:
        self._toggle_channel_flag("edit_enabled", self.client.set_channel_active)

    def action_toggle_solo(self) -> None:
        self._toggle_channel_flag("solo_mode", self.client.set_channel_solo)

    def _toggle_channel_flag(self, status_attr: str, setter) -> None:
        if self.selected_layer_id is None:
            return
        grid = self.query_one("#grid", ChannelGrid)
        channel = grid.selected_channel
        if channel is None:
            return
        self.run_worker(
            self._toggle_channel(self.selected_layer_id, channel, status_attr, setter), exclusive=False
        )

    async def _toggle_channel(self, layer_id: int, channel: int, status_attr: str, setter) -> None:
        try:
            statuses = await self.client.read_channel_status(layer_id, channel, 1)
            currently_on = getattr(statuses[channel], status_attr)
            await setter(layer_id, {channel: not currently_on})
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Toggle failed: {exc}")

    def action_edit_value(self) -> None:
        grid = self.query_one("#grid", ChannelGrid)
        if grid.selected_channel is None:
            return
        self._open_prompt("set_channel_value", "New value 0-255, Enter to apply")

    def action_layer_go(self) -> None:
        if self.selected_layer_id is None:
            return
        self._open_prompt("layer_go", "Cue List[.Step] to Go, e.g. 5 or 5.2")

    def action_toggle_pause(self) -> None:
        if self.selected_layer_id is None:
            return
        self.run_worker(self._toggle_pause(self.selected_layer_id), exclusive=False)

    async def _toggle_pause(self, layer_id: int) -> None:
        try:
            status = await self.client.get_layer_status(layer_id)
            if status.pause_status:
                await self.client.layer_resume(layer_id)
            else:
                await self.client.layer_pause(layer_id)
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Pause/resume failed: {exc}")

    def action_next_step(self) -> None:
        if self.selected_layer_id is None:
            return
        self.run_worker(self._step(self.selected_layer_id, forward=True), exclusive=False)

    def action_previous_step(self) -> None:
        if self.selected_layer_id is None:
            return
        self.run_worker(self._step(self.selected_layer_id, forward=False), exclusive=False)

    async def _step(self, layer_id: int, *, forward: bool) -> None:
        try:
            if forward:
                await self.client.layer_next_step(layer_id)
            else:
                await self.client.layer_previous_step(layer_id)
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Step failed: {exc}")

    def action_open_cue_lists(self) -> None:
        from lanbox_tui.tui.screens.cue_lists import CueListsScreen  # avoid import at module load

        self.app.push_screen(CueListsScreen(self.client))

    def action_open_layer_config(self) -> None:
        if self.selected_layer_id is None or self.selected_layer_label is None:
            return
        from lanbox_tui.tui.screens.layer_config import LayerConfigScreen  # avoid import at module load

        self.app.push_screen(
            LayerConfigScreen(self.client, self.selected_layer_id, self.selected_layer_label)
        )

    def action_open_global_settings(self) -> None:
        from lanbox_tui.tui.screens.global_settings import GlobalSettingsScreen  # avoid import at module load

        self.app.push_screen(GlobalSettingsScreen(self.client))

    def action_add_layer(self) -> None:
        self._open_prompt("add_layer", "New Layer letter, e.g. F")

    def _submit_add_layer(self, text: str) -> None:
        status = self.query_one("#grid-status", Static)
        try:
            layer_id = layer_label_to_id(text)
        except ValueError:
            status.update(f"Invalid Layer letter: {text!r}")
            return
        self.run_worker(self._create_layer(layer_id), exclusive=False)

    async def _create_layer(self, layer_id: int) -> None:
        try:
            await self.client.create_layer(layer_id)
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Add Layer failed: {exc}")
            return
        await self._load_layers()

    def action_delete_layer(self) -> None:
        if self.selected_layer_id is None:
            return
        self.run_worker(self._delete_layer(self.selected_layer_id), exclusive=False)

    async def _delete_layer(self, layer_id: int) -> None:
        try:
            await self.client.delete_layer(layer_id)
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Delete Layer failed: {exc}")
            return
        self.selected_layer_id = None
        self.selected_layer_label = None
        await self._load_layers()

    def action_move_layer_up(self) -> None:
        if self.selected_layer_id is None:
            return
        self.run_worker(self._move_layer(self.selected_layer_id, direction=-1), exclusive=False)

    def action_move_layer_down(self) -> None:
        if self.selected_layer_id is None:
            return
        self.run_worker(self._move_layer(self.selected_layer_id, direction=1), exclusive=False)

    async def _move_layer(self, layer_id: int, *, direction: int) -> None:
        status = self.query_one("#grid-status", Static)
        try:
            layers = await self.client.get_layers()
        except LanBoxError as exc:
            status.update(f"Move failed: {exc}")
            return
        ids = [layer.layer_id for layer in layers]
        if layer_id not in ids:
            return
        neighbor_index = ids.index(layer_id) + direction
        if not 0 <= neighbor_index < len(ids):
            return
        neighbor_id = ids[neighbor_index]
        try:
            if direction < 0:
                await self.client.move_layer_above(destination=neighbor_id, source=layer_id)
            else:
                await self.client.move_layer_above(destination=layer_id, source=neighbor_id)
        except LanBoxError as exc:
            status.update(f"Move failed: {exc}")
            return
        await self._load_layers()

    def _open_prompt(self, pending: str, placeholder: str) -> None:
        self._pending_action = pending
        value_input = self.query_one("#value-input", Input)
        value_input.placeholder = placeholder
        value_input.value = ""
        value_input.add_class("visible")
        value_input.focus()

    def action_cancel_edit(self) -> None:
        value_input = self.query_one("#value-input", Input)
        value_input.remove_class("visible")
        self._pending_action = None
        self.query_one("#grid", ChannelGrid).focus()

    @on(Input.Submitted, "#value-input")
    def handle_value_submitted(self, event: Input.Submitted) -> None:
        value_input = self.query_one("#value-input", Input)
        value_input.remove_class("visible")
        pending, self._pending_action = self._pending_action, None
        self.query_one("#grid", ChannelGrid).focus()
        text = event.value.strip()
        if not text:
            return
        if pending == "layer_go":
            self._submit_layer_go(text)
        elif pending == "add_layer":
            self._submit_add_layer(text)
        else:
            self._submit_channel_value(text)

    def _submit_channel_value(self, text: str) -> None:
        grid = self.query_one("#grid", ChannelGrid)
        channel = grid.selected_channel
        if self.selected_layer_id is None or channel is None:
            return
        try:
            value = int(text)
        except ValueError:
            self.query_one("#grid-status", Static).update(f"Invalid value: {text!r}")
            return
        if not 0 <= value <= 255:
            self.query_one("#grid-status", Static).update("Value must be 0-255")
            return
        self.run_worker(
            self._set_channel(self.selected_layer_id, channel, value), exclusive=False
        )

    async def _set_channel(self, layer_id: int, channel: int, value: int) -> None:
        try:
            await self.client.set_channel_data(layer_id, {channel: value})
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Set failed: {exc}")

    def _submit_layer_go(self, text: str) -> None:
        status = self.query_one("#grid-status", Static)
        if self.selected_layer_id is None:
            return
        try:
            if "." in text:
                cue_list_text, cue_step_text = text.split(".", 1)
                cue_list, cue_step = int(cue_list_text), int(cue_step_text)
            else:
                cue_list, cue_step = int(text), None
        except ValueError:
            status.update(f"Invalid Cue List[.Step]: {text!r}")
            return
        self.run_worker(self._layer_go(self.selected_layer_id, cue_list, cue_step), exclusive=False)

    async def _layer_go(self, layer_id: int, cue_list: int, cue_step: int | None) -> None:
        try:
            await self.client.layer_go(layer_id, cue_list, cue_step)
        except LanBoxError as exc:
            self.query_one("#grid-status", Static).update(f"Go failed: {exc}")
