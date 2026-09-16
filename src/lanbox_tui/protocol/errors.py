"""Exceptions raised by the LanBox protocol/transport/client layers."""


class LanBoxError(Exception):
    """Base class for all LanBox-related errors."""


class ProtocolError(LanBoxError):
    """Malformed data on the wire (framing/hex violations)."""


class CommandRejected(LanBoxError):
    """The LanBox replied with '?' (message not understood or not executed)."""


class NotConnectedError(LanBoxError):
    """An operation was attempted before connecting (or after disconnecting)."""


class AuthenticationError(LanBoxError):
    """The LanBox rejected the connection password."""
