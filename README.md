# lanbox-tui

A modern, Linux/Unix-first control tool for LanBox DMX controllers (LanBox-LCX
and similar), replacing the abandoned Windows/Mac-only LCedit+ software.

The LanBox protocol is fully documented in vendor PDFs (`LanBox Reference
3.04.pdf`, `LCedit manual 4_1.pdf` in this directory) as a plain-ASCII
command protocol over TCP/IP or serial/USB. See `src/lanbox_tui/protocol/`
for the reimplementation.

## Implementation status

This section tracks progress toward a **full LCedit+ replacement**, not just
the current release. "Done" means implemented and covered by tests; nothing
below has been verified against real hardware yet (see Testing).

### Done (v1)

**Core plumbing**
- [x] Wire framing (`*<hex>#` requests, `>`/`?`/`*<data>#>` replies) - `protocol/framing.py`
- [x] TCP transport (`transport/tcp.py`) - default port 777, password handshake
- [x] Async client with request/reply serialization - `client.py`
- [x] Simulator: a fake LanBox TCP server for dev/testing without hardware - `simulator/`
- [x] Textual TUI shell: connect screen -> main screen - `tui/`

**Commands implemented** (8 of ~80+ in the full reference chart):

| Command | Code | Used for |
|---|---|---|
| CommonGetAppID | `0005` | Identify device type + firmware on connect |
| Common16BitMode | `65` | Switch to 16-bit mode on connect |
| CommonGetLayers | `B1` | Populate the Layer sidebar |
| LayerGetStatus | `0A` | Per-layer detail (used for the pause/resume toggle) |
| ChannelReadData | `CD` | Live channel value polling |
| ChannelReadStatus | `CE` | Live channel flags (output/solo/fading) polling |
| ChannelSetData | `C9` | Editing a channel value from the grid |
| ChannelSetOutputEnable | `CA` | Toggling a channel's output on/off |

**What you can actually do right now:** connect to a LanBox (or the
simulator), see the active Layers, and view/edit individual Channel values
live, one Layer at a time, in a 64-channel scrollable window.

### Done (v2)

**Cue Lists and Layer playback control** - the biggest step yet toward a real
LCedit+ replacement: the LanBox can now be *programmed*, not just remote-
controlled.

- [x] Cue List domain model (`protocol/cue_steps.py`): Appendix A's 92-entry
  time-encoding table and Appendix B's Cue Step Types - `Show Scene`, `Hold`,
  `Go Cue Step`, `Go Cue Step in Layer`, and the single-Layer control steps
  (`Clear`/`Pause`/`Resume`/`Start`/`Stop Layer`) are specially modeled with
  typed constructors/accessors; every other step type round-trips losslessly
  as a generic `CueStep(kind, params)` so nothing is corrupted by reading and
  re-writing a list that uses a type the TUI doesn't specially understand.
- [x] Commands: `CueListGetDirectory` (`A7`), `CueListRead` (`AB`),
  `CueListWrite` (`AA`), `CueListRemove` (`60`), `CueListRemoveStep` (`62`),
  `CueSceneRead` (`AD`), `CueSceneWrite` (`AC`) - directory paging (>80 lists)
  and Cue Scene paging (>250 channel values) are both implemented in
  `client.py`. Cue Lists themselves are capped at 99 steps and sent/read in a
  single message - the reference chart's wording on multi-frame chunking for
  longer lists is internally ambiguous and untestable without real hardware,
  so it's deliberately not implemented (flagged for revisiting once hardware
  is available).
- [x] Layer playback: `LayerGo` (`56`), `LayerClear` (`57`), `LayerPause`
  (`58`), `LayerResume` (`59`), `LayerNextStep` (`5A`), `LayerPreviousStep`
  (`5B`).
- [x] New Cue Lists screen (`c` from the main screen): browse/create/delete
  Cue Lists, append Show Scene/Hold/Go-Cue-Step steps, delete steps, and edit
  a Show Scene step's Channel values in a dedicated (non-live) Scene editor.
- [x] Main screen playback controls: `g` (Go to a Cue List/Step), `p`
  (pause/resume), `.`/`,` (next/previous step).

**Deliberately deferred** (see the plan history for the reasoning):
`LayerNextCue`/`PreviousCue` and the Real-Time (on-the-fly) per-step editing
commands (`LayerSetEditRunMode`, `CueListCreate`, `LayerInsertStep`,
`LayerReplaceStep`, `LayerSetCueStepType`, `LayerSetCueStepParameters`) -
even LCedit+ itself didn't implement the first two, and the bulk
`CueListWrite`/`CueSceneWrite` approach used here covers the same ground with
far less on-device state to manage.

### Done (v3)

**Layer configuration and Chase/Fade control** - Layers are no longer stuck
with whatever they booted with: they can be created, deleted, reordered, and
individually tuned.

- [x] Commands: `LayerSetID` (`45`), `LayerSetOutput` (`48`), `LayerSetFading`
  (`46`), `LayerSetSolo` (`4A`), `LayerSetAutoOutput` (`64`), `LayerSetLocked`
  (`43`), `LayerSetMixMode` (`47`), `LayerSetTransparencyDepth` (`63`),
  `LayerSetChaseMode` (`4B`), `LayerSetChaseSpeed` (`4C`), `LayerSetFadeType`
  (`4D`), `LayerSetFadeTime` (`4E`, reuses the same Appendix A time table as
  Cue Steps), and `LayerConfigure` (`44`, short + long form) for
  creating/deleting/reordering Layers - `client.py` wraps its raw
  create/delete/move semantics as `create_layer`/`delete_layer`/
  `move_layer_above`.
