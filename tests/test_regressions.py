"""Regression tests for the bugs found in the 2026-10 audit against the PDFs.

Each test reproduces one specific finding; see the README "Implementation
status" (v7) for the write-up.
"""

import asyncio
import socket
import struct

import pytest

from lanbox_tui.client import LanBoxClient
from lanbox_tui.protocol import commands
from lanbox_tui.protocol.cue_steps import CueStep, describe
from lanbox_tui.protocol.errors import ConnectionLostError, LanBoxError, ReplyTimeoutError
from lanbox_tui.protocol.framing import ProtocolFramingError, Reply, ReplyReader, hex8, hex16
from lanbox_tui.simulator.server import make_connection_handler
from lanbox_tui.simulator.state import LanBoxState
from lanbox_tui.transport.tcp import TcpTransport


# --- Framing: malformed bytes must be catchable and must not wedge the stream ---


def test_framing_error_is_a_lanbox_error():
    assert issubclass(ProtocolFramingError, LanBoxError)


def test_reply_reader_skips_garbage_before_a_reply():
    # e.g. a password banner the reference chart doesn't document
    reader = ReplyReader()
    reader.feed(b"LanBox password: \r\n>")
    assert reader.pop_ready() == [Reply(ok=True, data=None)]


def test_reply_reader_recovers_after_a_bad_frame_trailer():
    reader = ReplyReader()
    reader.feed(b"*0102#X>")
    with pytest.raises(LanBoxError):
        reader.pop_ready()
    # the bad frame was dropped; the stream resynchronises on the next reply
    assert reader.pop_ready() == [Reply(ok=True, data=None)]


# --- Cue time codes outside Appendix A must not crash display code ---


def test_describe_tolerates_out_of_table_time_codes():
    assert "0x00" in describe(CueStep(wait=False, kind=0x01, params=(0, 0x00, 0x1B, 0, 0, 0)))
    assert "0x7F" in describe(CueStep(wait=False, kind=0x18, params=(0x7F, 0, 0, 0, 0, 0)))


# --- Baud rate is the MIDI port's, 0x80-0x83 = MIDI mode (LCedit manual p.57) ---


def test_describe_baud_rate_understands_midi_mode():
    assert "MIDI" in commands.describe_baud_rate(0x83)
    assert "9600" in commands.describe_baud_rate(0x02)
    assert "MIDI" not in commands.describe_baud_rate(0x02)


# --- Multi-frame writes: first frame declares the total, continuations 0 ---


def test_cue_list_continuation_frame_declares_zero_steps():
    request = commands.build_write_cue_list(1, [CueStep.hold(1.0)], declared_count=0)
    assert request.startswith(b"*AA000100")


def test_cue_list_frame_is_limited_to_70_steps():
    with pytest.raises(ValueError):
        commands.build_write_cue_list(1, [CueStep.hold(1.0)] * 71)


def test_cue_scene_first_frame_declares_total():
    request = commands.build_write_cue_scene(1, 1, {1: 255}, declared_count=300)
    assert request.startswith(b"*AC" + (hex16(1) + hex8(1) + hex8(0) + hex16(300)).encode())


# --- Client <-> simulator ---


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


async def _client(host, port) -> LanBoxClient:
    client = LanBoxClient(TcpTransport(host, port))
    await client.connect()
    return client


async def test_99_step_cue_list_round_trips_in_70_step_frames(simulator):
    host, port, state = simulator
    client = await _client(host, port)
    try:
        steps = [CueStep.go_cue_step(i % 99 + 1) for i in range(99)]
        await client.write_cue_list(5, steps)
        assert state.cue_lists[5] == steps
        assert await client.read_cue_list(5) == steps
    finally:
        await client.close()


async def test_cue_list_write_rejects_more_than_99_steps(simulator):
    host, port, _state = simulator
    client = await _client(host, port)
    try:
        with pytest.raises(ValueError):
            await client.write_cue_list(5, [CueStep.hold(1.0)] * 100)
    finally:
        await client.close()


