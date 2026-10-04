"""Smoke-test the PyInstaller binaries in DIST_DIR.

Bundling problems (a Textual stylesheet or a lazily imported module that
PyInstaller didn't pick up) only show up when a binary actually runs, so:
1. start lanbox-simulator and talk the LanBox protocol to it over TCP;
2. start lanbox-tui in a pseudo-terminal and wait for its connect screen.

Usage: python packaging/smoke_test.py DIST_DIR
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import socket
import struct
import subprocess
import sys
import termios
import time

ANSI = re.compile(rb"\x1b(\[[0-9;?<>=]*[ -/]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)|[@-Z\\-_])")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check_simulator(binary: str) -> None:
    port = free_port()
    proc = subprocess.Popen([binary, "--port", str(port)], stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise SystemExit(f"lanbox-simulator didn't start:\n{proc.stderr.read().decode()}")
                time.sleep(0.2)
        with sock:
            sock.settimeout(5)
            sock.sendall(b"777\r")
            assert sock.recv(16) == b">", "password not accepted"
            sock.sendall(b"*00050000#")  # CommonGetAppID
            reply = sock.recv(64)
            assert reply.startswith(b"*F8FD"), f"unexpected CommonGetAppID reply: {reply!r}"
        print("lanbox-simulator: OK, answered CommonGetAppID with", reply)
    finally:
        proc.terminate()
        proc.wait(10)


def check_tui(binary: str) -> None:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    env = {**os.environ, "TERM": "xterm-256color"}
    proc = subprocess.Popen(
        [binary], stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True
    )
    os.close(slave)
    output = b""
    try:
        deadline = time.monotonic() + 60  # first start of a onefile binary unpacks itself
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            ready, _, _ = select.select([master], [], [], 0.5)
            if ready:
                try:
                    output += os.read(master, 65536)
                except OSError:
                    break
                if b"Connect to LanBox" in ANSI.sub(b"", output):
                    print("lanbox-tui: OK, drew its connect screen")
                    return
        text = ANSI.sub(b"", output).decode(errors="replace")
        raise SystemExit(f"lanbox-tui never drew its connect screen (exit code {proc.poll()}):\n{text[-3000:]}")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(10)
        os.close(master)


def main() -> None:
    dist = sys.argv[1]
    check_simulator(os.path.join(dist, "lanbox-simulator"))
    check_tui(os.path.join(dist, "lanbox-tui"))


if __name__ == "__main__":
    main()
