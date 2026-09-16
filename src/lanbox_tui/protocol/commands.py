"""Typed request builders and reply parsers for the v1 LanBox command subset.

Every function pair mirrors one command from "LanBox Reference Chart 3.04":

    CommonGetAppID (#05), Common16BitMode (#65), CommonGetLayers (#B1),
    LayerGetStatus (#0A), ChannelReadData (#CD), ChannelReadStatus (#CE),
    ChannelSetData (#C9), ChannelSetOutputEnable (#CA)

`build_*` functions return the raw request bytes to send. `parse_*`
functions take the `Reply` received back and return a typed result,
raising `CommandRejected` if the LanBox returned '?'.
"""

from __future__ import annotations

from dataclasses import dataclass

from lanbox_tui.protocol import framing
from lanbox_tui.protocol.cue_steps import CueStep, encode_cue_time
from lanbox_tui.protocol.errors import CommandRejected
from lanbox_tui.protocol.framing import Reply, hex8, hex16, layer_id_to_label, read_fields

# LanBox buffer IDs usable in place of a Layer ID for channel commands (Table 2, LCX/LCE).
BUFFER_MIXER = 0xFE
BUFFER_DMX_OUT = 0xFF
BUFFER_DMX_IN = 0xFC
BUFFER_EXTERNAL_INPUTS = 0xFD

DEVICE_NAMES = {
    0xF8FB: "LC+",
    0xF8FD: "LCX",
    0xF8FF: "LXM",
    0xF901: "LCE",
}


def _require_ok(reply: Reply, *, command: str) -> None:
    if not reply.ok:
        raise CommandRejected(f"LanBox rejected {command}")


# --- CommonGetAppID (#05) ---------------------------------------------------


@dataclass(frozen=True)
class AppId:
    device_code: int  # e.g. 0xF8FD
    device_name: str  # e.g. "LCX", or "unknown" if not in DEVICE_NAMES
    firmware_version: float  # e.g. 2.11


def build_get_app_id() -> bytes:
    # Unlike almost every other command, CommonGetAppID is documented with a
    # 4-hex-char command code ("0005", not "05") - see the reference chart's
    # worked example: "* 0005 00 00 #".
    return framing.encode_request("0005", hex8(0), hex8(0))


def parse_app_id(reply: Reply) -> AppId:
    _require_ok(reply, command="CommonGetAppID")
    assert reply.data is not None
    fields, _ = read_fields(reply.data, [("device_code", 2), ("firmware_raw", 2)])
    device_code = fields["device_code"]
    return AppId(
        device_code=device_code,
        device_name=DEVICE_NAMES.get(device_code, "unknown"),
        firmware_version=fields["firmware_raw"] / 100,
    )


# --- Common16BitMode (#65) --------------------------------------------------


def build_set_16bit_mode(enabled: bool) -> bytes:
    return framing.encode_request("65", hex8(0xFF if enabled else 0x00))


def parse_set_16bit_mode(reply: Reply) -> None:
    _require_ok(reply, command="Common16BitMode")


# --- CommonGetLayers (#B1) --------------------------------------------------

_LAYER_ATTRIBUTE_FIELDS = (
    ("output_enabled", 0x01),
    ("edit_run_mode", 0x02),
    ("fading_enabled", 0x04),
    ("solo_mode", 0x08),
    ("paused", 0x10),
    ("auto_activate", 0x20),
    ("sequencer_waiting", 0x40),
    ("locked", 0x80),
)


@dataclass(frozen=True)
class LayerAttributes:
    raw: int
    output_enabled: bool
    edit_run_mode: bool
    fading_enabled: bool
    solo_mode: bool
    paused: bool
    auto_activate: bool
    sequencer_waiting: bool
    locked: bool

    @classmethod
    def from_byte(cls, raw: int) -> "LayerAttributes":
        flags = {name: bool(raw & mask) for name, mask in _LAYER_ATTRIBUTE_FIELDS}
        return cls(raw=raw, **flags)


@dataclass(frozen=True)
class LayerSummary:
    internal_number: int
    layer_id: int
    label: str
    attributes: LayerAttributes
    active_cue_list: int
    active_cue_step: int
    fade_time_code: int
    fade_remaining_frames: int
    hold_time_code: int
    hold_remaining_frames: int


