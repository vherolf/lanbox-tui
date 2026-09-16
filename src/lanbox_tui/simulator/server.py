"""Asyncio TCP server that speaks the LanBox wire protocol.

Lets the TUI (and tests) run against `localhost` instead of real hardware.
Reuses `lanbox_tui.protocol.framing` for encoding so the wire format can't
drift between the "real" client and this fake server.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from lanbox_tui.protocol import framing
from lanbox_tui.protocol.cue_steps import CueStep
from lanbox_tui.simulator.state import LanBoxState, SimulatedLayer

logger = logging.getLogger(__name__)

DEFAULT_PORT = 1777  # non-privileged default so `lanbox-simulator` needs no sudo


class RequestReader:
    """Server-side mirror of `ReplyReader`: extracts '*<body>#' request frames.

    Per spec, receiving '*' always resets the input buffer and receiving '#'
    always completes+resets it, so malformed/partial junk in between is
    simply discarded rather than raising.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[str]:
        bodies: list[str] = []
        for byte in chunk:
            if byte == framing.START:
                self._buffer.clear()
            elif byte == framing.END:
                bodies.append(self._buffer.decode("ascii", errors="replace"))
                self._buffer.clear()
            else:
                self._buffer.append(byte)
        return bodies


def _hex_pairs(hex_str: str, chars_per_item: int) -> list[str]:
    return [hex_str[i : i + chars_per_item] for i in range(0, len(hex_str), chars_per_item)]


def _handle_get_app_id(params: str, state: LanBoxState) -> str:
    firmware_raw = round(state.firmware_version * 100)
    return framing.hex16(state.device_code) + framing.hex16(firmware_raw)


def _handle_set_16bit_mode(params: str, state: LanBoxState) -> None:
    mode = framing.parse_hex(params)
    state.sixteen_bit_mode = mode > 0


def _handle_get_layers(params: str, state: LanBoxState) -> str:
    parts = []
    for layer in state.layers_in_mixing_order():
        parts.append(framing.hex8(layer.internal_number))
        parts.append(framing.hex8(layer.layer_id))
        parts.append(framing.hex8(layer.attributes_byte()))
        parts.append(framing.hex16(layer.active_cue_list))
        parts.append(framing.hex8(layer.active_cue_step))
        parts.append(framing.hex8(0))  # fade time code
        parts.append(framing.hex16(0))  # fade remaining frames
        parts.append(framing.hex8(0))  # hold time code
        parts.append(framing.hex16(0))  # hold remaining frames
    return "".join(parts)


def _require_layer(state: LanBoxState, layer_id: int) -> SimulatedLayer:
    layer = state.layers.get(layer_id)
    if layer is None:
        raise ValueError(f"no such layer: {layer_id}")
    return layer


def _handle_get_layer_status(params: str, state: LanBoxState) -> str:
    layer_id = framing.parse_hex(params)
    layer = _require_layer(state, layer_id)
    fields = [
        framing.hex8(0xFF if layer.output_enabled else 0x00),
        framing.hex8(0xFF if layer.edit_run_mode else 0x00),
        framing.hex8(0xFF if layer.fading_enabled else 0x00),
        framing.hex8(0xFF if layer.solo_mode else 0x00),
        framing.hex8(layer.mix_mode),
        framing.hex8(0),  # reserved
        framing.hex8(0),  # hold time code
        framing.hex16(0),  # hold remaining frames
        framing.hex16(layer.active_cue_list),
        framing.hex8(layer.active_cue_step),
        framing.hex8(layer.chase_mode),
        framing.hex8(layer.chase_speed),
        framing.hex8(layer.fade_type),
        framing.hex8(layer.fade_time_code),
        framing.hex8(0),  # cue step fade time code
        framing.hex16(0),  # fade remaining frames
        framing.hex8(layer.transparency_depth),
        framing.hex8(0),  # loading indication
        framing.hex8(0xFF if layer.paused else 0x00),
        framing.hex8(0),  # sysex device id
        framing.hex8(0xFF if layer.auto_activate else 0x00),
        framing.hex8(0),  # cue step type
        framing.hex8(0),
        framing.hex8(0),
        framing.hex8(0),
        framing.hex8(0),
        framing.hex8(0),
        framing.hex8(0),
        framing.hex8(0),  # reserved
    ]
    return "".join(fields)


def _handle_read_channel_data(params: str, state: LanBoxState) -> str:
    layer_id = framing.parse_hex(params[0:2])
    start_channel = framing.parse_hex(params[2:6])
    count = framing.parse_hex(params[6:8])
    layer = _require_layer(state, layer_id)
    return "".join(
        framing.hex8(layer.channel(start_channel + i).value) for i in range(count)
    )


