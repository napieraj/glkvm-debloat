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

import pytest

from kvmd.pluginmgr import wire
from kvmd.pluginmgr.errors import RefusalError
from kvmd.pluginmgr.errors import code_of
from kvmd.pluginmgr.errors import CODE_WIRE_BAD_SEQUENCE
from kvmd.pluginmgr.errors import CODE_MALFORMED
from kvmd.pluginmgr.errors import CODE_UNSUPPORTED_VERSION
from kvmd.pluginmgr.manifest import canonical_json

from .vectors import load_vectors
from .vectors import load_cases
from .vectors import case_ids
from .vectors import b64


# =====
_VECTORS = load_vectors("frames.json")
_CASES = load_cases("frames.json")


def test_frame_constants() -> None:
    # Pins the wire constants to the contract, so a local edit to either
    # cannot drift silently.
    assert wire.MSG_TYPE_PLUGIN == _VECTORS["msg_type"]
    assert wire.PAYLOAD_CHUNK_MAX == _VECTORS["payload_chunk_max"]
    assert wire.TID_LEN == _VECTORS["tid_len"]


def _build(case: dict) -> bytes:
    if "hex" in case:
        return bytes.fromhex(case["hex"])
    con = case["construct"]
    rep = con["data_repeat"]
    body = wire.encode_chunk(con["seq"], bool(con["flags"] & wire.FLAG_LAST),
                             bytes([rep["byte"]]) * rep["count"])
    return wire.encode_frame(con["tid"], con["sub"], body)


@pytest.mark.parametrize("case", _CASES, ids=case_ids(_CASES))
def test_frame_vector(case: dict) -> None:
    try:
        raw = _build(case)
        frame = wire.decode_frame(raw)
        chunk = (wire.decode_chunk(frame.body) if frame.sub == wire.SUB_PAYLOAD else None)
    except RefusalError as ex:
        # An oversized chunk is refused at encode as well as at decode; either
        # end of the wire is a valid place to catch it.
        assert "code" in case, f"unexpected refusal {code_of(ex)!r} ({ex}) -- {case['description']}"
        assert code_of(ex) == case["code"], \
            f"refusal code {code_of(ex)!r}, want {case['code']!r} ({ex}) -- {case['description']}"
        return

    assert "code" not in case, f"expected refusal {case.get('code')!r}, decoded -- {case['description']}"

    decoded = case.get("decoded")
    if decoded is None:
        return
    assert frame.tid == decoded["tid"]
    assert frame.sub == decoded["sub"]

    if "json" in decoded:
        body = json.loads(frame.body)
        assert body == decoded["json"]
        # The body must already be canonical on the wire: re-encoding the
        # decode has to reproduce the exact bytes, or the two languages cannot
        # hash the same message to the same value.
        assert canonical_json(body) == frame.body

    if "seq" in decoded:
        assert chunk is not None
        assert chunk.seq == decoded["seq"]
        assert chunk.flags == decoded["flags"]
        if "data_b64" in decoded:
            assert chunk.data == b64(decoded["data_b64"])

    if "hex" in case:
        # Round-trip: re-encoding the decoded frame reproduces the bytes.
        assert wire.encode_frame(frame.tid, frame.sub, frame.body) == raw


# =====
def test_reassembler_joins_chunks() -> None:
    payload = bytes(range(256)) * 300  # spans several chunks
    asm = wire.Reassembler(len(payload))
    chunks = [payload[i:i + wire.PAYLOAD_CHUNK_MAX] for i in range(0, len(payload), wire.PAYLOAD_CHUNK_MAX)]
    for (seq, data) in enumerate(chunks):
        done = asm.push(wire.decode_chunk(wire.encode_chunk(seq, seq == len(chunks) - 1, data)))
    assert done
    assert asm.complete
    assert asm.bytes() == payload


def test_reassembler_refuses_sequence_gap() -> None:
    asm = wire.Reassembler(1024)
    asm.push(wire.decode_chunk(wire.encode_chunk(0, False, b"a")))
    with pytest.raises(RefusalError) as ex:
        # Ordering is the tunnel's job; a receiver that quietly repairs
        # sequence errors hides a real fault.
        asm.push(wire.decode_chunk(wire.encode_chunk(2, True, b"c")))
    assert ex.value.code == CODE_WIRE_BAD_SEQUENCE