_LAYER_SUMMARY_SPEC = [
    ("internal_number", 1),
    ("layer_id", 1),
    ("attributes", 1),
    ("active_cue_list", 2),
    ("active_cue_step", 1),
    ("fade_time_code", 1),
    ("fade_remaining_frames", 2),
    ("hold_time_code", 1),
    ("hold_remaining_frames", 2),
]


def build_get_layers() -> bytes:
    return framing.encode_request("B1")


def parse_get_layers(reply: Reply) -> list[LayerSummary]:
    _require_ok(reply, command="CommonGetLayers")
    remaining = reply.data or ""
    layers: list[LayerSummary] = []
    while remaining:
        fields, remaining = read_fields(remaining, _LAYER_SUMMARY_SPEC)
        layers.append(
            LayerSummary(
                internal_number=fields["internal_number"],
                layer_id=fields["layer_id"],
                label=layer_id_to_label(fields["layer_id"]),
                attributes=LayerAttributes.from_byte(fields["attributes"]),
                active_cue_list=fields["active_cue_list"],
                active_cue_step=fields["active_cue_step"],
                fade_time_code=fields["fade_time_code"],
                fade_remaining_frames=fields["fade_remaining_frames"],
                hold_time_code=fields["hold_time_code"],
                hold_remaining_frames=fields["hold_remaining_frames"],
            )
        )
    return layers


# --- LayerGetStatus (#0A) ---------------------------------------------------

_LAYER_STATUS_SPEC = [
    ("output_status", 1),
    ("sequence_status", 1),
    ("fade_status", 1),
    ("solo_status", 1),
    ("mix_status", 1),
    ("_reserved1", 1),
    ("hold_time_code", 1),
    ("hold_remaining_frames", 2),
    ("active_cue_list", 2),
    ("active_cue_step", 1),
    ("chase_mode", 1),
    ("layer_speed", 1),
    ("manual_fade_type", 1),
    ("manual_fade_time_code", 1),
    ("cue_step_fade_time_code", 1),
    ("fade_remaining_frames", 2),
    ("transparency_depth", 1),
    ("loading_indication", 1),
    ("pause_status", 1),
    ("sysex_device_id", 1),
    ("auto_activate_status", 1),
    ("cue_step_type", 1),
    ("step_param_1", 1),
    ("step_param_2", 1),
    ("step_param_3", 1),
    ("step_param_4", 1),
    ("step_param_5", 1),
    ("step_param_6", 1),
    ("_reserved2", 1),
]


@dataclass(frozen=True)
class LayerStatus:
    output_status: bool
    sequence_status: bool
    fade_status: bool
    solo_status: bool
    mix_status: int
    active_cue_list: int
    active_cue_step: int
    chase_mode: int
    layer_speed_percent: int
    manual_fade_type: int
    manual_fade_time_code: int
    transparency_depth_percent: int
    pause_status: bool
    auto_activate_status: bool


def build_get_layer_status(layer_id: int) -> bytes:
    return framing.encode_request("0A", hex8(layer_id))


def parse_get_layer_status(reply: Reply) -> LayerStatus:
    _require_ok(reply, command="LayerGetStatus")
    assert reply.data is not None
    fields, _ = read_fields(reply.data, _LAYER_STATUS_SPEC)
    return LayerStatus(
        output_status=bool(fields["output_status"]),
        sequence_status=bool(fields["sequence_status"]),
        fade_status=bool(fields["fade_status"]),
        solo_status=bool(fields["solo_status"]),
        mix_status=fields["mix_status"],
        active_cue_list=fields["active_cue_list"],
        active_cue_step=fields["active_cue_step"],
        chase_mode=fields["chase_mode"],
        layer_speed_percent=fields["layer_speed"],
        manual_fade_type=fields["manual_fade_type"],
        manual_fade_time_code=fields["manual_fade_time_code"],
        transparency_depth_percent=fields["transparency_depth"],
        pause_status=bool(fields["pause_status"]),
        auto_activate_status=bool(fields["auto_activate_status"]),
    )


# --- ChannelReadData (#CD) --------------------------------------------------


def build_read_channel_data(layer: int, start_channel: int, count: int) -> bytes:
    return framing.encode_request("CD", hex8(layer), hex16(start_channel), hex8(count))


def parse_read_channel_data(reply: Reply, *, start_channel: int) -> dict[int, int]:
    _require_ok(reply, command="ChannelReadData")
    data = reply.data or ""
    values: dict[int, int] = {}
    for i in range(0, len(data), 2):
        channel = start_channel + i // 2
        values[channel] = framing.parse_hex(data[i : i + 2])
    return values