async def test_cue_scene_rewrite_replaces_the_scene(simulator):
    # Removing a channel in the scene editor (value 0 -> dropped) must stick.
    host, port, _state = simulator
    client = await _client(host, port)
    try:
        await client.write_cue_list(1, [CueStep.show_scene(fade_type=0, fade_seconds=0, hold_seconds=1)])
        big = {channel: channel % 256 for channel in range(1, 301)}
        await client.write_cue_scene(1, 1, big)
        assert await client.read_cue_scene(1, 1) == big

        small = {10: 1, 20: 2}
        await client.write_cue_scene(1, 1, small)
        assert await client.read_cue_scene(1, 1) == small
    finally:
        await client.close()


async def test_cue_scene_read_terminates_with_sparse_channels(simulator):
    host, port, state = simulator
    client = await _client(host, port)
    try:
        await client.write_cue_list(1, [CueStep.show_scene(fade_type=0, fade_seconds=0, hold_seconds=1)])
        sparse = {channel: 7 for channel in range(1, 3001, 10)}  # 300 values, spread out
        await client.write_cue_scene(1, 1, sparse)
        assert await asyncio.wait_for(client.read_cue_scene(1, 1), timeout=5) == sparse
    finally:
        await client.close()


async def test_directory_paging_with_sparse_cue_list_numbers(simulator):
    host, port, state = simulator
    client = await _client(host, port)
    try:
        numbers = list(range(3, 300, 3))  # 99 lists, numbers well above 80
        for number in numbers:
            state.cue_lists[number] = [CueStep.hold(1.0)]
        directory = await client.get_cue_list_directory()
        assert [info.number for info in directory] == numbers
    finally:
        await client.close()


# --- Network failures become LanBoxErrors (catchable by the screens) ---


async def _serve(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()[:2]
    return server, host, port


async def _accept_password(reader, writer):
    while (await reader.read(1)) not in (b"\r", b""):
        pass
    writer.write(b">")
    await writer.drain()


async def test_silent_lanbox_times_out_instead_of_hanging():
    async def handler(reader, writer):
        await _accept_password(reader, writer)
        await reader.read()  # never answers a command; return once the client hangs up

    server, host, port = await _serve(handler)
    async with server:
        client = LanBoxClient(TcpTransport(host, port), timeout=0.3)
        await client.connect()
        with pytest.raises(ReplyTimeoutError):
            await client.get_app_id()
        assert client.connected is False
        await client.close()


async def test_connect_times_out_without_a_password_reply():
    async def handler(reader, writer):
        await reader.read()  # never sends the password reply

    server, host, port = await _serve(handler)
    async with server:
        client = LanBoxClient(TcpTransport(host, port), timeout=0.3)
        with pytest.raises(ReplyTimeoutError):
            await client.connect()
        await client.close()


async def test_connection_reset_becomes_connection_lost():
    async def handler(reader, writer):
        await _accept_password(reader, writer)
        await reader.read(1)  # first byte of the next command
        sock = writer.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        writer.close()  # RST, like a rebooting LanBox

    server, host, port = await _serve(handler)
    async with server:
        client = LanBoxClient(TcpTransport(host, port), timeout=2)
        await client.connect()
        with pytest.raises(ConnectionLostError):
            await client.get_app_id()
        assert client.connected is False
        await client.close()


async def test_extra_replies_in_one_chunk_are_not_dropped():
    async def handler(reader, writer):
        await _accept_password(reader, writer)
        # answer two commands at once, as soon as the first one arrives
        await reader.readuntil(b"#")
        writer.write(b"*F8FD012D#>*5A0127000000000000000000#>")
        await writer.drain()
        await reader.read()

    server, host, port = await _serve(handler)
    async with server:
        client = LanBoxClient(TcpTransport(host, port), timeout=1)
        await client.connect()
        assert (await client.get_app_id()).device_name == "LCX"
        layers = await client.get_layers()  # answered by the queued second reply
        assert [layer.label for layer in layers] == ["A"]
        await client.close()
