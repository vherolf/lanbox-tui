from lanbox_tui.protocol import commands
from lanbox_tui.protocol.commands import LayerAttributes
from lanbox_tui.protocol.errors import CommandRejected
from lanbox_tui.protocol.framing import Reply

import pytest


def test_get_app_id_uses_four_char_command_code():
    # PDF general form: "* 0005 00 00 #"
    assert commands.build_get_app_id() == b"*0005 0000#".replace(b" ", b"")


def test_parse_app_id_matches_pdf_example():
    # PDF example reply: "* F8 FD 00D3 #>" -> LCX, firmware 2.11
    reply = Reply(ok=True, data="F8FD00D3")
    app_id = commands.parse_app_id(reply)
    assert app_id.device_code == 0xF8FD
    assert app_id.device_name == "LCX"
    assert app_id.firmware_version == pytest.approx(2.11)


def test_set_16bit_mode_request_bytes():
    assert commands.build_set_16bit_mode(True) == b"*65FF#"
    assert commands.build_set_16bit_mode(False) == b"*6500#"


def test_channel_set_data_matches_pdf_example():
    # "In Layer A, set Channel 2015 to a Value of 126" -> "*C9 01 07DF 7E#"
    request = commands.build_set_channel_data(layer=1, values={2015: 126})
    assert request == b"*C90107DF7E#"


def test_channel_read_data_parses_sequential_values():
    # PDF example: CD 01 0001 10 -> 16 sequential channel values starting at 1
    reply = Reply(ok=True, data="00F0AF56" + "00" * 12)
    values = commands.parse_read_channel_data(reply, start_channel=1)
    assert values[1] == 0x00
    assert values[2] == 0xF0
    assert values[3] == 0xAF
    assert values[4] == 0x56
    assert len(values) == 16


def test_channel_set_output_enable_all_channels():
    # "CA 02 00 00 FF" -> enable output of all channels in Layer B
    request = commands.build_set_channel_output_enable(layer=2, values={0: True})
    assert request == b"*CA020000FF#"


def test_get_layers_parses_two_layer_reply():
    # Derived from the CommonGetLayers worked example (first two layers only,
    # which the PDF spells out in full): Layer A (internal 0x5B) and Layer B
    # (internal 0x5C), both with attribute byte 0xA7.
    data = "5B01A700010225002333014C" + "5C02A7000201250000330071"
    reply = Reply(ok=True, data=data)
    layers = commands.parse_get_layers(reply)
    assert len(layers) == 2

    top = layers[0]
    assert top.internal_number == 0x5B
    assert top.layer_id == 1
    assert top.label == "A"
    assert top.attributes == LayerAttributes.from_byte(0xA7)
    assert top.attributes.output_enabled is True
    assert top.attributes.solo_mode is False
    assert top.active_cue_list == 1
    assert top.active_cue_step == 2

    second = layers[1]
    assert second.label == "B"
    assert second.active_cue_list == 2
    assert second.active_cue_step == 1


def test_rejected_reply_raises_command_rejected():
    with pytest.raises(CommandRejected):
        commands.parse_app_id(Reply(ok=False, data=None))


def test_channel_set_active_matches_pdf_examples():
    # "Disactivate channels 9 through 11 in Layer E" -> "* CC 05 00 09 00 00 0A 00 00 0B 00 #"
    request = commands.build_set_channel_active(5, {9: False, 10: False, 11: False})
    assert request == b"*CC05000900000A00000B00#"

    # "Activate all channels Layer B" -> "* CC 02 00 00 FF #"
    request = commands.build_set_channel_active(2, {0: True})
    assert request == b"*CC020000FF#"


def test_channel_set_solo_matches_pdf_examples():
    # "Disable Solo for channels 9 through 11 in Layer E" -> "* CB 05 00 09 00 00 0A 00 00 0B 00 #"
    request = commands.build_set_channel_solo(5, {9: False, 10: False, 11: False})
    assert request == b"*CB05000900000A00000B00#"

    # "Enable Solo for all channels Layer B" -> "* CB 02 00 00 FF #"
    request = commands.build_set_channel_solo(2, {0: True})
    assert request == b"*CB020000FF#"