# --- ChannelReadStatus (#CE) ------------------------------------------------

_CHANNEL_STATUS_FIELDS = (
    ("output_to_mixer", 0x01),
    ("edit_enabled", 0x02),
    ("solo_mode", 0x04),
    ("fading", 0x08),
)


@dataclass(frozen=True)
class ChannelStatus:
    raw: int
    output_to_mixer: bool
    edit_enabled: bool
    solo_mode: bool
    fading: bool

    @classmethod
    def from_byte(cls, raw: int) -> "ChannelStatus":
        flags = {name: bool(raw & mask) for name, mask in _CHANNEL_STATUS_FIELDS}
        return cls(raw=raw, **flags)


def build_read_channel_status(layer: int, start_channel: int, count: int) -> bytes:
    return framing.encode_request("CE", hex8(layer), hex16(start_channel), hex8(count))


def parse_read_channel_status(reply: Reply, *, start_channel: int) -> dict[int, ChannelStatus]:
    _require_ok(reply, command="ChannelReadStatus")
    data = reply.data or ""
    values: dict[int, ChannelStatus] = {}
    for i in range(0, len(data), 2):
        channel = start_channel + i // 2
        values[channel] = ChannelStatus.from_byte(framing.parse_hex(data[i : i + 2]))
    return values


# --- ChannelSetData (#C9) ---------------------------------------------------


def build_set_channel_data(layer: int, values: dict[int, int]) -> bytes:
    parts = [hex8(layer)]
    for channel, value in values.items():
        parts.append(hex16(channel))
        parts.append(hex8(value))
    return framing.encode_request("C9", *parts)


def parse_set_channel_data(reply: Reply) -> None:
    _require_ok(reply, command="ChannelSetData")


# --- ChannelSetOutputEnable (#CA) -------------------------------------------


def _build_channel_bool_map(code: str, layer: int, values: dict[int, bool]) -> bytes:
    parts = [hex8(layer)]
    for channel, enabled in values.items():
        parts.append(hex16(channel))
        parts.append(hex8(0xFF if enabled else 0x00))
    return framing.encode_request(code, *parts)


def build_set_channel_output_enable(layer: int, values: dict[int, bool]) -> bytes:
    return _build_channel_bool_map("CA", layer, values)


def parse_set_channel_output_enable(reply: Reply) -> None:
    _require_ok(reply, command="ChannelSetOutputEnable")


def build_set_channel_active(layer: int, values: dict[int, bool]) -> bytes:
    return _build_channel_bool_map("CC", layer, values)


def parse_set_channel_active(reply: Reply) -> None:
    _require_ok(reply, command="ChannelSetActive")


def build_set_channel_solo(layer: int, values: dict[int, bool]) -> bytes:
    return _build_channel_bool_map("CB", layer, values)


def parse_set_channel_solo(reply: Reply) -> None:
    _require_ok(reply, command="ChannelSetSolo")


# --- Layer Playback Control --------------------------------------------------


def build_layer_go(layer: int, cue_list: int, cue_step: int | None = None) -> bytes:
    parts = [hex8(layer), hex16(cue_list)]
    if cue_step is not None:
        parts.append(hex8(cue_step))
    return framing.encode_request("56", *parts)


def parse_layer_go(reply: Reply) -> None:
    _require_ok(reply, command="LayerGo")


def build_layer_clear(layer: int) -> bytes:
    return framing.encode_request("57", hex8(layer))


def parse_layer_clear(reply: Reply) -> None:
    _require_ok(reply, command="LayerClear")


def build_layer_pause(layer: int) -> bytes:
    return framing.encode_request("58", hex8(layer))


def parse_layer_pause(reply: Reply) -> None:
    _require_ok(reply, command="LayerPause")


def build_layer_resume(layer: int) -> bytes:
    return framing.encode_request("59", hex8(layer))


def parse_layer_resume(reply: Reply) -> None:
    _require_ok(reply, command="LayerResume")


def build_layer_next_step(layer: int) -> bytes:
    return framing.encode_request("5A", hex8(layer))


def parse_layer_next_step(reply: Reply) -> None:
    _require_ok(reply, command="LayerNextStep")


def build_layer_previous_step(layer: int) -> bytes:
    return framing.encode_request("5B", hex8(layer))