def test_reassembler_refuses_repeat() -> None:
    asm = wire.Reassembler(1024)
    asm.push(wire.decode_chunk(wire.encode_chunk(0, False, b"a")))
    with pytest.raises(RefusalError) as ex:
        asm.push(wire.decode_chunk(wire.encode_chunk(0, True, b"a")))
    assert ex.value.code == CODE_WIRE_BAD_SEQUENCE


def test_reassembler_refuses_after_last() -> None:
    asm = wire.Reassembler(1024)
    asm.push(wire.decode_chunk(wire.encode_chunk(0, True, b"a")))
    with pytest.raises(RefusalError) as ex:
        asm.push(wire.decode_chunk(wire.encode_chunk(1, True, b"b")))
    assert ex.value.code == CODE_WIRE_BAD_SEQUENCE


def test_reassembler_bounds_total() -> None:
    # A peer must not be able to stream unbounded data by never setting LAST.
    asm = wire.Reassembler(4)
    with pytest.raises(RefusalError):
        asm.push(wire.decode_chunk(wire.encode_chunk(0, False, b"12345")))


# =====
def test_sub_types_match_contract() -> None:
    # The numbering is wire-visible: a renumber silently breaks every deployed
    # device, so it is pinned here rather than left to the enum's order.
    assert (wire.SUB_OFFER, wire.SUB_FETCH, wire.SUB_PAYLOAD,
            wire.SUB_INSTALL_RESULT, wire.SUB_READBACK) == (0x00, 0x01, 0x02, 0x03, 0x04)
    subs = {case["decoded"]["sub"] for case in _CASES if "decoded" in case}
    assert subs <= {wire.SUB_OFFER, wire.SUB_FETCH, wire.SUB_PAYLOAD,
                    wire.SUB_INSTALL_RESULT, wire.SUB_READBACK}


def test_install_states_match_contract() -> None:
    # "refused" and "failed" must stay distinct: refused is the observable
    # signature of invariant 3 (nothing touched the disk), and collapsing them
    # would make that invariant untestable from the server's side.
    assert {wire.STATE_INSTALLED, wire.STATE_NOOP, wire.STATE_REFUSED, wire.STATE_FAILED} == \
        {"installed", "noop", "refused", "failed"}
    states = {
        json.loads(bytes.fromhex(case["hex"])[3 + wire.HEADER_LEN:])["state"]
        for case in _CASES
        if "hex" in case and case.get("decoded", {}).get("sub") == wire.SUB_INSTALL_RESULT
    }
    assert states == {"installed", "noop", "refused", "failed"}


# =====
def test_json_body_round_trips_with_version() -> None:
    body = wire.encode_json_body({"sha256": "a" * 64})
    assert body == b'{"sha256":"' + b"a" * 64 + b'","v":1}'
    assert wire.decode_json_body(body) == {"sha256": "a" * 64, "v": 1}


def test_json_body_refuses_unknown_version() -> None:
    # A message from a future protocol is not a message with unknown fields to
    # ignore; it is a message whose meaning is unknown.
    with pytest.raises(RefusalError) as ex:
        wire.decode_json_body(b'{"sha256":"x","v":2}')
    assert ex.value.code == CODE_UNSUPPORTED_VERSION


def test_json_body_refuses_missing_version() -> None:
    with pytest.raises(RefusalError) as ex:
        wire.decode_json_body(b'{"sha256":"x"}')
    assert ex.value.code == CODE_UNSUPPORTED_VERSION


def test_json_body_refuses_non_json() -> None:
    with pytest.raises(RefusalError) as ex:
        wire.decode_json_body(b"not json")
    assert ex.value.code == CODE_MALFORMED


def test_json_body_refuses_a_non_object() -> None:
    with pytest.raises(RefusalError) as ex:
        wire.decode_json_body(b"[1,2,3]")
    assert ex.value.code == CODE_MALFORMED


def test_vector_bodies_carry_version_one() -> None:
    # Every JSON body in the contract must be decodable by the version check,
    # which is the cheapest way to catch a vector generated without "v".
    for case in _CASES:
        decoded = case.get("decoded", {})
        if "json" not in decoded:
            continue
        raw = bytes.fromhex(case["hex"])[3 + wire.HEADER_LEN:]
        assert wire.decode_json_body(raw)["v"] == wire.PROTOCOL_VERSION, case["id"]
