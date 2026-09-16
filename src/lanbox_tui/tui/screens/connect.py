"""Connection screen: host/port/password entry, then hands off to MainScreen."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol.errors import LanBoxError
from lanbox_tui.transport.serial import DEFAULT_BAUDRATE, SerialTransport
from lanbox_tui.transport.tcp import DEFAULT_PORT, TcpTransport


class ConnectScreen(Screen):
    DEFAULT_CSS = """
    ConnectScreen {
        align: center middle;
    }
    #connect-form {
        width: 46;
        border: round $accent;
        padding: 1 2;
    }
    #connect-form Input {
        margin-bottom: 1;
    }
    #status {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="connect-form"):
            yield Label("Connect to LanBox")
            yield Input(placeholder="Host (e.g. 192.168.1.77 or localhost)", id="host")
            yield Input(placeholder=f"Port (default {DEFAULT_PORT})", id="port")
            yield Input(placeholder="Password (default 777)", password=True, id="password")
            yield Input(
                placeholder=f"Serial device[:baud] e.g. /dev/ttyUSB0 (default {DEFAULT_BAUDRATE}) - blank for TCP",
                id="serial-device",
            )
            yield Button("Connect", variant="primary", id="connect")
            yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#host", Input).focus()

    @on(Button.Pressed, "#connect")
    def handle_connect_pressed(self) -> None:
        self.run_worker(self._connect(), exclusive=True)

    @on(Input.Submitted)
    def handle_input_submitted(self) -> None:
        self.run_worker(self._connect(), exclusive=True)

    async def _connect(self) -> None:
        status = self.query_one("#status", Static)
        serial_device = self.query_one("#serial-device", Input).value.strip()

        if serial_device:
            device_path, _, baud_text = serial_device.partition(":")
            try:
                baudrate = int(baud_text) if baud_text else DEFAULT_BAUDRATE
            except ValueError:
                status.update("Baud rate must be a number")
                return
            client = LanBoxClient(SerialTransport(device_path, baudrate))
        else:
            host = self.query_one("#host", Input).value.strip() or "127.0.0.1"
            port_text = self.query_one("#port", Input).value.strip()
            password = self.query_one("#password", Input).value.strip() or "777"
            try:
                port = int(port_text) if port_text else DEFAULT_PORT
            except ValueError:
                status.update("Port must be a number")
                return
            client = LanBoxClient(TcpTransport(host, port), password=password)

        status.update("Connecting...")
        try:
            await client.connect()
            await client.set_16bit_mode(True)
            app_id = await client.get_app_id()
        except LanBoxError as exc:
            status.update(f"Connection failed: {exc}")
            return
        except OSError as exc:
            status.update(f"Could not reach host: {exc}")
            return

        from lanbox_tui.tui.screens.main import MainScreen  # avoid circular import at module load

        await self.app.push_screen(MainScreen(client, app_id))
