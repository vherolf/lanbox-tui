"""Cue Step time encoding (Appendix A) and step types (Appendix B).

Only a subset of the ~20 documented Cue Step Types is specially modeled
(Show Scene, Hold, Go Cue Step, Go Cue Step in Layer, and the single-Layer
control steps Clear/Pause/Resume/Start/Stop Layer) - see the v2 plan for
why. Every other type round-trips losslessly as a `CueStep` with its raw
`kind`/`params`, just without typed accessors or a specialized `describe()`
string.
"""

from __future__ import annotations

from dataclasses import dataclass

from lanbox_tui.protocol.framing import layer_id_to_label

# --- Appendix A: Cue Step Time Encoding Table -------------------------------
# (code, seconds) - seconds is None for code 0x5C, "For ever".
CUE_TIME_TABLE: list[tuple[int, float | None]] = [
    (0x01, 0.05), (0x02, 0.10), (0x03, 0.15), (0x04, 0.20), (0x05, 0.25),
    (0x06, 0.30), (0x07, 0.35), (0x08, 0.40), (0x09, 0.45), (0x0A, 0.50),
    (0x0B, 0.55), (0x0C, 0.60), (0x0D, 0.65), (0x0E, 0.70), (0x0F, 0.75),
    (0x10, 0.80), (0x11, 0.85), (0x12, 0.90), (0x13, 0.95), (0x14, 1.00),
    (0x15, 1.10), (0x16, 1.20), (0x17, 1.30), (0x18, 1.50), (0x19, 1.60),
    (0x1A, 1.80), (0x1B, 2.00), (0x1C, 2.20), (0x1D, 2.40), (0x1E, 2.70),
    (0x1F, 3.00), (0x20, 3.30), (0x21, 3.60), (0x22, 3.90), (0x23, 4.30),
    (0x24, 4.70), (0x25, 5.10), (0x26, 5.60), (0x27, 6.20), (0x28, 6.80),
    (0x29, 7.50), (0x2A, 8.20), (0x2B, 9.10), (0x2C, 10.00), (0x2D, 11.00),
    (0x2E, 12.00), (0x2F, 13.00), (0x30, 15.00), (0x31, 16.00), (0x32, 18.00),
    (0x33, 20.00), (0x34, 22.00), (0x35, 24.00), (0x36, 27.00), (0x37, 30.00),
    (0x38, 33.00), (0x39, 36.00), (0x3A, 39.00), (0x3B, 43.00), (0x3C, 47.00),
    (0x3D, 51.00), (0x3E, 56.00), (0x3F, 60.00), (0x40, 66.00), (0x41, 72.00),
    (0x42, 78.00), (0x43, 90.00), (0x44, 96.00), (0x45, 108.00), (0x46, 120.00),
    (0x47, 132.00), (0x48, 144.00), (0x49, 162.00), (0x4A, 180.00), (0x4B, 198.00),
    (0x4C, 222.00), (0x4D, 234.00), (0x4E, 258.00), (0x4F, 288.00), (0x50, 306.00),
    (0x51, 342.00), (0x52, 378.00), (0x53, 408.00), (0x54, 450.00), (0x55, 492.00),
    (0x56, 546.00), (0x57, 600.00), (0x58, 660.00), (0x59, 720.00), (0x5A, 780.00),
    (0x5B, 900.00), (0x5C, None),  # "For ever"
]
CUE_TIME_FOREVER = 0x5C
_CODE_TO_SECONDS = dict(CUE_TIME_TABLE)


def decode_cue_time(code: int) -> float | None:
    if code not in _CODE_TO_SECONDS:
        raise ValueError(f"not a valid Cue Step time code: {code!r}")
    return _CODE_TO_SECONDS[code]


def encode_cue_time(seconds: float) -> int:
    """Return the table code whose duration is closest to `seconds`."""
    timed_entries = [(code, s) for code, s in CUE_TIME_TABLE if s is not None]
    return min(timed_entries, key=lambda entry: abs(entry[1] - seconds))[0]


# --- Appendix B: Cue Step Types (subset specially modeled) ------------------

STEP_SHOW_SCENE = 0x01
STEP_GO_CUE_STEP_IN_LAYER = 0x0A
STEP_CLEAR_LAYER = 0x0B
STEP_PAUSE_LAYER = 0x0C
STEP_RESUME_LAYER = 0x0D
STEP_START_LAYER = 0x0E
STEP_STOP_LAYER = 0x0F
STEP_GO_CUE_STEP = 0x14
STEP_HOLD = 0x18

_LAYER_CONTROL_KINDS = {
    STEP_CLEAR_LAYER: "Clear Layer",
    STEP_PAUSE_LAYER: "Pause Layer",
    STEP_RESUME_LAYER: "Resume Layer",
    STEP_START_LAYER: "Start Layer",
    STEP_STOP_LAYER: "Stop Layer",
}

_WAIT_FLAG = 0x80


