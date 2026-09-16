"""Wire framing for the LanBox Serial & Network command protocol.

Reference: "LanBox Reference Chart Version 3.04", section "Serial & Network
Commands". The protocol is pure ASCII (no binary bytes): every request is

    '*' <command-code-hex> <param-hex...> '#'

and every reply is either:

    '>'                      -- accepted, no data
    '?'                      -- rejected / not understood / incomplete
    '*' <data-hex...> '#' '>' -- accepted, with data, followed by the ready prompt

8-bit values are 2 hex characters, 16-bit values are 4 hex characters,
big-endian. All hex digits are sent as their uppercase ASCII characters.
"""

from __future__ import annotations

from dataclasses import dataclass

START = 0x2A  # '*'
END = 0x23  # '#'
PROMPT_OK = 0x3E  # '>'
PROMPT_ERROR = 0x3F  # '?'

_HEX_DIGITS = "0123456789ABCDEF"


def hex8(value: int) -> str:
    """Encode an 8-bit value as 2 hex characters."""
    if not 0 <= value <= 0xFF:
        raise ValueError(f"value {value!r} does not fit in 8 bits")
    return f"{value:02X}"


def hex16(value: int) -> str:
    """Encode a 16-bit value as 4 hex characters."""
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"value {value!r} does not fit in 16 bits")
    return f"{value:04X}"


def parse_hex(chunk: str) -> int:
    """Parse a hex chunk of any (even) length into an int."""
    if not chunk or len(chunk) % 2 != 0 or any(c.upper() not in _HEX_DIGITS for c in chunk):
        raise ProtocolFramingError(f"invalid hex chunk: {chunk!r}")
    return int(chunk, 16)


class ProtocolFramingError(Exception):
    """Malformed framing data - kept local to avoid a circular import with errors.py."""


def encode_request(code: str, *hex_parts: str) -> bytes:
    """Build a full '*<code><params>#' request frame as raw bytes."""
    body = code + "".join(hex_parts)
    if not body or any(c.upper() not in _HEX_DIGITS for c in body):
        raise ProtocolFramingError(f"invalid request body: {body!r}")
    return b"*" + body.upper().encode("ascii") + b"#"


def encode_password(password: str) -> bytes:
    """Build the plain-text password + CR line sent to authenticate."""
    return password.encode("ascii") + b"\r"


@dataclass(frozen=True)
class Reply:
    """A parsed reply from the LanBox: either an error, or optional data."""

    ok: bool
    data: str | None  # raw hex payload between '*' and '#', or None

    @property
    def fields(self) -> list[tuple[str, int]]:
        """Split the raw hex payload into consecutive byte pairs (rarely used directly)."""
        if self.data is None:
            return []
        return [(self.data[i : i + 2], i // 2) for i in range(0, len(self.data), 2)]


class ReplyReader:
    """Incrementally feeds raw bytes and yields complete `Reply` objects.

    Usage: feed bytes as they arrive from the transport via `feed()`, then
    drain any complete replies with `pop_ready()`.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)

    def pop_ready(self) -> list[Reply]:
        replies: list[Reply] = []
        while self._buffer:
            first = self._buffer[0]
            if first == PROMPT_OK:
                replies.append(Reply(ok=True, data=None))
                del self._buffer[0]
            elif first == PROMPT_ERROR:
                replies.append(Reply(ok=False, data=None))
                del self._buffer[0]
            elif first == START:
                end_index = self._buffer.find(bytes([END]))
                if end_index == -1:
                    break  # frame not fully received yet
                data = self._buffer[1:end_index].decode("ascii")
                # The data frame is always followed by the ready prompt.
                if len(self._buffer) <= end_index + 1:
                    break  # wait for the trailing prompt byte
                trailing = self._buffer[end_index + 1]
                if trailing not in (PROMPT_OK, PROMPT_ERROR):
                    raise ProtocolFramingError(
                        f"expected prompt after data frame, got {trailing!r}"
                    )
                replies.append(Reply(ok=trailing == PROMPT_OK, data=data))
                del self._buffer[: end_index + 2]
            else:
                raise ProtocolFramingError(f"unexpected byte at start of reply: {first!r}")
        return replies


def read_fields(hex_string: str, spec: list[tuple[str, int]]) -> tuple[dict[str, int], str]:
    """Consume fixed-width fields from the front of a hex string.

    `spec` is a list of (field_name, width_in_bytes). Returns the parsed
    dict plus whatever hex remains unconsumed (for repeated/variable-length
    structures such as per-layer or per-channel lists).
    """
    values: dict[str, int] = {}
    pos = 0
    for name, width_bytes in spec:
        width_chars = width_bytes * 2
        chunk = hex_string[pos : pos + width_chars]
        if len(chunk) != width_chars:
            raise ProtocolFramingError(
                f"not enough data for field {name!r}: expected {width_chars} hex chars, "
                f"got {chunk!r}"
            )
        values[name] = parse_hex(chunk)
        pos += width_chars
    return values, hex_string[pos:]


_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def layer_id_to_label(layer_id: int) -> str:
    """Convert a numeric Layer ID (1-63) to its letter label (A-Z, then AA-BK)."""
    if not 1 <= layer_id <= 63:
        raise ValueError(f"layer id {layer_id!r} out of range 1-63")
    n = layer_id
    label = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        label = _LETTERS[remainder] + label
    return label


def layer_label_to_id(label: str) -> int:
    """Convert a Layer letter label (A-Z, AA-BK) back to its numeric ID."""
    label = label.upper()
    if not label or any(c not in _LETTERS for c in label):
        raise ValueError(f"invalid layer label: {label!r}")
    n = 0
    for c in label:
        n = n * 26 + (_LETTERS.index(c) + 1)
    if not 1 <= n <= 63:
        raise ValueError(f"layer label {label!r} decodes out of range 1-63")
    return n
