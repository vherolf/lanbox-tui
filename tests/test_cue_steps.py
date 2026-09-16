import pytest

from lanbox_tui.protocol import cue_steps as cs


def test_cue_time_table_has_92_entries():
    assert len(cs.CUE_TIME_TABLE) == 92


def test_decode_cue_time_matches_appendix_a_examples():
    assert cs.decode_cue_time(0x01) == pytest.approx(0.05)
    assert cs.decode_cue_time(0x1B) == pytest.approx(2.00)  # used in CueListWrite example
    assert cs.decode_cue_time(0x3F) == pytest.approx(60.00)
    assert cs.decode_cue_time(0x5B) == pytest.approx(900.00)
    assert cs.decode_cue_time(cs.CUE_TIME_FOREVER) is None


def test_decode_cue_time_rejects_invalid_code():
    with pytest.raises(ValueError):
        cs.decode_cue_time(0x00)
    with pytest.raises(ValueError):
        cs.decode_cue_time(0x5D)


def test_encode_cue_time_picks_nearest():
    assert cs.encode_cue_time(0.05) == 0x01
    assert cs.encode_cue_time(2.0) == 0x1B
    assert cs.encode_cue_time(1.95) == 0x1B  # closer to 2.00 than 1.80
    assert cs.encode_cue_time(10_000) == 0x5B  # clamps to the largest finite code


def test_show_scene_round_trip():
    step = cs.CueStep.show_scene(fade_type=3, fade_seconds=2.0, hold_seconds=2.0)
    # PDF CueListWrite example: Cue Step type "Hold" data 1B 1B 0A -60 -> here we
    # just check our own round trip through the wire format.
    hex_str = step.to_hex()
    assert len(hex_str) == 14
    decoded = cs.CueStep.from_hex(hex_str)
    assert decoded == step
    assert decoded.fade_type == 3
    assert decoded.fade_seconds == pytest.approx(2.0)
    assert decoded.hold_seconds == pytest.approx(2.0)


def test_hold_step_matches_pdf_worked_example():
    # CueListWrite example, step 1: Hold for 0.10 seconds (time index 2, 0x02 hex)
    step = cs.CueStep.hold(0.10)
    assert step.params[0] == 0x02
    decoded = cs.CueStep.from_hex(step.to_hex())
    assert decoded.kind == cs.STEP_HOLD
    assert decoded.wait is False
    assert decoded.hold_seconds == pytest.approx(0.10)


def test_go_cue_step_in_layer_round_trip():
    # CueListWrite example, step 4: "go 117.1 in Layer B"
    step = cs.CueStep.go_cue_step_in_layer(layer_id=2, cue_list=117, cue_step=1)
    assert len(step.to_hex()) == 14
    decoded = cs.CueStep.from_hex(step.to_hex())
    assert decoded.target_layer_id == 2
    assert decoded.target_cue_list == 117
    assert decoded.target_cue_step == 1


def test_go_cue_step_round_trip():
    step = cs.CueStep.go_cue_step(4)
    decoded = cs.CueStep.from_hex(step.to_hex())
    assert decoded.target_cue_step == 4


def test_layer_control_round_trip_and_rejects_bad_kind():
    step = cs.CueStep.layer_control(cs.STEP_PAUSE_LAYER, layer_id=2)
    decoded = cs.CueStep.from_hex(step.to_hex())
    assert decoded.kind == cs.STEP_PAUSE_LAYER
    assert decoded.target_layer_id == 2
    with pytest.raises(ValueError):
        cs.CueStep.layer_control(cs.STEP_SHOW_SCENE, layer_id=1)


def test_wait_flag_round_trips():
    step = cs.CueStep.hold(1.0, wait=True)
    decoded = cs.CueStep.from_hex(step.to_hex())
    assert decoded.wait is True
    assert decoded.kind == cs.STEP_HOLD


def test_raw_unknown_kind_round_trips_losslessly():
    # Cue Step Type 27 "Go if Analog Input" (0x1B) - deliberately not specially
    # modeled; must still round-trip exactly.
    raw = cs.CueStep(wait=False, kind=0x1B, params=(1, 0, 0, 1, 244, 4))
    decoded = cs.CueStep.from_hex(raw.to_hex())
    assert decoded == raw
    assert "0x1B" in cs.describe(decoded)
    assert "unsupported" in cs.describe(decoded)


def test_describe_covers_modeled_kinds():
    assert "Show Scene" in cs.describe(cs.CueStep.show_scene(fade_type=1, fade_seconds=0.2, hold_seconds=2.0))
    assert "Hold" in cs.describe(cs.CueStep.hold(1.5))
    assert "Go to step 4" in cs.describe(cs.CueStep.go_cue_step(4))
    assert "Layer A" in cs.describe(cs.CueStep.layer_control(cs.STEP_CLEAR_LAYER, layer_id=1))


def test_accessing_wrong_property_raises():
    step = cs.CueStep.hold(1.0)
    with pytest.raises(ValueError):
        _ = step.fade_type
    with pytest.raises(ValueError):
        _ = step.target_cue_list
