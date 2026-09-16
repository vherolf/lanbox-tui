"""Cue List browsing/editing screen, plus a Scene editor for Show Scene steps."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.commands import MAX_CUE_STEPS_PER_LIST
from lanbox_tui.protocol.cue_steps import STEP_SHOW_SCENE, CueStep, describe
from lanbox_tui.protocol.errors import LanBoxError
from lanbox_tui.tui.widgets.channel_grid import ChannelGrid


class SceneEditorScreen(Screen):
    """Edit the (sparse) Channel values that make up one Show Scene step."""

    DEFAULT_CSS = """
    #scene-status { margin-top: 1; }
    #scene-value-input { display: none; margin-top: 1; }
    #scene-value-input.visible { display: block; }
    """

    BINDINGS = [
        ("v", "edit_value", "Set value"),
        ("s", "save", "Save scene"),
        ("[", "page_prev", "Prev page"),
        ("]", "page_next", "Next page"),
        ("escape", "close", "Back"),
    ]

    def __init__(self, client: LanBoxClient, cue_list: int, cue_step: int) -> None:
        super().__init__()
        self.client = client
        self.cue_list = cue_list
        self.cue_step = cue_step
        self.values: dict[int, int] = {}

    def compose(self) -> ComposeResult:
        yield Static(f"Cue List {self.cue_list}, Step {self.cue_step} - Scene Data")
        yield ChannelGrid(id="scene-grid")
        yield Static("", id="scene-status")
        yield Input(placeholder="New value 0-255, Enter to apply", id="scene-value-input")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load(), exclusive=True)

    async def _load(self) -> None:
        status = self.query_one("#scene-status", Static)
        try:
            self.values = await self.client.read_cue_scene(self.cue_list, self.cue_step)
        except LanBoxError as exc:
            status.update(f"Failed to load scene: {exc}")
            return
        self._refresh_grid()
        status.update(f"{len(self.values)} channel(s) set")

    def _refresh_grid(self) -> None:
        grid = self.query_one("#scene-grid", ChannelGrid)
        window = {
            channel: self.values.get(channel, 0)
            for channel in range(grid.window_start, grid.window_start + grid.window_size)
        }
        grid.update_values(window)

    def action_page_prev(self) -> None:
        self.query_one("#scene-grid", ChannelGrid).page(-1)
        self._refresh_grid()

    def action_page_next(self) -> None:
        self.query_one("#scene-grid", ChannelGrid).page(1)
        self._refresh_grid()

    def action_edit_value(self) -> None:
        grid = self.query_one("#scene-grid", ChannelGrid)
        if grid.selected_channel is None:
            return
        value_input = self.query_one("#scene-value-input", Input)
        value_input.value = str(self.values.get(grid.selected_channel, 0))
        value_input.add_class("visible")
        value_input.focus()

    @on(Input.Submitted, "#scene-value-input")
    def handle_value_submitted(self, event: Input.Submitted) -> None:
        grid = self.query_one("#scene-grid", ChannelGrid)
        value_input = self.query_one("#scene-value-input", Input)
        value_input.remove_class("visible")
        grid.focus()
        channel = grid.selected_channel
        if channel is None:
            return
        text = event.value.strip()
        if not text:
            return
        try:
            value = int(text)
        except ValueError:
            self.query_one("#scene-status", Static).update(f"Invalid value: {text!r}")
            return
        if not 0 <= value <= 255:
            self.query_one("#scene-status", Static).update("Value must be 0-255")
            return
        if value == 0:
            self.values.pop(channel, None)
        else:
            self.values[channel] = value
        self._refresh_grid()

    def action_save(self) -> None:
        self.run_worker(self._save(), exclusive=True)

    async def _save(self) -> None:
        status = self.query_one("#scene-status", Static)
        if not self.values:
            status.update("Nothing to save yet - an empty scene can't be written")
            return
        try:
            await self.client.write_cue_scene(self.cue_list, self.cue_step, self.values)
        except LanBoxError as exc:
            status.update(f"Save failed: {exc}")
            return
        status.update(f"Saved ({len(self.values)} channel(s))")

    def action_close(self) -> None:
        self.app.pop_screen()


class CueListsScreen(Screen):
    DEFAULT_CSS = """
    #lists {
        width: 24;
        border-right: solid $accent;
    }
    #steps-panel {
        padding: 0 1;
    }
    #step-input {
        display: none;
        margin-top: 1;
    }
    #step-input.visible {
        display: block;
    }
    """

    BINDINGS = [
        ("n", "new_cue_list", "New list"),
        ("d", "delete_cue_list", "Delete list"),
        ("s", "add_show_scene", "Add Show Scene"),
        ("h", "add_hold", "Add Hold"),
        ("j", "add_go_step", "Add Go-Step"),
        ("e", "edit_scene", "Edit scene"),
        ("x", "delete_step", "Delete step"),
        ("escape", "cancel_or_close", "Cancel/Back"),
    ]

    def __init__(self, client: LanBoxClient) -> None:
        super().__init__()
        self.client = client
        self.selected_cue_list: int | None = None
        self.steps: list[CueStep] = []
        self._pending_action: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="lists"):
                yield Static("Cue Lists")
                yield DataTable(id="cue-list-table")
            with Vertical(id="steps-panel"):
                yield Static("Steps", id="steps-title")
                yield DataTable(id="steps-table")
                yield Static("", id="cue-status")
                yield Input(id="step-input")
        yield Footer()

    def on_mount(self) -> None:
        directory_table = self.query_one("#cue-list-table", DataTable)
        directory_table.cursor_type = "row"
        directory_table.add_column("List", key="number")
        directory_table.add_column("Steps", key="count")

        steps_table = self.query_one("#steps-table", DataTable)
        steps_table.cursor_type = "row"
        steps_table.add_column("#", key="index")
        steps_table.add_column("Description", key="description")

        self.run_worker(self._load_directory(), exclusive=True)
        directory_table.focus()

    async def _load_directory(self) -> None:
        status = self.query_one("#cue-status", Static)
        try:
            directory = await self.client.get_cue_list_directory()
        except LanBoxError as exc:
            status.update(f"Failed to load Cue Lists: {exc}")
            return
        table = self.query_one("#cue-list-table", DataTable)
        table.clear()
        for info in directory:
            table.add_row(str(info.number), str(info.step_count), key=str(info.number))

    @on(DataTable.RowSelected, "#cue-list-table")
    def handle_cue_list_selected(self, event: DataTable.RowSelected) -> None:
        cue_list = int(event.row_key.value)
        self.selected_cue_list = cue_list
        self.run_worker(self._load_steps(cue_list), exclusive=True)

    async def _load_steps(self, cue_list: int) -> None:
        status = self.query_one("#cue-status", Static)
        try:
            self.steps = await self.client.read_cue_list(cue_list)
        except LanBoxError as exc:
            status.update(f"Failed to load steps: {exc}")
            return
        self._refresh_steps_table()
        status.update(f"Cue List {cue_list}: {len(self.steps)} step(s)")

    def _refresh_steps_table(self) -> None:
        table = self.query_one("#steps-table", DataTable)
        table.clear()
        for index, step in enumerate(self.steps, start=1):
            table.add_row(str(index), describe(step), key=str(index))

    def _selected_step_index(self) -> int | None:
        table = self.query_one("#steps-table", DataTable)
        if table.cursor_row is None or table.cursor_row < 0:
            return None
        index = table.cursor_row + 1
        return index if index <= len(self.steps) else None

    # --- prompt handling (new Cue List number / step parameters) ---

    def _open_prompt(self, pending: str, placeholder: str) -> None:
        self._pending_action = pending
        box = self.query_one("#step-input", Input)
        box.placeholder = placeholder
        box.value = ""
        box.add_class("visible")
        box.focus()

    def action_cancel_or_close(self) -> None:
        box = self.query_one("#step-input", Input)
        if "visible" in box.classes:
            box.remove_class("visible")
            self._pending_action = None
            return
        self.app.pop_screen()

    def action_new_cue_list(self) -> None:
        self._open_prompt("new_cue_list", "New Cue List number (1-999)")

    def action_add_show_scene(self) -> None:
        if self.selected_cue_list is None:
            return
        self._open_prompt("add_show_scene", "fade_seconds,hold_seconds e.g. 0.5,2.0")

    def action_add_hold(self) -> None:
        if self.selected_cue_list is None:
            return
        self._open_prompt("add_hold", "Hold seconds")

    def action_add_go_step(self) -> None:
        if self.selected_cue_list is None:
            return
        self._open_prompt("add_go_step", "Target step number")

    @on(Input.Submitted, "#step-input")
    def handle_step_input_submitted(self, event: Input.Submitted) -> None:
        box = self.query_one("#step-input", Input)
        box.remove_class("visible")
        pending, self._pending_action = self._pending_action, None
        text = event.value.strip()
        status = self.query_one("#cue-status", Static)
        if pending is None or not text:
            return
        try:
            if pending == "new_cue_list":
                self.run_worker(self._create_cue_list(int(text)), exclusive=False)
            elif pending == "add_show_scene":
                fade_text, hold_text = (part.strip() for part in text.split(",", 1))
                step = CueStep.show_scene(
                    fade_type=3, fade_seconds=float(fade_text), hold_seconds=float(hold_text)
                )
                self.run_worker(self._append_step(step), exclusive=False)
            elif pending == "add_go_step":
                self.run_worker(self._append_step(CueStep.go_cue_step(int(text))), exclusive=False)
            elif pending == "add_hold":
                self.run_worker(self._append_step(CueStep.hold(float(text))), exclusive=False)
        except ValueError as exc:
            status.update(f"Invalid input: {exc}")

    # --- actions that talk to the LanBox ---

    async def _create_cue_list(self, cue_list: int) -> None:
        status = self.query_one("#cue-status", Static)
        try:
            # CueListWrite creates the list if it doesn't exist yet; a Cue List
            # can't be written with zero steps, so seed it with a placeholder.
            await self.client.write_cue_list(cue_list, [CueStep.hold(1.0)])
        except LanBoxError as exc:
            status.update(f"Create failed: {exc}")
            return
        await self._load_directory()
        self.selected_cue_list = cue_list
        await self._load_steps(cue_list)

    def action_delete_cue_list(self) -> None:
        if self.selected_cue_list is not None:
            self.run_worker(self._delete_cue_list(self.selected_cue_list), exclusive=False)

    async def _delete_cue_list(self, cue_list: int) -> None:
        status = self.query_one("#cue-status", Static)
        try:
            await self.client.remove_cue_list(cue_list)
        except LanBoxError as exc:
            status.update(f"Delete failed: {exc}")
            return
        self.selected_cue_list = None
        self.steps = []
        self._refresh_steps_table()
        await self._load_directory()

    async def _append_step(self, step: CueStep) -> None:
        status = self.query_one("#cue-status", Static)
        if self.selected_cue_list is None:
            return
        new_steps = [*self.steps, step]
        if len(new_steps) > MAX_CUE_STEPS_PER_LIST:
            status.update(f"Cue List already has the maximum {MAX_CUE_STEPS_PER_LIST} steps")
            return
        try:
            await self.client.write_cue_list(self.selected_cue_list, new_steps)
        except LanBoxError as exc:
            status.update(f"Add step failed: {exc}")
            return
        await self._load_steps(self.selected_cue_list)
        await self._load_directory()

    def action_delete_step(self) -> None:
        index = self._selected_step_index()
        if self.selected_cue_list is not None and index is not None:
            self.run_worker(self._delete_step(self.selected_cue_list, index), exclusive=False)

    async def _delete_step(self, cue_list: int, index: int) -> None:
        status = self.query_one("#cue-status", Static)
        try:
            await self.client.remove_cue_list_step(cue_list, index)
        except LanBoxError as exc:
            status.update(f"Delete step failed: {exc}")
            return
        await self._load_steps(cue_list)
        await self._load_directory()

    def action_edit_scene(self) -> None:
        index = self._selected_step_index()
        if (
            self.selected_cue_list is None
            or index is None
            or self.steps[index - 1].kind != STEP_SHOW_SCENE
        ):
            self.query_one("#cue-status", Static).update("Select a Show Scene step to edit")
            return
        self.app.push_screen(SceneEditorScreen(self.client, self.selected_cue_list, index))