def _handle_read_channel_status(params: str, state: LanBoxState) -> str:
    layer_id = framing.parse_hex(params[0:2])
    start_channel = framing.parse_hex(params[2:6])
    count = framing.parse_hex(params[6:8])
    layer = _require_layer(state, layer_id)
    return "".join(
        framing.hex8(layer.channel(start_channel + i).status_byte()) for i in range(count)
    )


def _handle_set_channel_data(params: str, state: LanBoxState) -> None:
    layer_id = framing.parse_hex(params[0:2])
    layer = _require_layer(state, layer_id)
    for pair in _hex_pairs(params[2:], 6):
        channel_number = framing.parse_hex(pair[0:4])
        value = framing.parse_hex(pair[4:6])
        channel = layer.channel(channel_number)
        channel.value = value
        channel.output_to_mixer = True  # auto-activate default (LayerSetAutoOutput)


def _set_channel_bool_map(params: str, state: LanBoxState, attr: str) -> None:
    layer_id = framing.parse_hex(params[0:2])
    layer = _require_layer(state, layer_id)
    for pair in _hex_pairs(params[2:], 6):
        channel_number = framing.parse_hex(pair[0:4])
        enabled = framing.parse_hex(pair[4:6]) > 0
        if channel_number == 0:
            for channel in layer.channels.values():
                setattr(channel, attr, enabled)
        else:
            setattr(layer.channel(channel_number), attr, enabled)


def _handle_set_channel_output_enable(params: str, state: LanBoxState) -> None:
    _set_channel_bool_map(params, state, "output_to_mixer")


def _handle_set_channel_active(params: str, state: LanBoxState) -> None:
    # Table 3's bit1 ("Channel edit enabled") is the closest documented match
    # for ChannelSetActive's "Active Status Attribute" - the reference chart
    # doesn't explicitly cross-reference the two, but the Channel Control
    # section's own description of "activating" a Channel lines up with it.
    _set_channel_bool_map(params, state, "edit_enabled")


def _handle_set_channel_solo(params: str, state: LanBoxState) -> None:
    _set_channel_bool_map(params, state, "solo_mode")


def _handle_layer_go(params: str, state: LanBoxState) -> None:
    layer_id = framing.parse_hex(params[0:2])
    cue_list = framing.parse_hex(params[2:6])
    cue_step = framing.parse_hex(params[6:8]) if len(params) > 6 else 1
    layer = _require_layer(state, layer_id)
    if cue_list == 0:
        # Cue List 0 resets the Layer per spec; the simulator only tracks
        # cue-position state, so just clear that.
        layer.active_cue_list = 0
        layer.active_cue_step = 0
        return
    layer.paused = False
    state.apply_cue_step(layer, cue_list, cue_step)


def _handle_layer_clear(params: str, state: LanBoxState) -> None:
    layer = _require_layer(state, framing.parse_hex(params))
    layer.channels.clear()


def _handle_layer_pause(params: str, state: LanBoxState) -> None:
    _require_layer(state, framing.parse_hex(params)).paused = True


def _handle_layer_resume(params: str, state: LanBoxState) -> None:
    _require_layer(state, framing.parse_hex(params)).paused = False


def _handle_layer_next_step(params: str, state: LanBoxState) -> None:
    layer = _require_layer(state, framing.parse_hex(params))
    if layer.active_cue_list:
        state.apply_cue_step(layer, layer.active_cue_list, layer.active_cue_step + 1)


def _handle_layer_previous_step(params: str, state: LanBoxState) -> None:
    layer = _require_layer(state, framing.parse_hex(params))
    if layer.active_cue_list:
        state.apply_cue_step(layer, layer.active_cue_list, layer.active_cue_step - 1)


def _handle_cue_list_get_directory(params: str, state: LanBoxState) -> str:
    start_index = framing.parse_hex(params)
    numbers = sorted(number for number in state.cue_lists if number >= start_index)
    parts = []
    for number in numbers[:80]:
        parts.append(framing.hex16(number))
        parts.append(framing.hex8(len(state.cue_lists[number])))
    return "".join(parts)


def _handle_remove_cue_list(params: str, state: LanBoxState) -> None:
    cue_list = framing.parse_hex(params)
    state.cue_lists.pop(cue_list, None)
    for key in [k for k in state.cue_scenes if k[0] == cue_list]:
        del state.cue_scenes[key]


def _handle_remove_cue_list_step(params: str, state: LanBoxState) -> None:
    cue_list = framing.parse_hex(params[0:4])
    cue_step = framing.parse_hex(params[4:6])
    steps = state.cue_lists.get(cue_list)
    if not steps or not (1 <= cue_step <= len(steps)):
        raise ValueError("no such cue step")
    del steps[cue_step - 1]
    # Re-index scene data to follow the steps that shifted down; drop the
    # removed step's own scene.
    old_scenes = {k: v for k, v in state.cue_scenes.items() if k[0] == cue_list}
    for key in old_scenes:
        del state.cue_scenes[key]
    for (list_id, step_index), scene in sorted(old_scenes.items()):
        if step_index < cue_step:
            state.cue_scenes[(list_id, step_index)] = scene
        elif step_index > cue_step:
            state.cue_scenes[(list_id, step_index - 1)] = scene


