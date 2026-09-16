"""Global/Device Settings screen: name, network, DMX output, baud rate."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.commands import BAUD_RATE_NAMES, GlobalData, MAX_NAME_LENGTH
from lanbox_tui.protocol.errors import LanBoxError

_BAUD_RATE_ORDER = sorted(BAUD_RATE_NAMES)


def _format_address(octets: tuple[int, int, int, int]) -> str:
    return ".".join(str(octet) for octet in octets)


def _parse_address(text: str) -> tuple[int, int, int, int]:
    parts = [int(part.strip()) for part in text.split(".")]
    if len(parts) != 4 or not all(0 <= part <= 255 for part in parts):
        raise ValueError(f"not a valid dotted-quad address: {text!r}")
    return (parts[0], parts[1], parts[2], parts[3])


class GlobalSettingsScreen(Screen):
    # Bindings-only screen, no naturally-focused widget - see the project
    # memory note: `AUTO_FOCUS = None` would silently inherit App.AUTO_FOCUS
    # ("*") and let the hidden Input steal every keypress as text entry.
    AUTO_FOCUS = ""

    DEFAULT_CSS = """
    #settings-input { display: none; margin-top: 1; }
    #settings-input.visible { display: block; }
    #settings-message { margin-top: 1; }
    """

    BINDINGS = [
        ("n", "prompt_rename", "Rename"),
        ("p", "prompt_password", "Password"),
        ("o", "prompt_dmx_offset", "DMX Offset"),
        ("c", "prompt_dmx_channels", "DMX Channels"),
        ("i", "prompt_ip_config", "IP Config"),
        ("b", "cycle_baud_rate", "Baud Rate"),
        ("s", "save_data", "Save"),
        ("r", "reboot", "Reboot"),
        ("escape", "close_or_cancel", "Back"),
    ]

    def __init__(self, client: LanBoxClient) -> None:
        super().__init__()
        self.client = client
        self.data: GlobalData | None = None
        self._pending_action: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("Loading...", id="settings-summary")
        yield Static("", id="settings-message")
        yield Input(id="settings-input")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._load(), exclusive=True)

    async def _load(self) -> None:
        message = self.query_one("#settings-message", Static)
        try:
            self.data = await self.client.get_global_data()
        except LanBoxError as exc:
            message.update(f"Failed to load settings: {exc}")
            return
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        assert self.data is not None
        data = self.data
        baud_name = BAUD_RATE_NAMES.get(data.baud_rate_param, str(data.baud_rate_param))
        lines = [
            "LanBox Global Settings",
            "",
            f"[n] Name:          {data.name}",
            "[p] Password:      (hidden - press to change)",
            f"[i] IP Address:    {_format_address(data.ip_address)}",
            f"    Subnet Mask:   {_format_address(data.subnet_mask)}",
            f"    Gateway:       {_format_address(data.gateway)}",
            f"[o] DMX Out Offset: {data.dmx_out_offset}",
            f"[c] DMX Channels:  {data.dmx_channel_count}",
            f"[b] Baud Rate:     {baud_name}",
            "",
            "[s] Save to flash   [r] Reboot",
            "",
            "Note: IP/password/baud rate changes need a Save + Reboot to take",
            "effect on real hardware, and the reference chart warns to change",
            "IP/password 'with extreme care'.",
        ]
        self.query_one("#settings-summary", Static).update("\n".join(lines))

    # --- prompts ---

    def _open_prompt(self, pending: str, placeholder: str, initial: str = "") -> None:
        self._pending_action = pending
        box = self.query_one("#settings-input", Input)
        box.placeholder = placeholder
        box.value = initial
        box.add_class("visible")
        box.focus()

    def action_prompt_rename(self) -> None:
        current = self.data.name if self.data else ""
        self._open_prompt("rename", f"New name (<= {MAX_NAME_LENGTH} chars)", current)

    def action_prompt_password(self) -> None:
        self._open_prompt("password", "New password 0-65535")

    def action_prompt_dmx_offset(self) -> None:
        current = str(self.data.dmx_out_offset) if self.data else ""
        self._open_prompt("dmx_offset", "DMX Out Offset 0-512", current)

    def action_prompt_dmx_channels(self) -> None:
        current = str(self.data.dmx_channel_count) if self.data else ""
        self._open_prompt("dmx_channels", "Number of DMX Channels 0-512", current)

    def action_prompt_ip_config(self) -> None:
        if self.data is None:
            return
        initial = (
            f"{_format_address(self.data.ip_address)},"
            f"{_format_address(self.data.subnet_mask)},"
            f"{_format_address(self.data.gateway)}"
        )
        self._open_prompt("ip_config", "IP,Subnet,Gateway e.g. 192.168.1.77,255.255.255.0,192.168.1.1", initial)

    def action_close_or_cancel(self) -> None:
        box = self.query_one("#settings-input", Input)
        if "visible" in box.classes:
            box.remove_class("visible")
            self._pending_action = None
            return
        self.app.pop_screen()

    @on(Input.Submitted, "#settings-input")
    def handle_input_submitted(self, event: Input.Submitted) -> None:
        box = self.query_one("#settings-input", Input)
        box.remove_class("visible")
        pending, self._pending_action = self._pending_action, None
        text = event.value.strip()
        message = self.query_one("#settings-message", Static)
        if pending is None or not text:
            return
        try:
            if pending == "rename":
                self.run_worker(self._apply(self.client.set_name, text), exclusive=False)
            elif pending == "password":
                value = int(text)
                if not 0 <= value <= 65535:
                    raise ValueError("must be 0-65535")
                self.run_worker(self._apply(self.client.set_password, value), exclusive=False)
            elif pending == "dmx_offset":
                value = int(text)
                if not 0 <= value <= 512:
                    raise ValueError("must be 0-512")
                self.run_worker(self._apply(self.client.set_dmx_offset, value), exclusive=False)
            elif pending == "dmx_channels":
                value = int(text)
                if not 0 <= value <= 512:
                    raise ValueError("must be 0-512")
                self.run_worker(self._apply(self.client.set_num_dmx_channels, value), exclusive=False)
            elif pending == "ip_config":
                ip_text, subnet_text, gateway_text = (part.strip() for part in text.split(",", 2))
                ip, subnet, gateway = _parse_address(ip_text), _parse_address(subnet_text), _parse_address(gateway_text)
                self.run_worker(self._apply_ip_config(ip, subnet, gateway), exclusive=False)
        except ValueError as exc:
            message.update(f"Invalid input: {exc}")

    async def _apply(self, setter, value) -> None:
        try:
            await setter(value)
        except LanBoxError as exc:
            self.query_one("#settings-message", Static).update(f"Change failed: {exc}")
            return
        await self._load()

    async def _apply_ip_config(self, ip, subnet, gateway) -> None:
        try:
            await self.client.set_ip_config(ip, subnet, gateway)
        except LanBoxError as exc:
            self.query_one("#settings-message", Static).update(f"Change failed: {exc}")
            return
        await self._load()

    # --- baud rate cycle, save, reboot ---

    def action_cycle_baud_rate(self) -> None:
        self.run_worker(self._cycle_baud_rate(), exclusive=False)

    async def _cycle_baud_rate(self) -> None:
        if self.data is None:
            return
        current_index = (
            _BAUD_RATE_ORDER.index(self.data.baud_rate_param)
            if self.data.baud_rate_param in _BAUD_RATE_ORDER
            else -1
        )
        new_param = _BAUD_RATE_ORDER[(current_index + 1) % len(_BAUD_RATE_ORDER)]
        try:
            await self.client.set_baud_rate(new_param)
        except LanBoxError as exc:
            self.query_one("#settings-message", Static).update(f"Change failed: {exc}")
            return
        await self._load()

    def action_save_data(self) -> None:
        self.run_worker(self._save_data(), exclusive=False)

    async def _save_data(self) -> None:
        message = self.query_one("#settings-message", Static)
        try:
            await self.client.save_data()
        except LanBoxError as exc:
            message.update(f"Save failed: {exc}")
            return
        message.update("Saved to flash.")

    def action_reboot(self) -> None:
        self.run_worker(self._reboot(), exclusive=False)

    async def _reboot(self) -> None:
        message = self.query_one("#settings-message", Static)
        try:
            await self.client.reboot()
        except LanBoxError as exc:
            message.update(f"Reboot failed: {exc}")
            return
        message.update("Reboot requested.")