@dataclass(frozen=True)
class CueStep:
    """One raw Cue Step: a 6-byte parameter block tagged with its type.

    Always holds the raw `kind`/`params`, so any step type - modeled or not
    - round-trips losslessly through `to_hex`/`from_hex`. Use the named
    constructors and properties below for the specially-modeled kinds.
    """

    wait: bool
    kind: int
    params: tuple[int, int, int, int, int, int]

    def _require_kind(self, *kinds: int) -> None:
        if self.kind not in kinds:
            raise ValueError(f"step kind 0x{self.kind:02X} does not support this accessor")

    # --- named constructors for the specially-modeled step types ---

    @classmethod
    def show_scene(
        cls, *, fade_type: int, fade_seconds: float, hold_seconds: float, wait: bool = False
    ) -> "CueStep":
        return cls(
            wait=wait,
            kind=STEP_SHOW_SCENE,
            params=(fade_type, encode_cue_time(fade_seconds), encode_cue_time(hold_seconds), 0, 0, 0),
        )

    @classmethod
    def hold(cls, seconds: float, *, wait: bool = False) -> "CueStep":
        return cls(wait=wait, kind=STEP_HOLD, params=(encode_cue_time(seconds), 0, 0, 0, 0, 0))

    @classmethod
    def go_cue_step(cls, step: int, *, wait: bool = False) -> "CueStep":
        return cls(wait=wait, kind=STEP_GO_CUE_STEP, params=(step, 0, 0, 0, 0, 0))

    @classmethod
    def go_cue_step_in_layer(
        cls, layer_id: int, cue_list: int, cue_step: int, *, wait: bool = False
    ) -> "CueStep":
        high, low = divmod(cue_list, 256)
        return cls(
            wait=wait,
            kind=STEP_GO_CUE_STEP_IN_LAYER,
            params=(layer_id, high, low, cue_step, 0, 0),
        )

    @classmethod
    def layer_control(cls, kind: int, layer_id: int, *, wait: bool = False) -> "CueStep":
        if kind not in _LAYER_CONTROL_KINDS:
            raise ValueError(f"0x{kind:02X} is not a single-Layer control step type")
        return cls(wait=wait, kind=kind, params=(layer_id, 0, 0, 0, 0, 0))

    # --- typed accessors (raise ValueError if `.kind` doesn't match) ---

    @property
    def fade_type(self) -> int:
        self._require_kind(STEP_SHOW_SCENE)
        return self.params[0]

    @property
    def fade_seconds(self) -> float | None:
        self._require_kind(STEP_SHOW_SCENE)
        return decode_cue_time(self.params[1])

    @property
    def hold_seconds(self) -> float | None:
        self._require_kind(STEP_SHOW_SCENE, STEP_HOLD)
        code = self.params[2] if self.kind == STEP_SHOW_SCENE else self.params[0]
        return decode_cue_time(code)

    @property
    def target_cue_step(self) -> int:
        self._require_kind(STEP_GO_CUE_STEP, STEP_GO_CUE_STEP_IN_LAYER)
        return self.params[0] if self.kind == STEP_GO_CUE_STEP else self.params[3]

    @property
    def target_cue_list(self) -> int:
        self._require_kind(STEP_GO_CUE_STEP_IN_LAYER)
        return self.params[1] * 256 + self.params[2]

    @property
    def target_layer_id(self) -> int:
        self._require_kind(STEP_GO_CUE_STEP_IN_LAYER, *_LAYER_CONTROL_KINDS)
        return self.params[0]

    # --- wire format ---

    def to_hex(self) -> str:
        type_byte = self.kind | (_WAIT_FLAG if self.wait else 0x00)
        return "".join(f"{b:02X}" for b in (type_byte, *self.params))

    @classmethod
    def from_hex(cls, chunk: str) -> "CueStep":
        if len(chunk) != 14:
            raise ValueError(f"a Cue Step is 7 bytes (14 hex chars), got {chunk!r}")
        raw = [int(chunk[i : i + 2], 16) for i in range(0, 14, 2)]
        type_byte, *params = raw
        return cls(wait=bool(type_byte & _WAIT_FLAG), kind=type_byte & ~_WAIT_FLAG, params=tuple(params))


def _format_time(seconds: float | None) -> str:
    return "forever" if seconds is None else f"{seconds:.2f}s"


def describe(step: CueStep) -> str:
    """A short, human-readable summary of a Cue Step for the TUI's step list."""
    prefix = "[wait] " if step.wait else ""
    if step.kind == STEP_SHOW_SCENE:
        return f"{prefix}Show Scene - fade {_format_time(step.fade_seconds)}, hold {_format_time(step.hold_seconds)}"
    if step.kind == STEP_HOLD:
        return f"{prefix}Hold {_format_time(step.hold_seconds)}"
    if step.kind == STEP_GO_CUE_STEP:
        return f"{prefix}Go to step {step.target_cue_step}"
    if step.kind == STEP_GO_CUE_STEP_IN_LAYER:
        layer_label = layer_id_to_label(step.target_layer_id)
        return f"{prefix}Go to Cue List {step.target_cue_list} step {step.target_cue_step} in Layer {layer_label}"
    if step.kind in _LAYER_CONTROL_KINDS:
        layer_label = layer_id_to_label(step.params[0])
        return f"{prefix}{_LAYER_CONTROL_KINDS[step.kind]} {layer_label}"
    return f"{prefix}Type 0x{step.kind:02X} (unsupported)"