def parse_layer_previous_step(reply: Reply) -> None:
    _require_ok(reply, command="LayerPreviousStep")


# --- Cue List Control --------------------------------------------------------

MAX_CUE_STEPS_PER_LIST = 99
MAX_CUE_SCENE_VALUES_PER_MESSAGE = 250


@dataclass(frozen=True)
class CueListInfo:
    number: int
    step_count: int


def build_get_cue_list_directory(start_index: int = 1) -> bytes:
    return framing.encode_request("A7", hex16(start_index))


def parse_get_cue_list_directory(reply: Reply) -> list[CueListInfo]:
    _require_ok(reply, command="CueListGetDirectory")
    remaining = reply.data or ""
    infos: list[CueListInfo] = []
    while remaining:
        fields, remaining = read_fields(remaining, [("number", 2), ("step_count", 1)])
        infos.append(CueListInfo(number=fields["number"], step_count=fields["step_count"]))
    return infos


def build_remove_cue_list(cue_list: int) -> bytes:
    return framing.encode_request("60", hex16(cue_list))


def parse_remove_cue_list(reply: Reply) -> None:
    _require_ok(reply, command="CueListRemove")


def build_remove_cue_list_step(cue_list: int, cue_step: int) -> bytes:
    return framing.encode_request("62", hex16(cue_list), hex8(cue_step))


def parse_remove_cue_list_step(reply: Reply) -> None:
    _require_ok(reply, command="CueListRemoveStep")


def build_read_cue_list(cue_list: int, start_step: int = 1, count: int = 0) -> bytes:
    """`count=0` (the default) asks the LanBox for every step in the list."""
    return framing.encode_request("AB", hex16(cue_list), hex8(start_step), hex8(count))


def parse_read_cue_list(reply: Reply) -> list[CueStep]:
    _require_ok(reply, command="CueListRead")
    data = reply.data or ""
    return [CueStep.from_hex(data[i : i + 14]) for i in range(0, len(data), 14)]


def build_write_cue_list(cue_list: int, steps: list[CueStep]) -> bytes:
    if not 1 <= len(steps) <= MAX_CUE_STEPS_PER_LIST:
        raise ValueError(f"a Cue List holds 1-{MAX_CUE_STEPS_PER_LIST} steps, got {len(steps)}")
    parts = [hex16(cue_list), hex8(len(steps))]
    parts.extend(step.to_hex() for step in steps)
    return framing.encode_request("AA", *parts)


def parse_write_cue_list(reply: Reply) -> None:
    _require_ok(reply, command="CueListWrite")


def build_read_cue_scene(cue_list: int, cue_step: int, start_channel: int | None = None) -> bytes:
    parts = [hex16(cue_list), hex8(cue_step)]
    if start_channel is not None:
        parts.append(hex16(start_channel))
    return framing.encode_request("AD", *parts)


def parse_read_cue_scene(reply: Reply) -> tuple[dict[int, int], int]:
    """Returns (values, count) - `count` is how many pairs this reply carried,
    used by the caller to decide whether to page for more (see CueSceneRead's
    caller in client.py for the paging loop)."""
    _require_ok(reply, command="CueSceneRead")
    data = reply.data or ""
    header, remaining = read_fields(data, [("scene_flag", 1), ("channel_count", 2)])
    values: dict[int, int] = {}
    for i in range(0, len(remaining), 6):
        pair, _ = read_fields(remaining[i : i + 6], [("channel", 2), ("value", 1)])
        values[pair["channel"]] = pair["value"]
    return values, header["channel_count"]


def build_write_cue_scene(cue_list: int, cue_step: int, values: dict[int, int]) -> bytes:
    if not 1 <= len(values) <= MAX_CUE_SCENE_VALUES_PER_MESSAGE:
        raise ValueError(
            f"a single CueSceneWrite message holds 1-{MAX_CUE_SCENE_VALUES_PER_MESSAGE} "
            f"channel values, got {len(values)}"
        )
    parts = [hex16(cue_list), hex8(cue_step), hex8(0), hex16(len(values))]
    for channel, value in values.items():
        parts.append(hex16(channel))
        parts.append(hex8(value))
    return framing.encode_request("AC", *parts)


def parse_write_cue_scene(reply: Reply) -> None:
    _require_ok(reply, command="CueSceneWrite")


# --- Layer Configuration & Chase/Fade Control (reference chart pp. 19-24, 29-31) ---


