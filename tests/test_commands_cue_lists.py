from lanbox_tui.protocol import commands
from lanbox_tui.protocol.cue_steps import CueStep, STEP_CLEAR_LAYER
from lanbox_tui.protocol.errors import CommandRejected
from lanbox_tui.protocol.framing import Reply, hex8, hex16

import pytest


# --- Layer Playback Control (reference chart pp. 26-28) ---------------------


def test_layer_go_matches_pdf_example():
    # "Start Cue List 673, step 1 in Layer AC" -> "* 56 1D 02A1 01 #"
    assert commands.build_layer_go(layer=0x1D, cue_list=0x02A1, cue_step=1) == b"*561D02A101#"


def test_layer_go_without_step_omits_it():
    assert commands.build_layer_go(layer=1, cue_list=1) == b"*56010001#"


@pytest.mark.parametrize(
    "builder,code",
    [
        (commands.build_layer_clear, "57"),
        (commands.build_layer_pause, "58"),
        (commands.build_layer_resume, "59"),
        (commands.build_layer_next_step, "5A"),
        (commands.build_layer_previous_step, "5B"),
    ],
)
def test_single_layer_playback_commands(builder, code):
    assert builder(0x1F) == f"*{code}1F#".encode()


def test_layer_playback_replies_reject_on_error():
    with pytest.raises(CommandRejected):
        commands.parse_layer_go(Reply(ok=False, data=None))


# --- Cue List Control (reference chart pp. 38-43) ---------------------------


def test_cue_list_get_directory_request_matches_pdf_example():
    assert commands.build_get_cue_list_directory(1) == b"*A70001#"


def test_cue_list_get_directory_parses_pdf_example():
    # "Get a maximum of 80 Cue Lists Starting at Cue List index 1"
    entries = [(1, 3), (2, 3), (3, 5), (4, 1), (8, 1), (11, 7), (151, 7)]
    data = "".join(hex16(number) + hex8(count) for number, count in entries)
    infos = commands.parse_get_cue_list_directory(Reply(ok=True, data=data))
    assert [(i.number, i.step_count) for i in infos] == entries


def test_remove_cue_list_matches_pdf_example():
    # "Delete Cue List 20" -> "* 60 00 14 #"
    assert commands.build_remove_cue_list(20) == b"*600014#"


def test_remove_cue_list_step_matches_pdf_example():
    # "Delete Cue Step 96 of Cue List 546" -> "* 62 02 22 60 #"
    assert commands.build_remove_cue_list_step(cue_list=546, cue_step=96) == b"*62022260#"


def test_read_cue_list_request_matches_pdf_example():
    # "Read all steps of Cue Step Data from Cue List 51, starting at Cue Step 1"
    assert commands.build_read_cue_list(cue_list=51, start_step=1, count=0) == b"*AB00330100#"


def test_read_cue_scene_request_matches_pdf_example():
    # "Read the Scene Data of Cue List 168, Cue Step 2" -> "* AD 00 A8 02 #"
    assert commands.build_read_cue_scene(cue_list=168, cue_step=2) == b"*AD00A802#"


def test_read_cue_scene_parses_pdf_example():
    # Cue List 168, Cue Step 2: 4 channels, values 0, 255, 0, 0
    data = hex8(0) + hex16(4) + "".join(hex16(ch) + hex8(v) for ch, v in [(1, 0), (2, 255), (3, 0), (4, 0)])
    values, count = commands.parse_read_cue_scene(Reply(ok=True, data=data))
    assert count == 4
    assert values == {1: 0, 2: 255, 3: 0, 4: 0}


def test_write_cue_scene_matches_pdf_example():
    # "Write the following Channel Value for Cue List 897, Cue Step 17"
    values = {480: 66, 481: 165, 482: 159, 483: 197, 501: 103, 502: 0, 503: 181, 504: 255}
    request = commands.build_write_cue_scene(cue_list=897, cue_step=17, values=values)
    expected = (
        b"*AC"
        + hex16(897).encode()
        + hex8(17).encode()
        + hex8(0).encode()
        + hex16(len(values)).encode()
        + "".join(hex16(ch) + hex8(v) for ch, v in values.items()).encode()
        + b"#"
    )
    assert request == expected


def test_write_cue_scene_rejects_more_than_250_values():
    with pytest.raises(ValueError):
        commands.build_write_cue_scene(1, 1, {ch: 0 for ch in range(1, 252)})


def test_write_cue_list_rejects_bad_step_counts():
    with pytest.raises(ValueError):
        commands.build_write_cue_list(1, [])
    with pytest.raises(ValueError):
        commands.build_write_cue_list(1, [CueStep.hold(1.0)] * 100)


def test_write_then_read_cue_list_round_trips():
    steps = [
        CueStep.show_scene(fade_type=3, fade_seconds=2.0, hold_seconds=2.0),
        CueStep.hold(0.10),
        CueStep.go_cue_step(1),
        CueStep.go_cue_step_in_layer(layer_id=2, cue_list=117, cue_step=1),
        CueStep.layer_control(STEP_CLEAR_LAYER, layer_id=1),
    ]
    write_request = commands.build_write_cue_list(959, steps)
    assert write_request.startswith(b"*AA03BF05")

    # simulate what the LanBox would echo back on a subsequent CueListRead
    read_data = "".join(step.to_hex() for step in steps)
    parsed = commands.parse_read_cue_list(Reply(ok=True, data=read_data))
    assert parsed == steps
