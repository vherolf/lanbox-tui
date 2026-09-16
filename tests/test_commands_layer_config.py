import pytest

from lanbox_tui.protocol import commands
from lanbox_tui.protocol.errors import CommandRejected
from lanbox_tui.protocol.framing import Reply


def test_layer_set_id_matches_pdf_example():
    # "Change the ID of Layer A to AA" -> "* 45 01 1B #"
    assert commands.build_set_layer_id(0x01, 0x1B) == b"*45011B#"


def test_layer_set_output_matches_pdf_example():
    # "Set output of Layer E to Off" -> "* 48 05 00 #"
    assert commands.build_set_layer_output(0x05, False) == b"*480500#"


def test_layer_set_fading_round_trips():
    assert commands.build_set_layer_fading(0x20, True) == b"*4620FF#"
    assert commands.build_set_layer_fading(0x20, False) == b"*462000#"


def test_layer_set_solo_matches_pdf_example():
    # "Set Solo Mode of Layer R to Off" -> "* 4A 12 00 #"
    assert commands.build_set_layer_solo(0x12, False) == b"*4A1200#"


def test_layer_set_auto_output_uses_pdf_layer_id():
    # "Set Auto Output of Layer C to On" -> Layer C is 0x03. The PDF's own
    # example uses 0x01 for "On" (any nonzero value is valid per spec); this
    # implementation always emits 0xFF for True.
    assert commands.build_set_layer_auto_output(0x03, True) == b"*6403FF#"


def test_layer_set_locked_uses_pdf_layer_id():
    # "Set the Locked attribute of Layer Y to On" -> Layer Y is 0x19
    assert commands.build_set_layer_locked(0x19, True) == b"*4319FF#"


def test_layer_set_mix_mode_matches_pdf_example():
    # "Set Mix Mode of Layer AH to Transparent" -> "* 47 22 04 #"
    assert commands.build_set_layer_mix_mode(0x22, 4) == b"*472204#"


def test_layer_set_transparency_depth_matches_pdf_example():
    # "Set the Transparency depth of Layer BJ to 20%" -> "* 63 3E 33 #"
    assert commands.build_set_layer_transparency_depth(0x3E, 0x33) == b"*633E33#"


def test_layer_set_chase_mode_matches_pdf_example():
    # "Set Layer V Chase mode to Loop Up" -> "* 4B 16 02#"
    assert commands.build_set_layer_chase_mode(0x16, 2) == b"*4B1602#"


def test_layer_set_chase_speed_matches_pdf_example():
    # "Set Chase Speed of Layer AR to 150%" -> "* 4C 2C AA#"
    assert commands.build_set_layer_chase_speed(0x2C, 0xAA) == b"*4C2CAA#"


def test_layer_set_fade_type_matches_pdf_example():
    # "Set Manual Fade Type of Layer AR to Cross Fade" -> "* 4D 17 03#"
    assert commands.build_set_layer_fade_type(0x17, 3) == b"*4D1703#"


def test_layer_set_fade_time_uses_pdf_layer_id():
    # "Set Manual Fade Time of Layer M to 1.5 seconds" -> Layer M is 0x0D.
    # NOTE: the PDF's own example claims this encodes as time code 0x03, but
    # Appendix A's table (already verified elsewhere, e.g. test_cue_steps.py)
    # says 0x03 = 0.15s and 0x18 = 1.50s - the worked example contradicts the
    # reference chart's own time-encoding table, so it's treated as a
    # documentation error and Appendix A is trusted instead.
    assert commands.build_set_layer_fade_time(0x0D, 1.5) == b"*4E0D18#"


@pytest.mark.parametrize(
    "builder",
    [
        commands.build_set_layer_id,
        commands.build_set_layer_output,
        commands.build_set_layer_mix_mode,
    ],
)
def test_layer_config_replies_reject_on_error(builder):
    with pytest.raises(CommandRejected):
        commands.parse_set_layer_id(Reply(ok=False, data=None))


def test_layer_configure_short_form_move_matches_pdf_example():
    # "Place Layer D above B" -> "* 44 02 04 #"
    assert commands.build_layer_configure_short(destination=0x02, source=0x04) == b"*440204#"


def test_layer_configure_short_form_delete_matches_pdf_example():
    # "Delete Layer AA" -> "* 44 1B 40 #"
    assert (
        commands.build_layer_configure_short(
            destination=0x1B, source=commands.LAYER_CONFIGURE_NEW_OR_DELETE_MARKER
        )
        == b"*441B40#"
    )


def test_layer_configure_long_form_create_matches_pdf_example():
    # "Place New Layer on top of Mixing Order, give it ID AA and stated
    # Attributes and start Cue List 265 at step 8" -> "* 44 40 00 1B 27 0109 08 #"
    request = commands.build_layer_configure_long(
        destination=commands.LAYER_CONFIGURE_NEW_OR_DELETE_MARKER,
        source=commands.LAYER_CONFIGURE_TOP_OF_MIXING_ORDER,
        layer_id=0x1B,
        attributes=0x27,
        start_cue_list=0x0109,
        start_cue_step=0x08,
    )
    assert request == b"*4440001B27010908#"


def test_layer_configure_rejects_on_error():
    with pytest.raises(CommandRejected):
        commands.parse_layer_configure(Reply(ok=False, data=None))
