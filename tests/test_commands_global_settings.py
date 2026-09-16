import pytest

from lanbox_tui.protocol import commands
from lanbox_tui.protocol.errors import CommandRejected
from lanbox_tui.protocol.framing import Reply, hex8, hex16


def test_get_global_data_request():
    assert commands.build_get_global_data() == b"*0B#"


def test_get_global_data_parses_pdf_example():
    # "Get the Global Settings of the LanBox" (p.51): Baud Rate Fixed MIDI
    # (0x83), DMX Out Offset 0, 512 DMX Channels, Network Name "Demo-LCX"
    # (length 8, padded to the fixed 13-byte field), SysEx Device ID 2,
    # IP 192.168.1.76, Subnet 255.255.255.0, Gateway 192.168.1.1.
    # NOTE: the PDF's own caption says IP ".77", but the hex (0x4C = 76)
    # and the separate CommonSetIpConfig example (using the same bytes,
    # captioned ".76") show ".77" is a typo in that one caption.
    name = "Demo-LCX"
    name_hex = "".join(hex8(ord(c)) for c in name) + "00" * (13 - len(name))
    data = (
        hex8(0x83)
        + hex16(0x0000)
        + hex16(0x0200)
        + hex8(len(name))
        + name_hex
        + hex8(0x02)
        + hex8(0xC0) + hex8(0xA8) + hex8(0x01) + hex8(0x4C)
        + hex8(0xFF) + hex8(0xFF) + hex8(0xFF) + hex8(0x00)
        + hex8(0xC0) + hex8(0xA8) + hex8(0x01) + hex8(0x01)
    )
    result = commands.parse_get_global_data(Reply(ok=True, data=data))
    assert result.baud_rate_param == 0x83
    assert result.dmx_out_offset == 0
    assert result.dmx_channel_count == 0x0200
    assert result.name == "Demo-LCX"
    assert result.sysex_device_id == 2
    assert result.ip_address == (192, 168, 1, 76)
    assert result.subnet_mask == (255, 255, 255, 0)
    assert result.gateway == (192, 168, 1, 1)


def test_set_baud_rate_matches_pdf_example():
    # "Set the Baud Rate of the LanBox Serial MIDI Port to 9600" -> "* 0006 02 #"
    assert commands.build_set_baud_rate(2) == b"*000602#"


def test_set_dmx_offset_matches_pdf_example():
    # "Set the DMX Out Offset of the LanBox to 256" -> "* 6A 0100 #"
    assert commands.build_set_dmx_offset(256) == b"*6A0100#"


def test_set_num_dmx_channels_matches_pdf_example():
    # "Set the Number of DMX Out Channels of the LanBox to 255" -> "* 69 00FF #"
    assert commands.build_set_num_dmx_channels(255) == b"*6900FF#"


def test_set_name_matches_pdf_example():
    # "Set a new name for the LanBox to 'Lanbox LCX1'" -> "* AE 4C 61 6E 62 6F 78 20 4C 43 58 31 #"
    assert commands.build_set_name("Lanbox LCX1") == b"*AE4C616E626F78204C435831#"


def test_set_name_rejects_too_long():
    with pytest.raises(ValueError):
        commands.build_set_name("x" * 14)


def test_set_password_matches_pdf_example():
    # "Set a new password for the LanBox to 1012" -> "* AF 03F4 #"
    assert commands.build_set_password(1012) == b"*AF03F4#"


def test_set_ip_config_matches_pdf_example():
    # "Set IP settings of the LanBox to 192.168.1.76, 255.255.0.0, 192.168.1.1"
    # -> "* B0 C0A8014C FFFF0000 C0A80101 #"
    request = commands.build_set_ip_config(
        ip=(192, 168, 1, 76), subnet=(255, 255, 0, 0), gateway=(192, 168, 1, 1)
    )
    assert request == b"*B0C0A8014CFFFF0000C0A80101#"


def test_reboot_and_save_data_requests():
    assert commands.build_reboot() == b"*B5#"
    assert commands.build_save_data() == b"*A9#"


@pytest.mark.parametrize(
    "parse_fn",
    [
        commands.parse_set_name,
        commands.parse_set_password,
        commands.parse_set_dmx_offset,
        commands.parse_set_num_dmx_channels,
        commands.parse_set_ip_config,
        commands.parse_set_baud_rate,
        commands.parse_reboot,
        commands.parse_save_data,
    ],
)
def test_global_settings_replies_reject_on_error(parse_fn):
    with pytest.raises(CommandRejected):
        parse_fn(Reply(ok=False, data=None))
