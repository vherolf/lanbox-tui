"""In-memory fake LanBox: just enough state to answer the v1 command subset.

This does not attempt to simulate fades, cue-list playback, or timing - it
exists so the client and TUI can be developed and tested without real
hardware. State transitions mirror the *documented* defaults and behavior
(e.g. 5 active Layers A-E on boot, ChannelSetData implicitly activating a
Channel's output) from "LanBox Reference Chart 3.04".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lanbox_tui.protocol.commands import (
    LAYER_CONFIGURE_NEW_OR_DELETE_MARKER,
    LAYER_CONFIGURE_TOP_OF_MIXING_ORDER,
    LayerAttributes,
)
from lanbox_tui.protocol.cue_steps import STEP_SHOW_SCENE, CueStep, encode_cue_time

DEFAULT_DEVICE_CODE = 0xF8FD  # LCX
DEFAULT_FIRMWARE_VERSION = 3.01
DEFAULT_PASSWORD = "777"


@dataclass
class SimulatedChannel:
    value: int = 0
    output_to_mixer: bool = False
    edit_enabled: bool = True
    solo_mode: bool = False
    fading: bool = False

    def status_byte(self) -> int:
        bits = 0
        if self.output_to_mixer:
            bits |= 0x01
        if self.edit_enabled:
            bits |= 0x02
        if self.solo_mode:
            bits |= 0x04
        if self.fading:
            bits |= 0x08
        return bits


@dataclass
class SimulatedLayer:
    internal_number: int
    layer_id: int
    output_enabled: bool = True
    edit_run_mode: bool = True
    fading_enabled: bool = True
    solo_mode: bool = False
    paused: bool = False
    auto_activate: bool = True
    sequencer_waiting: bool = False
    locked: bool = False
    active_cue_list: int = 0
    active_cue_step: int = 0
    mix_mode: int = 1  # Copy (Table 5 default)
    transparency_depth: int = 127  # 50%
    chase_mode: int = 0  # Off (Table 6 default)
    chase_speed: int = 127  # 100%
    fade_type: int = 0  # Off (Table 7 default)
    fade_time_code: int = field(default_factory=lambda: encode_cue_time(3.0))  # docs: default 3.0s
    channels: dict[int, SimulatedChannel] = field(default_factory=dict)

    def channel(self, number: int) -> SimulatedChannel:
        return self.channels.setdefault(number, SimulatedChannel())

    def attributes_byte(self) -> int:
        bits = 0
        if self.output_enabled:
            bits |= 0x01
        if self.edit_run_mode:
            bits |= 0x02
        if self.fading_enabled:
            bits |= 0x04
        if self.solo_mode:
            bits |= 0x08
        if self.paused:
            bits |= 0x10
        if self.auto_activate:
            bits |= 0x20
        if self.sequencer_waiting:
            bits |= 0x40
        if self.locked:
            bits |= 0x80
        return bits


class LanBoxState:
    def __init__(
        self,
        *,
        device_code: int = DEFAULT_DEVICE_CODE,
        firmware_version: float = DEFAULT_FIRMWARE_VERSION,
        password: str = DEFAULT_PASSWORD,
    ) -> None:
        self.device_code = device_code
        self.firmware_version = firmware_version
        self.password = password
        self.sixteen_bit_mode = False
        self.layers: dict[int, SimulatedLayer] = {}
        # Real LanBox-LCX boots with 5 active Layers, A through E.
        for offset, layer_id in enumerate(range(1, 6)):
            self.layers[layer_id] = SimulatedLayer(internal_number=90 + offset, layer_id=layer_id)
        # Layer IDs in mixing order, top (highest priority) first - independent
        # of numeric Layer ID so LayerConfigure can actually reorder Layers.
        self.layer_order: list[int] = [1, 2, 3, 4, 5]
        self._next_internal_number = 95

        self.cue_lists: dict[int, list[CueStep]] = {}
        # Keyed by (cue_list, cue_step) -> {channel: value}.
        self.cue_scenes: dict[tuple[int, int], dict[int, int]] = {}

    def layers_in_mixing_order(self) -> list[SimulatedLayer]:
        return [self.layers[layer_id] for layer_id in self.layer_order]

    def configure_layer(
        self,
        destination: int,
        source: int,
        *,
        layer_id: int | None = None,
        attributes: int | None = None,
        start_cue_list: int = 0,
        start_cue_step: int = 0,
    ) -> None:
        """Mirrors LayerConfigure's (#44) short/long form semantics: create,
        delete, or reorder a Layer - see commands.py for the marker constants."""
        if source == LAYER_CONFIGURE_NEW_OR_DELETE_MARKER:
            self.layers.pop(destination, None)
            if destination in self.layer_order:
                self.layer_order.remove(destination)
            return

        if destination == LAYER_CONFIGURE_NEW_OR_DELETE_MARKER:
            new_id = layer_id if layer_id is not None else destination
            new_layer = SimulatedLayer(internal_number=self._next_internal_number, layer_id=new_id)
            self._next_internal_number += 1
            if attributes is not None:
                attrs = LayerAttributes.from_byte(attributes)
                new_layer.output_enabled = attrs.output_enabled
                new_layer.edit_run_mode = attrs.edit_run_mode
                new_layer.fading_enabled = attrs.fading_enabled
                new_layer.solo_mode = attrs.solo_mode
                new_layer.paused = attrs.paused
                new_layer.auto_activate = attrs.auto_activate
                new_layer.sequencer_waiting = attrs.sequencer_waiting
                new_layer.locked = attrs.locked
            new_layer.active_cue_list = start_cue_list
            new_layer.active_cue_step = start_cue_step
            self.layers[new_id] = new_layer
            if source == LAYER_CONFIGURE_TOP_OF_MIXING_ORDER or source not in self.layer_order:
                self.layer_order.insert(0, new_id)
            else:
                self.layer_order.insert(self.layer_order.index(source) + 1, new_id)
            return

        # Move: place `source` directly above `destination` in the stack.
        if source in self.layer_order:
            self.layer_order.remove(source)
        if destination == LAYER_CONFIGURE_TOP_OF_MIXING_ORDER or destination not in self.layer_order:
            self.layer_order.insert(0, source)
        else:
            self.layer_order.insert(self.layer_order.index(destination), source)

    def rename_layer(self, layer_id: int, new_id: int) -> None:
        """Mirrors LayerSetID (#45): if `new_id` is already in use, that other
        Layer is dropped (per the reference chart's documented behavior)."""
        layer = self.layers[layer_id]
        if new_id in self.layers and new_id != layer_id:
            self.layers.pop(new_id, None)
            if new_id in self.layer_order:
                self.layer_order.remove(new_id)
        del self.layers[layer_id]
        layer.layer_id = new_id
        self.layers[new_id] = layer
        self.layer_order[self.layer_order.index(layer_id)] = new_id

    def apply_cue_step(self, layer: SimulatedLayer, cue_list: int, cue_step_index: int) -> None:
        """Apply the addressed step's effect immediately (no fade/hold timing -
        see the module docstring for why the simulator doesn't model timing)."""
        steps = self.cue_lists.get(cue_list, [])
        if not (1 <= cue_step_index <= len(steps)):
            return
        layer.active_cue_list = cue_list
        layer.active_cue_step = cue_step_index
        step = steps[cue_step_index - 1]
        if step.kind == STEP_SHOW_SCENE:
            scene = self.cue_scenes.get((cue_list, cue_step_index), {})
            for channel, value in scene.items():
                channel_state = layer.channel(channel)
                channel_state.value = value
                channel_state.output_to_mixer = True
