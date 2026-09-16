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
from lanbox_tui.protocol.errors import AuthenticationError, NotConnectedError
from lanbox_tui.protocol.framing import Reply, ReplyReader
from lanbox_tui.transport.base import Transport

DEFAULT_PASSWORD = "777"


class LanBoxClient:
    def __init__(self, transport: Transport, password: str = DEFAULT_PASSWORD) -> None:
        self._transport = transport
        self._password = password
        self._reply_reader = ReplyReader()
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        await self._transport.connect()
        await self._transport.write(framing.encode_password(self._password))
        reply = await self._read_one_reply()
        if not reply.ok:
            await self._transport.close()
            raise AuthenticationError("LanBox rejected the connection password")
        self._connected = True

    async def close(self) -> None:
        self._connected = False
        await self._transport.close()

    async def _read_one_reply(self) -> Reply:
        while True:
            ready = self._reply_reader.pop_ready()
            if ready:
                return ready[0]
            chunk = await self._transport.read()
            if not chunk:
                self._connected = False
                raise NotConnectedError("connection closed by peer")
            self._reply_reader.feed(chunk)

    async def _request(self, request: bytes) -> Reply:
        if not self._connected:
            raise NotConnectedError("not connected - call connect() first")
        async with self._lock:
            await self._transport.write(request)
            return await self._read_one_reply()

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
        infos: list[CueListInfo] = []
        start = 1
        while True:
            reply = await self._request(commands.build_get_cue_list_directory(start))
            page = commands.parse_get_cue_list_directory(reply)
            if not page:
                break
            infos.extend(page)
            if len(page) < 80:
                break
            start = page[-1].number + 1
        return infos

    async def read_cue_list(self, cue_list: int) -> list[CueStep]:
        reply = await self._request(commands.build_read_cue_list(cue_list))
        return commands.parse_read_cue_list(reply)

    async def write_cue_list(self, cue_list: int, steps: list[CueStep]) -> None:
        reply = await self._request(commands.build_write_cue_list(cue_list, steps))
        commands.parse_write_cue_list(reply)

    async def remove_cue_list(self, cue_list: int) -> None:
        reply = await self._request(commands.build_remove_cue_list(cue_list))
        commands.parse_remove_cue_list(reply)

    async def remove_cue_list_step(self, cue_list: int, cue_step: int) -> None:
        reply = await self._request(commands.build_remove_cue_list_step(cue_list, cue_step))
        commands.parse_remove_cue_list_step(reply)

    async def read_cue_scene(self, cue_list: int, cue_step: int) -> dict[int, int]:
        values: dict[int, int] = {}
        start_channel: int | None = None
        while True:
            reply = await self._request(
                commands.build_read_cue_scene(cue_list, cue_step, start_channel)
            )
            page, count = commands.parse_read_cue_scene(reply)
            values.update(page)
            if count < commands.MAX_CUE_SCENE_VALUES_PER_MESSAGE:
                break
            start_channel = (start_channel or 1) + commands.MAX_CUE_SCENE_VALUES_PER_MESSAGE
        return values

    async def write_cue_scene(self, cue_list: int, cue_step: int, values: dict[int, int]) -> None:
        items = list(values.items())
        chunk_size = commands.MAX_CUE_SCENE_VALUES_PER_MESSAGE
        for i in range(0, len(items), chunk_size):
            chunk = dict(items[i : i + chunk_size])
            reply = await self._request(commands.build_write_cue_scene(cue_list, cue_step, chunk))
            commands.parse_write_cue_scene(reply)

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
        above: int | None = None,
    ) -> None:
        source = above if above is not None else commands.LAYER_CONFIGURE_TOP_OF_MIXING_ORDER
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
