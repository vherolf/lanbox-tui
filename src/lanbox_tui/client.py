"""Async client for talking to a LanBox (or the simulator) over any Transport.

The wire protocol is strictly half-duplex request/reply (the LanBox
processes one message at a time and always answers with a single reply),
so all requests are serialized through one lock - there is never more than
one in-flight command per connection.
"""

from __future__ import annotations

import asyncio

from lanbox_tui.protocol import commands, framing
from lanbox_tui.protocol.commands import (
    AppId,
    ChannelStatus,
    CueListInfo,
    LayerStatus,
    LayerSummary,
)
from lanbox_tui.protocol.cue_steps import CueStep
from lanbox_tui.protocol.errors import (
    AuthenticationError,
    ConnectionLostError,
    NotConnectedError,
    ReplyTimeoutError,
)
from lanbox_tui.protocol.framing import Reply, ReplyReader
from lanbox_tui.transport.base import Transport

DEFAULT_PASSWORD = "777"
DEFAULT_TIMEOUT_SECONDS = 5.0
_MAX_PAGES = 64  # hard stop for paging loops, in case a device's replies don't shrink


class LanBoxClient:
    def __init__(
        self,
        transport: Transport,
        password: str = DEFAULT_PASSWORD,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = transport
        self._password = password
        self._timeout = timeout
        self._reply_reader = ReplyReader()
        self._pending: list[Reply] = []
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        try:
            await asyncio.wait_for(self._transport.connect(), self._timeout)
            if self._transport.requires_auth:
                await asyncio.wait_for(
                    self._transport.write(framing.encode_password(self._password)), self._timeout
                )
                reply = await asyncio.wait_for(self._read_one_reply(), self._timeout)
                if not reply.ok:
                    await self._transport.close()
                    raise AuthenticationError("LanBox rejected the connection password")
        except asyncio.TimeoutError as exc:
            await self._drop()
            raise ReplyTimeoutError(f"no answer from the LanBox within {self._timeout:g}s") from exc
        self._connected = True

    async def close(self) -> None:
        await self._drop()

    async def _drop(self) -> None:
        self._connected = False
        self._pending.clear()
        self._reply_reader = ReplyReader()
        try:
            await self._transport.close()
        except OSError:
            pass

    async def _read_one_reply(self) -> Reply:
        while not self._pending:
            chunk = await self._transport.read()
            if not chunk:
                self._connected = False
                raise ConnectionLostError("connection closed by the LanBox")
            self._reply_reader.feed(chunk)
            self._pending.extend(self._reply_reader.pop_ready())
        return self._pending.pop(0)

    async def _request(self, request: bytes) -> Reply:
        if not self._connected:
            raise NotConnectedError("not connected")
        async with self._lock:
            try:
                await asyncio.wait_for(self._transport.write(request), self._timeout)
                return await asyncio.wait_for(self._read_one_reply(), self._timeout)
            except asyncio.TimeoutError as exc:
                # A late reply would be mistaken for the next command's answer,
                # so the session can't be trusted any more - drop it.
                await self._drop()
                raise ReplyTimeoutError(f"no answer from the LanBox within {self._timeout:g}s") from exc
            except OSError as exc:
                await self._drop()
                raise ConnectionLostError(f"connection lost: {exc}") from exc
            except ConnectionLostError:
                await self._drop()
                raise

    # --- Typed command methods (see protocol/commands.py for the wire format) ---

    async def get_app_id(self) -> AppId:
        return commands.parse_app_id(await self._request(commands.build_get_app_id()))

    async def set_16bit_mode(self, enabled: bool = True) -> None:
        reply = await self._request(commands.build_set_16bit_mode(enabled))
        commands.parse_set_16bit_mode(reply)

    async def get_layers(self) -> list[LayerSummary]:
        return commands.parse_get_layers(await self._request(commands.build_get_layers()))

    async def get_layer_status(self, layer_id: int) -> LayerStatus:
        reply = await self._request(commands.build_get_layer_status(layer_id))
        return commands.parse_get_layer_status(reply)

    async def read_channel_data(self, layer: int, start_channel: int, count: int) -> dict[int, int]:
        reply = await self._request(commands.build_read_channel_data(layer, start_channel, count))
        return commands.parse_read_channel_data(reply, start_channel=start_channel)

    async def read_channel_status(
        self, layer: int, start_channel: int, count: int
    ) -> dict[int, ChannelStatus]:
        reply = await self._request(commands.build_read_channel_status(layer, start_channel, count))
        return commands.parse_read_channel_status(reply, start_channel=start_channel)

    async def set_channel_data(self, layer: int, values: dict[int, int]) -> None:
        reply = await self._request(commands.build_set_channel_data(layer, values))
        commands.parse_set_channel_data(reply)

    async def set_channel_output_enable(self, layer: int, values: dict[int, bool]) -> None:
        reply = await self._request(commands.build_set_channel_output_enable(layer, values))
        commands.parse_set_channel_output_enable(reply)

    async def set_channel_active(self, layer: int, values: dict[int, bool]) -> None:
        reply = await self._request(commands.build_set_channel_active(layer, values))
        commands.parse_set_channel_active(reply)

    async def set_channel_solo(self, layer: int, values: dict[int, bool]) -> None:
        reply = await self._request(commands.build_set_channel_solo(layer, values))
        commands.parse_set_channel_solo(reply)

    # --- Layer Playback Control ---

    async def layer_go(self, layer: int, cue_list: int, cue_step: int | None = None) -> None:
        reply = await self._request(commands.build_layer_go(layer, cue_list, cue_step))
        commands.parse_layer_go(reply)

    async def layer_clear(self, layer: int) -> None:
        reply = await self._request(commands.build_layer_clear(layer))
        commands.parse_layer_clear(reply)

    async def layer_pause(self, layer: int) -> None:
        reply = await self._request(commands.build_layer_pause(layer))
        commands.parse_layer_pause(reply)

    async def layer_resume(self, layer: int) -> None:
        reply = await self._request(commands.build_layer_resume(layer))
        commands.parse_layer_resume(reply)

    async def layer_next_step(self, layer: int) -> None:
        reply = await self._request(commands.build_layer_next_step(layer))
        commands.parse_layer_next_step(reply)

    async def layer_previous_step(self, layer: int) -> None:
        reply = await self._request(commands.build_layer_previous_step(layer))
        commands.parse_layer_previous_step(reply)

    # --- Cue List Control ---

    async def get_cue_list_directory(self) -> list[CueListInfo]:
        # The chart calls the parameter a "Cue List Index" without saying
        # whether it's a position or a list number. Advancing by the page size
        # and de-duplicating is correct under either reading.
        by_number: dict[int, CueListInfo] = {}
        start = 1
        for _ in range(_MAX_PAGES):
            reply = await self._request(commands.build_get_cue_list_directory(start))
            page = commands.parse_get_cue_list_directory(reply)
            for info in page:
                by_number.setdefault(info.number, info)
            if len(page) < commands.MAX_CUE_LISTS_PER_DIRECTORY_PAGE:
                break
            start += commands.MAX_CUE_LISTS_PER_DIRECTORY_PAGE
        return [by_number[number] for number in sorted(by_number)]

    async def read_cue_list(self, cue_list: int) -> list[CueStep]:
        # Lists longer than 70 steps have to be read in several frames (p.39).
        frame = commands.MAX_CUE_STEPS_PER_FRAME
        steps: list[CueStep] = []
        start = 1
        while start <= commands.MAX_CUE_STEPS_PER_LIST:
            reply = await self._request(commands.build_read_cue_list(cue_list, start, frame))
            if start > 1 and not reply.ok:
                break  # asked past the end of a list that was exactly a frame long
            page = commands.parse_read_cue_list(reply)
            steps.extend(page)
            if len(page) < frame:
                break
            start += frame
        return steps

    async def write_cue_list(self, cue_list: int, steps: list[CueStep]) -> None:
        # First frame declares the total, continuation frames declare 0 (p.41).
        if not 1 <= len(steps) <= commands.MAX_CUE_STEPS_PER_LIST:
            raise ValueError(
                f"a Cue List holds 1-{commands.MAX_CUE_STEPS_PER_LIST} steps, got {len(steps)}"
            )
        frame = commands.MAX_CUE_STEPS_PER_FRAME
        for offset in range(0, len(steps), frame):
            declared = len(steps) if offset == 0 else 0
            request = commands.build_write_cue_list(
                cue_list, steps[offset : offset + frame], declared_count=declared
            )
            commands.parse_write_cue_list(await self._request(request))

    async def remove_cue_list(self, cue_list: int) -> None:
        reply = await self._request(commands.build_remove_cue_list(cue_list))
        commands.parse_remove_cue_list(reply)

    async def remove_cue_list_step(self, cue_list: int, cue_step: int) -> None:
        reply = await self._request(commands.build_remove_cue_list_step(cue_list, cue_step))
        commands.parse_remove_cue_list_step(reply)

    async def read_cue_scene(self, cue_list: int, cue_step: int) -> dict[int, int]:
        # The reply header is the scene's *total* value count, each reply holds
        # at most 250 values; page on with the next start channel (p.40).
        values: dict[int, int] = {}
        start_channel: int | None = None
        for _ in range(_MAX_PAGES):
            reply = await self._request(
                commands.build_read_cue_scene(cue_list, cue_step, start_channel)
            )
            page, total = commands.parse_read_cue_scene(reply)
            values.update(page)
            if not page or len(values) >= total:
                break
            next_start = max(page) + 1
            if start_channel is not None and next_start <= start_channel:
                break  # no progress - don't loop on a confused reply
            start_channel = next_start
        return values

    async def write_cue_scene(self, cue_list: int, cue_step: int, values: dict[int, int]) -> None:
        # First frame declares the total (replacing the scene), continuation
        # frames declare 0 (p.42).
        if not values:
            raise ValueError("a Cue Scene needs at least one channel value")
        items = list(values.items())
        frame = commands.MAX_CUE_SCENE_VALUES_PER_MESSAGE
        for offset in range(0, len(items), frame):
            declared = len(items) if offset == 0 else 0
            request = commands.build_write_cue_scene(
                cue_list, cue_step, dict(items[offset : offset + frame]), declared_count=declared
            )
            commands.parse_write_cue_scene(await self._request(request))

    # --- Layer Configuration & Chase/Fade Control ---

    async def set_layer_id(self, layer: int, new_id: int) -> None:
        reply = await self._request(commands.build_set_layer_id(layer, new_id))
        commands.parse_set_layer_id(reply)

    async def set_layer_output(self, layer: int, enabled: bool) -> None:
        reply = await self._request(commands.build_set_layer_output(layer, enabled))
        commands.parse_set_layer_output(reply)

    async def set_layer_fading(self, layer: int, enabled: bool) -> None:
        reply = await self._request(commands.build_set_layer_fading(layer, enabled))
        commands.parse_set_layer_fading(reply)

    async def set_layer_solo(self, layer: int, enabled: bool) -> None:
        reply = await self._request(commands.build_set_layer_solo(layer, enabled))
        commands.parse_set_layer_solo(reply)

    async def set_layer_auto_output(self, layer: int, enabled: bool) -> None:
        reply = await self._request(commands.build_set_layer_auto_output(layer, enabled))
        commands.parse_set_layer_auto_output(reply)

    async def set_layer_locked(self, layer: int, enabled: bool) -> None:
        reply = await self._request(commands.build_set_layer_locked(layer, enabled))
        commands.parse_set_layer_locked(reply)

    async def set_layer_mix_mode(self, layer: int, mode: int) -> None:
        reply = await self._request(commands.build_set_layer_mix_mode(layer, mode))
        commands.parse_set_layer_mix_mode(reply)

    async def set_layer_transparency_depth(self, layer: int, depth: int) -> None:
        reply = await self._request(commands.build_set_layer_transparency_depth(layer, depth))
        commands.parse_set_layer_transparency_depth(reply)

    async def set_layer_chase_mode(self, layer: int, mode: int) -> None:
        reply = await self._request(commands.build_set_layer_chase_mode(layer, mode))
        commands.parse_set_layer_chase_mode(reply)

    async def set_layer_chase_speed(self, layer: int, speed: int) -> None:
        reply = await self._request(commands.build_set_layer_chase_speed(layer, speed))
        commands.parse_set_layer_chase_speed(reply)

    async def set_layer_fade_type(self, layer: int, fade_type: int) -> None:
        reply = await self._request(commands.build_set_layer_fade_type(layer, fade_type))
        commands.parse_set_layer_fade_type(reply)

    async def set_layer_fade_time(self, layer: int, seconds: float) -> None:
        reply = await self._request(commands.build_set_layer_fade_time(layer, seconds))
        commands.parse_set_layer_fade_time(reply)

    async def create_layer(
        self,
        layer_id: int,
        *,
        attributes: int = commands.DEFAULT_NEW_LAYER_ATTRIBUTES,
        start_cue_list: int = 0,
        start_cue_step: int = 0,
        under: int | None = None,
    ) -> None:
        # LayerConfigure puts a new Layer directly *underneath* the source Layer,
        # or on top of the mixing order when there is none (p.24).
        source = under if under is not None else commands.LAYER_CONFIGURE_TOP_OF_MIXING_ORDER
        request = commands.build_layer_configure_long(
            commands.LAYER_CONFIGURE_NEW_OR_DELETE_MARKER,
            source,
            layer_id,
            attributes,
            start_cue_list,
            start_cue_step,
        )
        commands.parse_layer_configure(await self._request(request))

    async def delete_layer(self, layer: int) -> None:
        request = commands.build_layer_configure_short(layer, commands.LAYER_CONFIGURE_NEW_OR_DELETE_MARKER)
        commands.parse_layer_configure(await self._request(request))

    async def move_layer_above(self, destination: int, source: int) -> None:
        request = commands.build_layer_configure_short(destination, source)
        commands.parse_layer_configure(await self._request(request))

    # --- LanBox Global Settings ---

    async def get_global_data(self) -> commands.GlobalData:
        reply = await self._request(commands.build_get_global_data())
        return commands.parse_get_global_data(reply)

    async def set_name(self, name: str) -> None:
        reply = await self._request(commands.build_set_name(name))
        commands.parse_set_name(reply)

    async def set_password(self, password: int) -> None:
        reply = await self._request(commands.build_set_password(password))
        commands.parse_set_password(reply)

    async def set_dmx_offset(self, offset: int) -> None:
        reply = await self._request(commands.build_set_dmx_offset(offset))
        commands.parse_set_dmx_offset(reply)

    async def set_num_dmx_channels(self, count: int) -> None:
        reply = await self._request(commands.build_set_num_dmx_channels(count))
        commands.parse_set_num_dmx_channels(reply)

    async def set_ip_config(
        self,
        ip: tuple[int, int, int, int],
        subnet: tuple[int, int, int, int],
        gateway: tuple[int, int, int, int],
    ) -> None:
        reply = await self._request(commands.build_set_ip_config(ip, subnet, gateway))
        commands.parse_set_ip_config(reply)

    async def set_baud_rate(self, param: int) -> None:
        reply = await self._request(commands.build_set_baud_rate(param))
        commands.parse_set_baud_rate(reply)

    async def reboot(self) -> None:
        reply = await self._request(commands.build_reboot())
        commands.parse_reboot(reply)

    async def save_data(self) -> None:
        reply = await self._request(commands.build_save_data())
        commands.parse_save_data(reply)
