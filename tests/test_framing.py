from lanbox_tui.protocol import framing
from lanbox_tui.protocol.framing import ProtocolFramingError, ReplyReader


def test_encode_request_matches_pdf_example():
    # "LanBox Reference Chart 3.04", ChannelSetData example:
    # * C9 01 07DF 7E # -> In Layer A, set Channel 2015 to Value 126
    request = framing.encode_request("C9", framing.hex8(1), framing.hex16(2015), framing.hex8(126))
    assert request == b"*C90107DF7E#"


def test_hex8_and_hex16_round_trip():
    assert framing.hex8(0) == "00"
    assert framing.hex8(255) == "FF"
    assert framing.hex16(2015) == "07DF"
    assert framing.parse_hex("07DF") == 2015
    assert framing.parse_hex("FF") == 255


def test_hex8_rejects_out_of_range():
    import pytest

    with pytest.raises(ValueError):
        framing.hex8(256)
    with pytest.raises(ValueError):
        framing.hex16(65536)


def test_reply_reader_no_data_ok():
    reader = ReplyReader()
    reader.feed(b">")
    (reply,) = reader.pop_ready()
    assert reply.ok is True
    assert reply.data is None


def test_reply_reader_error():
    reader = ReplyReader()
    reader.feed(b"?")
    (reply,) = reader.pop_ready()
    assert reply.ok is False
    assert reply.data is None


def test_reply_reader_data_frame_followed_by_prompt():
    # CommonGetAppID example reply: * F8 FD 00D3 # >
    reader = ReplyReader()
    reader.feed(b"*F8FD00D3#>")
    (reply,) = reader.pop_ready()
    assert reply.ok is True
    assert reply.data == "F8FD00D3"


def test_reply_reader_handles_partial_chunks():
    reader = ReplyReader()
    reader.feed(b"*F8FD")
    assert reader.pop_ready() == []
    reader.feed(b"00D3#")
    assert reader.pop_ready() == []  # still waiting on the trailing prompt byte
    reader.feed(b">")
    (reply,) = reader.pop_ready()
    assert reply.data == "F8FD00D3"


def test_reply_reader_multiple_replies_in_one_chunk():
    reader = ReplyReader()
    reader.feed(b">*0102#>?")
    replies = reader.pop_ready()
    assert [r.ok for r in replies] == [True, True, False]
    assert replies[1].data == "0102"


def test_reply_reader_rejects_garbage():
    reader = ReplyReader()
    reader.feed(b"X")
    try:
        reader.pop_ready()
        assert False, "expected ProtocolFramingError"
    except ProtocolFramingError:
        pass


def test_read_fields_consumes_in_order_and_returns_remainder():
    fields, remainder = framing.read_fields("5B01A7000102", [("nr", 1), ("id", 1), ("attr", 1)])
    assert fields == {"nr": 0x5B, "id": 0x01, "attr": 0xA7}
    assert remainder == "000102"


def test_layer_id_label_round_trip():
    assert framing.layer_id_to_label(1) == "A"
    assert framing.layer_id_to_label(26) == "Z"
    assert framing.layer_id_to_label(27) == "AA"
    assert framing.layer_id_to_label(63) == "BK"
    for layer_id in range(1, 64):
        label = framing.layer_id_to_label(layer_id)
        assert framing.layer_label_to_id(label) == layer_id
