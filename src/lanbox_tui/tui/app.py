"""Textual application entrypoint for the LanBox TUI."""

from __future__ import annotations

from textual.app import App

from lanbox_tui.tui.screens.connect import ConnectScreen


class LanBoxApp(App):
    TITLE = "LanBox TUI"

    def on_mount(self) -> None:
        self.push_screen(ConnectScreen())


def run() -> None:
    LanBoxApp().run()


if __name__ == "__main__":
    run()