def _build_layer_bool(code: str, layer: int, enabled: bool) -> bytes:
    return framing.encode_request(code, hex8(layer), hex8(0xFF if enabled else 0x00))


def build_set_layer_id(layer: int, new_id: int) -> bytes:
    return framing.encode_request("45", hex8(layer), hex8(new_id))


def parse_set_layer_id(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetID")


def build_set_layer_output(layer: int, enabled: bool) -> bytes:
    return _build_layer_bool("48", layer, enabled)


def parse_set_layer_output(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetOutput")


def build_set_layer_fading(layer: int, enabled: bool) -> bytes:
    return _build_layer_bool("46", layer, enabled)


def parse_set_layer_fading(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetFading")


def build_set_layer_solo(layer: int, enabled: bool) -> bytes:
    return _build_layer_bool("4A", layer, enabled)


def parse_set_layer_solo(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetSolo")


def build_set_layer_auto_output(layer: int, enabled: bool) -> bytes:
    return _build_layer_bool("64", layer, enabled)


def parse_set_layer_auto_output(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetAutoOutput")


def build_set_layer_locked(layer: int, enabled: bool) -> bytes:
    return _build_layer_bool("43", layer, enabled)


def parse_set_layer_locked(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetLocked")


def build_set_layer_mix_mode(layer: int, mode: int) -> bytes:
    return framing.encode_request("47", hex8(layer), hex8(mode))


def parse_set_layer_mix_mode(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetMixMode")


def build_set_layer_transparency_depth(layer: int, depth: int) -> bytes:
    return framing.encode_request("63", hex8(layer), hex8(depth))


def parse_set_layer_transparency_depth(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetTransparencyDepth")


def build_set_layer_chase_mode(layer: int, mode: int) -> bytes:
    return framing.encode_request("4B", hex8(layer), hex8(mode))


def parse_set_layer_chase_mode(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetChaseMode")


def build_set_layer_chase_speed(layer: int, speed: int) -> bytes:
    return framing.encode_request("4C", hex8(layer), hex8(speed))


def parse_set_layer_chase_speed(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetChaseSpeed")


def build_set_layer_fade_type(layer: int, fade_type: int) -> bytes:
    return framing.encode_request("4D", hex8(layer), hex8(fade_type))


def parse_set_layer_fade_type(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetFadeType")


def build_set_layer_fade_time(layer: int, seconds: float) -> bytes:
    return framing.encode_request("4E", hex8(layer), hex8(encode_cue_time(seconds)))


def parse_set_layer_fade_time(reply: Reply) -> None:
    _require_ok(reply, command="LayerSetFadeTime")


# LayerConfigure (#44) creates, deletes, and reorders Layers. Short form:
# "place Layer LS above Layer LD"; the reference chart's own worked examples
# (pp. 24-25) establish the special marker values below.
LAYER_CONFIGURE_NEW_OR_DELETE_MARKER = 0x40  # as LD: create a new Layer here; as LS: delete Layer LD
LAYER_CONFIGURE_TOP_OF_MIXING_ORDER = 0x00  # as LS: place LD on top of the mixing order
DEFAULT_NEW_LAYER_ATTRIBUTES = 0x27  # Output + Edit/Run + Fading + Auto Activate on (documented Layer defaults)


def build_layer_configure_short(destination: int, source: int) -> bytes:
    return framing.encode_request("44", hex8(destination), hex8(source))


def build_layer_configure_long(
    destination: int,
    source: int,
    layer_id: int,
    attributes: int,
    start_cue_list: int,
    start_cue_step: int,
) -> bytes:
    return framing.encode_request(
        "44",
        hex8(destination),
        hex8(source),
        hex8(layer_id),
        hex8(attributes),
        hex16(start_cue_list),
        hex8(start_cue_step),
    )


def parse_layer_configure(reply: Reply) -> None:
    _require_ok(reply, command="LayerConfigure")


# --- LanBox Global Settings (reference chart pp. 7-8, 50-54) ----------------

BAUD_RATE_NAMES = {0: "38400", 1: "19200", 2: "9600", 3: "31250 (MIDI)"}
MAX_NAME_LENGTH = 13

_GLOBAL_DATA_HEAD_SPEC = [
    ("baud_rate", 1),
    ("dmx_out_offset", 2),
    ("dmx_channel_count", 2),
    ("name_length", 1),
]
_GLOBAL_DATA_TAIL_SPEC = [
    ("sysex_device_id", 1),
    ("ip1", 1), ("ip2", 1), ("ip3", 1), ("ip4", 1),
    ("sn1", 1), ("sn2", 1), ("sn3", 1), ("sn4", 1),
    ("gw1", 1), ("gw2", 1), ("gw3", 1), ("gw4", 1),
]
_NAME_FIELD_BYTES = 13  # always sent as a fixed-width 13-byte field


@dataclass(frozen=True)
class GlobalData:
    baud_rate_param: int
    dmx_out_offset: int
    dmx_channel_count: int
    name: str
    sysex_device_id: int
    ip_address: tuple[int, int, int, int]
    subnet_mask: tuple[int, int, int, int]
    gateway: tuple[int, int, int, int]


def build_get_global_data() -> bytes:
    return framing.encode_request("0B")


def parse_get_global_data(reply: Reply) -> GlobalData:
    # Only decodes the prefix through Standard Gateway - CommonGetGlobalData's
    # full reply also covers DMX Input/UDP/clock config, which this LanBox
    # client doesn't manage yet (see the v5 plan's scope decisions).
    _require_ok(reply, command="CommonGetGlobalData")
    data = reply.data or ""
    head, remaining = read_fields(data, _GLOBAL_DATA_HEAD_SPEC)
    name_hex = remaining[: _NAME_FIELD_BYTES * 2]
    remaining = remaining[_NAME_FIELD_BYTES * 2 :]
    name_length = head["name_length"]
    name = "".join(
        chr(framing.parse_hex(name_hex[i : i + 2])) for i in range(0, name_length * 2, 2)
    )
    tail, _ = read_fields(remaining, _GLOBAL_DATA_TAIL_SPEC)
    return GlobalData(
        baud_rate_param=head["baud_rate"],
        dmx_out_offset=head["dmx_out_offset"],
        dmx_channel_count=head["dmx_channel_count"],
        name=name,
        sysex_device_id=tail["sysex_device_id"],
        ip_address=(tail["ip1"], tail["ip2"], tail["ip3"], tail["ip4"]),
        subnet_mask=(tail["sn1"], tail["sn2"], tail["sn3"], tail["sn4"]),
        gateway=(tail["gw1"], tail["gw2"], tail["gw3"], tail["gw4"]),
    )


def build_set_name(name: str) -> bytes:
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"a LanBox name is at most {MAX_NAME_LENGTH} characters, got {len(name)!r}")
    return framing.encode_request("AE", *(hex8(ord(c)) for c in name))


def parse_set_name(reply: Reply) -> None:
    _require_ok(reply, command="CommonSetName")


def build_set_password(password: int) -> bytes:
    return framing.encode_request("AF", hex16(password))


def parse_set_password(reply: Reply) -> None:
    _require_ok(reply, command="CommonSetPassword")


def build_set_dmx_offset(offset: int) -> bytes:
    return framing.encode_request("6A", hex16(offset))


def parse_set_dmx_offset(reply: Reply) -> None:
    _require_ok(reply, command="CommonSetDMXOffset")


def build_set_num_dmx_channels(count: int) -> bytes:
    return framing.encode_request("69", hex16(count))


def parse_set_num_dmx_channels(reply: Reply) -> None:
    _require_ok(reply, command="CommonSetNumDMXChannels")


def build_set_ip_config(
    ip: tuple[int, int, int, int],
    subnet: tuple[int, int, int, int],
    gateway: tuple[int, int, int, int],
) -> bytes:
    octets = (*ip, *subnet, *gateway)
    return framing.encode_request("B0", *(hex8(octet) for octet in octets))


def parse_set_ip_config(reply: Reply) -> None:
    _require_ok(reply, command="CommonSetIpConfig")


def build_set_baud_rate(param: int) -> bytes:
    # 4-hex-char command code, like CommonGetAppID's "0005" - see the
    # reference chart's own "Note the extra 0's in the command number".
    return framing.encode_request("0006", hex8(param))


def parse_set_baud_rate(reply: Reply) -> None:
    _require_ok(reply, command="CommonSetBaudRate")


def build_reboot() -> bytes:
    return framing.encode_request("B5")


def parse_reboot(reply: Reply) -> None:
    _require_ok(reply, command="CommonReboot")


def build_save_data() -> bytes:
    return framing.encode_request("A9")


def parse_save_data(reply: Reply) -> None:
    _require_ok(reply, command="CommonSaveData")
