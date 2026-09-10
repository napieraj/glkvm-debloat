# ========================================================================== #
#                                                                            #
#    KVMD - The main PiKVM daemon.                                           #
#                                                                            #
#    Copyright (C) 2018-2024  Maxim Devaev <mdevaev@gmail.com>               #
#                                                                            #
#    This program is free software: you can redistribute it and/or modify    #
#    it under the terms of the GNU General Public License as published by    #
#    the Free Software Foundation, either version 3 of the License, or       #
#    (at your option) any later version.                                     #
#                                                                            #
#    This program is distributed in the hope that it will be useful,         #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of          #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the           #
#    GNU General Public License for more details.                            #
#                                                                            #
#    You should have received a copy of the GNU General Public License       #
#    along with this program.  If not, see <https://www.gnu.org/licenses/>.  #
#                                                                            #
# ========================================================================== #


import json
import struct
import dataclasses

from typing import Any

from .errors import RefusalError
from .errors import CODE_PAYLOAD_TOO_LARGE
from .errors import CODE_WIRE_BAD_FRAME
from .errors import CODE_WIRE_BAD_FLAGS
from .errors import CODE_WIRE_BAD_SEQUENCE
from .errors import CODE_WIRE_CHUNK_TOO_LARGE
from .errors import CODE_MALFORMED
from .errors import CODE_UNSUPPORTED_VERSION
from .manifest import canonical_json


# =====
# Wire constants. See contract/plugins/wire.md.

# Sits in the custom-extension range kazbek already reserves above the upstream
# rtty message types (0xF0 is DEVICE_INFO). Upstream runs 0x00-0x09; keeping
# extensions at 0xF0+ leaves room for upstream to grow without collision.
MSG_TYPE_PLUGIN = 0xF1

# Matches the existing 32-byte sid convention used by the login/termdata/file
# messages, so device-side framing keeps its shape.
TID_LEN = 32

# tid + sub.
HEADER_LEN = TID_LEN + 1

# Caps the data bytes in one payload chunk. The uint16 envelope would permit
# 65502; 32768 leaves clear headroom and is a size this device can buffer
# without thought.
PAYLOAD_CHUNK_MAX = 32768

# seq(4) + flags(1), on top of HEADER_LEN.
CHUNK_HEADER_LEN = 5

# Marks the final payload chunk. All other bits must be zero.
FLAG_LAST = 0x01

# Carried as "v" in every JSON body.
#
# v2 differs from v1 by three manifest changes: a mandatory monotonic revision,
# a structured and required signature block, and capabilities renamed to
# sandbox and reserved. Because unknown manifest fields are refused rather than
# ignored, none of the three could be added compatibly -- which is the bump
# working as designed.
PROTOCOL_VERSION = 2

SUB_OFFER = 0x00
SUB_FETCH = 0x01
SUB_PAYLOAD = 0x02
SUB_INSTALL_RESULT = 0x03
SUB_READBACK = 0x04
_SUB_MAX = SUB_READBACK

# Install result states. "refused" and "failed" are deliberately distinct:
# refused means the plugin never touched the disk and is the observable
# signature of invariant 3, while failed means the disk was touched and then
# restored.
STATE_INSTALLED = "installed"
STATE_NOOP = "noop"
STATE_REFUSED = "refused"
STATE_FAILED = "failed"


@dataclasses.dataclass(frozen=True)
class Frame:
    tid: str
    sub: int
    body: bytes  # sub-type specific: canonical JSON, or a payload chunk


@dataclasses.dataclass(frozen=True)
class Chunk:
    seq: int
    flags: int
    data: bytes

    @property
    def last(self) -> bool:
        return bool(self.flags & FLAG_LAST)


def encode_frame(tid: str, sub: int, body: bytes) -> bytes:
    """
    Builds a complete wire frame including the rtty envelope.
    """

    if len(tid) != TID_LEN:
        raise RefusalError(CODE_WIRE_BAD_FRAME, f"tid is {len(tid)} bytes, want {TID_LEN}")
    inner = HEADER_LEN + len(body)
    if inner > 0xFFFF:
        # The envelope's length field is a uint16. This is the single hardest
        # constraint on the design and is why payloads are chunked at all.
        raise RefusalError(CODE_WIRE_BAD_FRAME, f"body {inner} bytes exceeds the uint16 envelope")
    return struct.pack(">BH", MSG_TYPE_PLUGIN, inner) + tid.encode("ascii") + bytes([sub]) + body


def decode_frame(raw: bytes) -> Frame:
    """
    Parses a complete wire frame, envelope included.
    """

    if len(raw) < 3:
        raise RefusalError(CODE_WIRE_BAD_FRAME, "frame shorter than the envelope")
    (msg_type, msg_len) = struct.unpack(">BH", raw[:3])
    if msg_type != MSG_TYPE_PLUGIN:
        raise RefusalError(CODE_WIRE_BAD_FRAME, f"message type 0x{msg_type:02x} is not a plugin frame")
    if len(raw) - 3 != msg_len:
        raise RefusalError(CODE_WIRE_BAD_FRAME, f"envelope claims {msg_len} bytes, got {len(raw) - 3}")
    return decode_body(raw[3:])


