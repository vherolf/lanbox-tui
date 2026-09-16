"""Per-Layer configuration screen: attribute toggles, Mix/Chase/Fade settings."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.commands import LayerAttributes, LayerStatus
from lanbox_tui.protocol.cue_steps import decode_cue_time
from lanbox_tui.protocol.errors import LanBoxError
from lanbox_tui.protocol.framing import layer_label_to_id

_MIX_MODE_NAMES = {0: "Off", 1: "Copy", 2: "HTP", 3: "LTP", 4: "Transparent", 5: "Add"}
_CHASE_MODE_NAMES = {
    0: "Off", 1: "Chase Up", 2: "Loop Up", 3: "Chase Down", 4: "Loop Down",
    5: "Random", 6: "Loop Random", 7: "Bounce", 8: "Loop Bounce",
}
_FADE_TYPE_NAMES = {
    0: "Off", 1: "Fade In", 2: "Fade Out", 3: "Cross Fade",
    4: "Off", 5: "Fade In CR", 6: "Fade Out CR", 7: "Cross Fade CR",
}


def _format_seconds(seconds: float | None) -> str:
    return "forever" if seconds is None else f"{seconds:.2f}s"


def _on_off(value: bool) -> str:
    return "On" if value else "Off"


class LayerConfigScreen(Screen):
    # This screen is driven entirely by BINDINGS, not focus-dependent widgets
    # like the other screens' Lists/DataTables/ChannelGrids - without this,
    # Textual's default AUTO_FOCUS="*" would auto-focus the (hidden) Input
    # since it's the first focusable widget in the DOM, silently swallowing
    # every keypress as text entry instead of letting it reach the bindings.
    # NOTE: `None` here means "inherit App.AUTO_FOCUS" (still "*"!) per
    # Screen's own fallback logic - an empty string is what actually disables it.
    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    #layer-input { display: none; margin-top: 1; }
    #layer-input.visible { display: block; }
    #layer-message { margin-top: 1; }
    """

    BINDINGS = [
        ("1", "toggle_output", "Output"),
        ("2", "toggle_fading", "Fading"),
        ("3", "toggle_solo", "Solo"),
        ("4", "toggle_auto_output", "Auto Output"),
        ("5", "toggle_locked", "Locked"),
        ("m", "cycle_mix_mode", "Mix Mode"),
        ("t", "prompt_transparency", "Transparency"),
        ("c", "cycle_chase_mode", "Chase Mode"),
        ("v", "prompt_chase_speed", "Chase Speed"),
        ("f", "cycle_fade_type", "Fade Type"),
        ("d", "prompt_fade_time", "Fade Time"),
        ("r", "prompt_rename", "Rename"),
        ("escape", "close_or_cancel", "Back"),
    ]

    def __init__(self, client: LanBoxClient, layer_id: int, layer_label: str) -> None:
        super().__init__()
        self.client = client
        self.layer_id = layer_id
        self.layer_label = layer_label
        self.attributes: LayerAttributes | None = None
        self.layer_status: LayerStatus | None = None
        self._pending_action: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="layer-summary")
        yield Static("", id="layer-message")
        yield Input(id="layer-input")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load(), exclusive=True)

    async def _load(self) -> None:
        message = self.query_one("#layer-message", Static)
        try:
            layers = await self.client.get_layers()
            matching = next((layer for layer in layers if layer.layer_id == self.layer_id), None)
            if matching is None:
                message.update(f"Layer {self.layer_id} no longer exists")
                return
            self.attributes = matching.attributes
            self.layer_label = matching.label
            self.layer_status = await self.client.get_layer_status(self.layer_id)
        except LanBoxError as exc:
            message.update(f"Failed to load Layer: {exc}")
            return
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        assert self.attributes is not None and self.layer_status is not None
        attrs, status = self.attributes, self.layer_status
        fade_seconds = decode_cue_time(status.manual_fade_time_code)
        lines = [
            f"Layer {self.layer_label} (id {self.layer_id})",
            "",
            f"[1] Output:       {_on_off(attrs.output_enabled)}",
            f"[2] Fading:       {_on_off(attrs.fading_enabled)}",
            f"[3] Solo:         {_on_off(attrs.solo_mode)}",
            f"[4] Auto Output:  {_on_off(attrs.auto_activate)}",
            f"[5] Locked:       {_on_off(attrs.locked)}",
            f"[m] Mix Mode:     {_MIX_MODE_NAMES.get(status.mix_status, status.mix_status)}",
            f"[t] Transparency: {status.transparency_depth_percent}",
            f"[c] Chase Mode:   {_CHASE_MODE_NAMES.get(status.chase_mode, status.chase_mode)}",
            f"[v] Chase Speed:  {status.layer_speed_percent}",
            f"[f] Fade Type:    {_FADE_TYPE_NAMES.get(status.manual_fade_type, status.manual_fade_type)}",
            f"[d] Fade Time:    {_format_seconds(fade_seconds)}",
            "[r] Rename...",
        ]
        self.query_one("#layer-summary", Static).update("\n".join(lines))

    # --- boolean toggles ---

    async def _toggle(self, attr_name: str, setter) -> None:
        if self.attributes is None:
            return
        current = getattr(self.attributes, attr_name)
        try:
            await setter(self.layer_id, not current)
        except LanBoxError as exc:
            self.query_one("#layer-message", Static).update(f"Change failed: {exc}")
            return
        await self._load()

    def action_toggle_output(self) -> None:
        self.run_worker(self._toggle("output_enabled", self.client.set_layer_output), exclusive=False)

    def action_toggle_fading(self) -> None:
        self.run_worker(self._toggle("fading_enabled", self.client.set_layer_fading), exclusive=False)

    def action_toggle_solo(self) -> None:
        self.run_worker(self._toggle("solo_mode", self.client.set_layer_solo), exclusive=False)

    def action_toggle_auto_output(self) -> None:
        self.run_worker(self._toggle("auto_activate", self.client.set_layer_auto_output), exclusive=False)

    def action_toggle_locked(self) -> None:
        self.run_worker(self._toggle("locked", self.client.set_layer_locked), exclusive=False)

    # --- cycled enums ---

    async def _cycle(self, attr_name: str, max_value: int, setter) -> None:
        if self.layer_status is None:
            return
        current = getattr(self.layer_status, attr_name)
        new_value = (current + 1) % (max_value + 1)
        try:
            await setter(self.layer_id, new_value)
        except LanBoxError as exc:
            self.query_one("#layer-message", Static).update(f"Change failed: {exc}")
            return
        await self._load()

    def action_cycle_mix_mode(self) -> None:
        self.run_worker(self._cycle("mix_status", 5, self.client.set_layer_mix_mode), exclusive=False)

    def action_cycle_chase_mode(self) -> None:
        self.run_worker(self._cycle("chase_mode", 8, self.client.set_layer_chase_mode), exclusive=False)

    def action_cycle_fade_type(self) -> None:
        self.run_worker(self._cycle("manual_fade_type", 7, self.client.set_layer_fade_type), exclusive=False)

    # --- numeric/text prompts ---

    def _open_prompt(self, pending: str, placeholder: str) -> None:
        self._pending_action = pending
        box = self.query_one("#layer-input", Input)
        box.placeholder = placeholder
        box.value = ""
        box.add_class("visible")
        box.focus()

    def action_prompt_transparency(self) -> None:
        self._open_prompt("transparency", "Transparency depth 0-255")

    def action_prompt_chase_speed(self) -> None:
        self._open_prompt("chase_speed", "Chase speed 0-255")

    def action_prompt_fade_time(self) -> None:
        self._open_prompt("fade_time", "Fade time in seconds")

    def action_prompt_rename(self) -> None:
        self._open_prompt("rename", "New Layer letter, e.g. F")

    def action_close_or_cancel(self) -> None:
        box = self.query_one("#layer-input", Input)
        if "visible" in box.classes:
            box.remove_class("visible")
            self._pending_action = None
            return
        self.app.pop_screen()

    @on(Input.Submitted, "#layer-input")
    def handle_input_submitted(self, event: Input.Submitted) -> None:
        box = self.query_one("#layer-input", Input)
        box.remove_class("visible")
        pending, self._pending_action = self._pending_action, None
        text = event.value.strip()
        message = self.query_one("#layer-message", Static)
        if pending is None or not text:
            return
        try:
            if pending == "transparency":
                value = int(text)
                if not 0 <= value <= 255:
                    raise ValueError("must be 0-255")
                self.run_worker(self._apply(self.client.set_layer_transparency_depth, value), exclusive=False)
            elif pending == "chase_speed":
                value = int(text)
                if not 0 <= value <= 255:
                    raise ValueError("must be 0-255")
                self.run_worker(self._apply(self.client.set_layer_chase_speed, value), exclusive=False)
            elif pending == "fade_time":
                self.run_worker(self._apply(self.client.set_layer_fade_time, float(text)), exclusive=False)
            elif pending == "rename":
                self.run_worker(self._rename(layer_label_to_id(text)), exclusive=False)
        except ValueError as exc:
            message.update(f"Invalid input: {exc}")

    async def _apply(self, setter, value) -> None:
        try:
            await setter(self.layer_id, value)
        except LanBoxError as exc:
            self.query_one("#layer-message", Static).update(f"Change failed: {exc}")
            return
        await self._load()

    async def _rename(self, new_id: int) -> None:
        try:
            await self.client.set_layer_id(self.layer_id, new_id)
        except LanBoxError as exc:
            self.query_one("#layer-message", Static).update(f"Rename failed: {exc}")
            return
        self.layer_id = new_id
        await self._load()