def _handle_read_cue_list(params: str, state: LanBoxState) -> str:
    cue_list = framing.parse_hex(params[0:4])
    start_step = framing.parse_hex(params[4:6])
    count = framing.parse_hex(params[6:8])
    steps = state.cue_lists.get(cue_list)
    if steps is None:
        raise ValueError(f"no such cue list: {cue_list}")
    selected = steps[start_step - 1 :] if count == 0 else steps[start_step - 1 : start_step - 1 + count]
    return "".join(step.to_hex() for step in selected)


def _handle_write_cue_list(params: str, state: LanBoxState) -> None:
    cue_list = framing.parse_hex(params[0:4])
    count = framing.parse_hex(params[4:6])
    body = params[6:]
    steps = [CueStep.from_hex(body[i : i + 14]) for i in range(0, count * 14, 14)]
    state.cue_lists[cue_list] = steps
    for key in [k for k in state.cue_scenes if k[0] == cue_list and k[1] > len(steps)]:
        del state.cue_scenes[key]


def _handle_read_cue_scene(params: str, state: LanBoxState) -> str:
    cue_list = framing.parse_hex(params[0:4])
    cue_step = framing.parse_hex(params[4:6])
    start_channel = framing.parse_hex(params[6:10]) if len(params) > 6 else 1
    scene = state.cue_scenes.get((cue_list, cue_step), {})
    channels = sorted(channel for channel in scene if channel >= start_channel)
    page = channels[:250]
    parts = [framing.hex8(0), framing.hex16(len(page))]
    for channel in page:
        parts.append(framing.hex16(channel))
        parts.append(framing.hex8(scene[channel]))
    return "".join(parts)


def _handle_write_cue_scene(params: str, state: LanBoxState) -> None:
    cue_list = framing.parse_hex(params[0:4])
    cue_step = framing.parse_hex(params[4:6])
    # params[6:8] is the always-zero Cue Scene Flag - ignored.
    count = framing.parse_hex(params[8:12])
    body = params[12:]
    scene = state.cue_scenes.setdefault((cue_list, cue_step), {})
    for pair in _hex_pairs(body, 6)[:count]:
        channel = framing.parse_hex(pair[0:4])
        value = framing.parse_hex(pair[4:6])
        scene[channel] = value


def _set_layer_bool(params: str, state: LanBoxState, attr: str) -> None:
    layer = _require_layer(state, framing.parse_hex(params[0:2]))
    setattr(layer, attr, framing.parse_hex(params[2:4]) > 0)


def _set_layer_value(params: str, state: LanBoxState, attr: str) -> None:
    layer = _require_layer(state, framing.parse_hex(params[0:2]))
    setattr(layer, attr, framing.parse_hex(params[2:4]))


def _handle_set_layer_id(params: str, state: LanBoxState) -> None:
    layer_id = framing.parse_hex(params[0:2])
    new_id = framing.parse_hex(params[2:4])
    _require_layer(state, layer_id)
    state.rename_layer(layer_id, new_id)


def _handle_set_layer_output(params: str, state: LanBoxState) -> None:
    _set_layer_bool(params, state, "output_enabled")


def _handle_set_layer_fading(params: str, state: LanBoxState) -> None:
    _set_layer_bool(params, state, "fading_enabled")


def _handle_set_layer_solo(params: str, state: LanBoxState) -> None:
    _set_layer_bool(params, state, "solo_mode")


def _handle_set_layer_auto_output(params: str, state: LanBoxState) -> None:
    _set_layer_bool(params, state, "auto_activate")


def _handle_set_layer_locked(params: str, state: LanBoxState) -> None:
    _set_layer_bool(params, state, "locked")


def _handle_set_layer_mix_mode(params: str, state: LanBoxState) -> None:
    _set_layer_value(params, state, "mix_mode")


def _handle_set_layer_transparency_depth(params: str, state: LanBoxState) -> None:
    _set_layer_value(params, state, "transparency_depth")


def _handle_set_layer_chase_mode(params: str, state: LanBoxState) -> None:
    _set_layer_value(params, state, "chase_mode")


def _handle_set_layer_chase_speed(params: str, state: LanBoxState) -> None:
    _set_layer_value(params, state, "chase_speed")


def _handle_set_layer_fade_type(params: str, state: LanBoxState) -> None:
    _set_layer_value(params, state, "fade_type")