def decode_body(body: bytes) -> Frame:
    """
    Parses a plugin body once the rtty envelope has been stripped.
    """

    if len(body) < HEADER_LEN:
        # A short read drops the connection, as every other message type in
        # this protocol already does.
        raise RefusalError(CODE_WIRE_BAD_FRAME, f"body {len(body)} bytes, need at least {HEADER_LEN}")
    sub = body[TID_LEN]
    if sub > _SUB_MAX:
        raise RefusalError(CODE_WIRE_BAD_FRAME, f"unknown sub-type 0x{sub:02x}")
    return Frame(tid=body[:TID_LEN].decode("ascii", "replace"), sub=sub, body=body[HEADER_LEN:])


def encode_chunk(seq: int, last: bool, data: bytes) -> bytes:
    """
    Builds a payload chunk body (the part after tid+sub).
    """

    if len(data) > PAYLOAD_CHUNK_MAX:
        raise RefusalError(CODE_WIRE_CHUNK_TOO_LARGE, f"chunk {len(data)} bytes exceeds {PAYLOAD_CHUNK_MAX}")
    return struct.pack(">IB", seq, (FLAG_LAST if last else 0)) + data


def decode_chunk(body: bytes) -> Chunk:
    """
    Parses a payload chunk body.
    """

    if len(body) < CHUNK_HEADER_LEN:
        raise RefusalError(CODE_WIRE_BAD_FRAME,
                           f"chunk body {len(body)} bytes, need at least {CHUNK_HEADER_LEN}")
    (seq, flags) = struct.unpack(">IB", body[:CHUNK_HEADER_LEN])
    if flags & ~FLAG_LAST:
        # Refusing unknown bits is what stops a flag added later from being
        # silently ignored by an old device.
        raise RefusalError(CODE_WIRE_BAD_FLAGS, f"unknown flags bits in 0x{flags:02x}")
    data = body[CHUNK_HEADER_LEN:]
    if len(data) > PAYLOAD_CHUNK_MAX:
        raise RefusalError(CODE_WIRE_CHUNK_TOO_LARGE, f"chunk {len(data)} bytes exceeds {PAYLOAD_CHUNK_MAX}")
    return Chunk(seq=seq, flags=flags, data=data)


def encode_json_body(obj: Any) -> bytes:
    """
    Encodes a JSON message body in canonical form, stamping the protocol
    version so no caller can forget it.
    """

    return canonical_json({**obj, "v": PROTOCOL_VERSION})


def decode_json_body(body: bytes) -> dict:
    """
    Parses a JSON message body and enforces the protocol version.

    A receiver that does not recognise "v" refuses rather than guessing: a
    message from a future protocol is not a message with unknown fields to
    ignore, it is a message whose meaning is unknown.
    """

    try:
        obj = json.loads(body)
    except ValueError as ex:
        raise RefusalError(CODE_MALFORMED, f"body is not JSON: {ex}")
    if not isinstance(obj, dict):
        raise RefusalError(CODE_MALFORMED, "body is not a JSON object")
    if obj.get("v") != PROTOCOL_VERSION:
        raise RefusalError(CODE_UNSUPPORTED_VERSION, f"body version {obj.get('v')!r}")
    return obj


class Reassembler:
    """
    Accumulates payload chunks into a bundle.

    It does not reorder: a gap or a repeat drops the transfer. Ordering is the
    tunnel's job, and a receiver that quietly repairs sequence errors hides a
    real fault.
    """

    def __init__(self, max_total: int) -> None:
        # Bounds the total accepted bytes, so a peer cannot stream unbounded
        # data by never setting LAST.
        self.__max_total = max_total
        self.__buf = bytearray()
        self.__next = 0
        self.__done = False

    def push(self, chunk: Chunk) -> bool:
        """
        Adds a chunk and reports whether the transfer is complete.
        """

        if self.__done:
            raise RefusalError(CODE_WIRE_BAD_SEQUENCE, f"chunk {chunk.seq} after LAST")
        if chunk.seq != self.__next:
            raise RefusalError(CODE_WIRE_BAD_SEQUENCE, f"expected seq {self.__next}, got {chunk.seq}")
        if len(self.__buf) + len(chunk.data) > self.__max_total:
            raise RefusalError(CODE_PAYLOAD_TOO_LARGE, f"transfer exceeds {self.__max_total} bytes")
        self.__buf += chunk.data
        self.__next += 1
        self.__done = chunk.last
        return self.__done

    @property
    def complete(self) -> bool:
        return self.__done

    def bytes(self) -> bytes:
        """
        The assembled bundle. Only meaningful once push() has reported completion.
        """

        return bytes(self.__buf)
