"""A scrollable table of Channel number / Value / Output for one Layer window.

Shows a fixed-size "window" of consecutive channel numbers (LanBox layers
can have up to 3072 channels, far more than fits on screen) which can be
paged with `set_window_start`.
"""

from __future__ import annotations

from textual.widgets import DataTable

from lanbox_tui.protocol.commands import ChannelStatus

MAX_CHANNEL = 3072


class ChannelGrid(DataTable):
    def __init__(self, *, window_size: int = 64, **kwargs) -> None:
        super().__init__(cursor_type="row", **kwargs)
        self.window_size = window_size
        self.window_start = 1

    def on_mount(self) -> None:
        self.add_column("Ch", key="ch")
        self.add_column("Value", key="value")
        self.add_column("Out", key="out")
        self.add_column("Act", key="active")
        self.add_column("Solo", key="solo")
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        self.clear()
        for offset in range(self.window_size):
            channel = self.window_start + offset
            self.add_row(str(channel), "0", "-", "-", "-", key=str(channel))

    def set_window_start(self, start: int) -> None:
        start = max(1, min(start, MAX_CHANNEL - self.window_size + 1))
        if start != self.window_start:
            self.window_start = start
            self._rebuild_rows()

    def page(self, direction: int) -> None:
        """Move the window forward/backward by one full window (direction: +1 or -1)."""
        self.set_window_start(self.window_start + direction * self.window_size)

    def update_values(
        self, values: dict[int, int], statuses: dict[int, ChannelStatus] | None = None
    ) -> None:
        for channel, value in values.items():
            row_key = str(channel)
            if row_key not in self.rows:
                continue
            self.update_cell(row_key, "value", str(value))
            if statuses is not None and channel in statuses:
                status = statuses[channel]
                self.update_cell(row_key, "out", "on" if status.output_to_mixer else "-")
                self.update_cell(row_key, "active", "on" if status.edit_enabled else "-")
                self.update_cell(row_key, "solo", "on" if status.solo_mode else "-")

    @property
    def selected_channel(self) -> int | None:
        if self.cursor_row is None or self.cursor_row < 0:
            return None
        return self.window_start + self.cursor_row