- [x] Simulator fix: `LanBoxState` now tracks an explicit `layer_order` list
  (top-to-bottom mixing order) instead of just sorting Layer IDs numerically
  - a real gap in v1/v2's simulator that this feature's reordering support
    required fixing first.
- [x] New Layer settings screen (`l` from the main screen, for the selected
  Layer): toggle Output/Fading/Solo/Auto Output/Locked, cycle Mix Mode/Chase
  Mode/Fade Type, set Transparency Depth/Chase Speed/Fade Time, and rename
  the Layer's ID.
- [x] Main screen Layer-list controls: `plus`/`minus` (add/delete a Layer),
  `u`/`n` (move the selected Layer up/down the mixing order).

**A real Textual gotcha worth remembering:** a `Screen` subclass with no
naturally-focused widget (like the new Layer settings screen, which is driven
entirely by keybindings) needs `AUTO_FOCUS = ""` - setting it to `None`
looks like "disable auto-focus" but Textual's own fallback logic reads that
as "inherit `App.AUTO_FOCUS`", which defaults to `"*"` and will silently
auto-focus the first focusable widget (even a hidden `Input`), swallowing
every keypress as text entry instead of letting it reach the screen's
`BINDINGS`.

### Done (v4)

**Channel active/solo control** - a small addition rounding off the Channel
grid feature set from v1.

- [x] Commands: `ChannelSetActive` (`CC`) and `ChannelSetSolo` (`CB`), same
  "Layer + n×(Channel, Bool)" shape as `ChannelSetOutputEnable` (including the
  Channel-number-0-means-all-Channels convention).
- [x] The Channel grid now shows `Act`/`Solo` columns alongside `Out`, backed
  by data the client was already polling (`ChannelReadStatus`) but not
  displaying.
- [x] Main screen: `a` toggles the selected Channel's Active status, `s`
  toggles Solo.
- Note: `ChannelSetActive`'s "Active Status Attribute" isn't explicitly
  cross-referenced in the reference chart to a specific status bit, but the
  Channel Control section's description of "activating" a Channel lines up
  with Table 3's bit1 ("Channel edit enabled") - the simulator maps it there
  (see `simulator/server.py::_handle_set_channel_active`). Worth confirming
  against real hardware. `ChannelSetSolo` is annotated "LCedit+: not
  implemented" in the reference chart, but is implemented here anyway since
  it's the only way to control per-Channel Solo (unlike the `LayerNextCue`
  -style commands skipped in v2, there's no equivalent alternate path).

### Not yet implemented

Everything else LCedit+ does. Grouped by area, referencing the reference
chart's own command names so it's traceable back to the spec:

- **The other ~14 Cue Step Types** from Appendix B that aren't specially
  modeled yet (Go if Analog Input, Go if Channel, Set Layer Attributes/Mix
  Mode/Chaser, Write MIDI/Serial Stream, Comment, Configure Layer, Loop Cue
  Step, Hold Until, Reset Layer, Go Trigger, Show Scene of Cue List) - these
  round-trip safely as raw/opaque steps but aren't editable in the TUI.
- **MIDI**: per-layer MIDI settings (`LayerSetDeviceID`, `LayerSetSustain`,
  `LayerIgnoreNoteOff`), MIDI mapping (`CommonGet/Set/StoreMIDIMapping`),
  MIDI Show Control, Note/CC/Program Change control surfaces.
- **Global/device settings UI**: IP config, DMX offset/channel count, device
  name, password, serial baud rate, gain/curves/slopes, patcher
  (`CommonGetGlobalData`, `CommonSetIpConfig`, `CommonSetDMXOffset`,
  `CommonSetNumDMXChannels`, `CommonSetName`, `CommonSetPassword`,
  `CommonSetBaudRate`, gain/curve/slope commands, `Common*Patcher`).
- **UDP networking**: bulk channel streaming and Art-Net bridging
  (`CommonSetUdpIn`, `CommonSetUdpOut`) - v1 only uses the TCP command
  channel.
- **Serial/USB transport**: the LanBox enumerates as a USB-serial modem;
  only TCP is implemented so far (`transport/base.py` is already abstracted
  for this).
- **Persistence**: `CommonSaveData` (flush RAM to flash), `CommonReboot`,
  `CommonResetNonVolatile`, firmware upload, backup/restore.
- **Debug commands**: `DebugGetTotalUsage`, `DebugGetFreeList`,
  `DebugGetCuelistUsage` - low priority, mainly useful for troubleshooting.
- **LCedit-level UX concepts** that sit above the raw protocol: a Fixture
  library/patch table (naming Channels after real fixtures/parameters
  instead of raw numbers), Stage layout, Groups, Presets - none of this is
  protocol work, it's a UI/data-model layer for later.
- **Real-hardware verification**: everything above has only run against the
  simulator so far - see `simulator/state.py` for what it does and doesn't
  model (no fade/cue-timing simulation).

## Setup

```sh
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Running against the simulator (no hardware required)

A fake LanBox is included so the client/TUI can be developed and tested
without real hardware. In one terminal:

```sh
lanbox-simulator --port 1777
```

In another:

```sh
lanbox-tui
```

At the connect screen, use host `127.0.0.1`, port `1777`, password `777`
(the simulator's defaults).

## Running against real hardware

Same as above, but point `lanbox-tui` at the LanBox's actual IP address
(factory default `192.168.1.77`, port `777`, password `777`) instead of the
simulator. No separate setup needed - it's the same protocol either way.
This has not been tried against a real LanBox yet.

## Testing

```sh
pytest
```

Covers wire-framing round-trips, each command's encode/decode against
worked examples from the reference PDF, a full simulator+client
integration test, and a headless Textual smoke test that drives the actual
TUI screens against the simulator.