def _handle_set_layer_fade_time(params: str, state: LanBoxState) -> None:
    _set_layer_value(params, state, "fade_time_code")


def _handle_layer_configure(params: str, state: LanBoxState) -> None:
    destination = framing.parse_hex(params[0:2])
    source = framing.parse_hex(params[2:4])
    if len(params) > 4:
        layer_id = framing.parse_hex(params[4:6])
        attributes = framing.parse_hex(params[6:8])
        start_cue_list = framing.parse_hex(params[8:12])
        start_cue_step = framing.parse_hex(params[12:14])
        state.configure_layer(
            destination,
            source,
            layer_id=layer_id,
            attributes=attributes,
            start_cue_list=start_cue_list,
            start_cue_step=start_cue_step,
        )
    else:
        state.configure_layer(destination, source)


_HANDLERS = {
    # CommonGetAppID is the odd one out with a 4-hex-char code ("0005"); every
    # other v1 command uses 2. Sorted longest-first so dispatch() can match
    # unambiguously by trying longer codes before shorter ones.
    "0005": _handle_get_app_id,
    "65": _handle_set_16bit_mode,
    "B1": _handle_get_layers,
    "0A": _handle_get_layer_status,
    "CD": _handle_read_channel_data,
    "CE": _handle_read_channel_status,
    "C9": _handle_set_channel_data,
    "CA": _handle_set_channel_output_enable,
    "CC": _handle_set_channel_active,
    "CB": _handle_set_channel_solo,
    "56": _handle_layer_go,
    "57": _handle_layer_clear,
    "58": _handle_layer_pause,
    "59": _handle_layer_resume,
    "5A": _handle_layer_next_step,
    "5B": _handle_layer_previous_step,
    "A7": _handle_cue_list_get_directory,
    "60": _handle_remove_cue_list,
    "62": _handle_remove_cue_list_step,
    "AB": _handle_read_cue_list,
    "AA": _handle_write_cue_list,
    "AD": _handle_read_cue_scene,
    "AC": _handle_write_cue_scene,
    "45": _handle_set_layer_id,
    "48": _handle_set_layer_output,
    "46": _handle_set_layer_fading,
    "4A": _handle_set_layer_solo,
    "64": _handle_set_layer_auto_output,
    "43": _handle_set_layer_locked,
    "47": _handle_set_layer_mix_mode,
    "63": _handle_set_layer_transparency_depth,
    "4B": _handle_set_layer_chase_mode,
    "4C": _handle_set_layer_chase_speed,
    "4D": _handle_set_layer_fade_type,
    "4E": _handle_set_layer_fade_time,
    "44": _handle_layer_configure,
}
_HANDLER_CODES_BY_LENGTH_DESC = sorted(_HANDLERS, key=len, reverse=True)


def dispatch(body: str, state: LanBoxState) -> bytes:
    code = next((c for c in _HANDLER_CODES_BY_LENGTH_DESC if body.startswith(c)), None)
    if code is None:
        logger.warning("unknown command in request: %r", body)
        return bytes([framing.PROMPT_ERROR])
    handler = _HANDLERS[code]
    params = body[len(code) :]
    try:
        data = handler(params, state)
    except Exception:
        logger.exception("command %r failed", code)
        return bytes([framing.PROMPT_ERROR])
    if data is None:
        return bytes([framing.PROMPT_OK])
    return b"*" + data.encode("ascii") + b"#" + bytes([framing.PROMPT_OK])


async def _read_password_line(reader: asyncio.StreamReader) -> str | None:
    buffer = bytearray()
    while True:
        byte = await reader.read(1)
        if not byte:
            return None
        if byte == b"\r":
            return buffer.decode("ascii", errors="replace")
        buffer.extend(byte)


def make_connection_handler(state: LanBoxState):
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        logger.info("connection from %s", peer)
        try:
            password = await _read_password_line(reader)
            if password is None:
                return
            if password != state.password:
                writer.write(bytes([framing.PROMPT_ERROR]))
                await writer.drain()
                return
            writer.write(bytes([framing.PROMPT_OK]))
            await writer.drain()

            request_reader = RequestReader()
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                for body in request_reader.feed(chunk):
                    writer.write(dispatch(body, state))
                    await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            logger.info("connection from %s closed", peer)

    return handle_client


async def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, state: LanBoxState | None = None) -> None:
    state = state or LanBoxState()
    server = await asyncio.start_server(make_connection_handler(state), host, port)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    logger.info("LanBox simulator listening on %s (password=%r)", addrs, state.password)
    async with server:
        await server.serve_forever()


def run() -> None:
    parser = argparse.ArgumentParser(description="Fake LanBox TCP server for development/testing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--password", default="777")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(serve(args.host, args.port, LanBoxState(password=args.password)))


if __name__ == "__main__":
    run()
