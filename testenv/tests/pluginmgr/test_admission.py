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


import pytest

from kvmd.pluginmgr.errors import RefusalError
from kvmd.pluginmgr.errors import code_of
from kvmd.pluginmgr.errors import CODE_PAYLOAD_TOO_LARGE
from kvmd.pluginmgr.manifest import canonical_json
from kvmd.pluginmgr.manifest import parse_manifest
from kvmd.pluginmgr.gate import admit_offer

from .vectors import load_cases
from .vectors import case_ids


# =====
_CASES = load_cases("admission.json")


@pytest.mark.parametrize("case", _CASES, ids=case_ids(_CASES))
def test_admission_vector(case: dict) -> None:
    """
    Admission runs on the offer alone, before a fetch is sent and before any
    chunk moves. It neither sees nor needs the payload -- which is exactly what
    distinguishes it from the verify gate.
    """

    try:
        admit_offer(parse_manifest(canonical_json(case["manifest"])))
    except RefusalError as ex:
        assert case["expect"] == "refuse", \
            f"expected admit, refused with {code_of(ex)!r} ({ex}) -- {case['description']}"
        assert code_of(ex) == case["code"], \
            f"refusal code {code_of(ex)!r}, want {case['code']!r} ({ex}) -- {case['description']}"
        return
    assert case["expect"] == "admit", \
        f"expected refusal {case.get('code')!r}, got admit -- {case['description']}"


def test_admission_precedes_transfer() -> None:
    """
    States the ordering claim directly: an oversized declaration is refused
    without the payload existing at all. gate() step 2 could not make this
    call, because it has nothing to measure until the bytes have already
    crossed the wire.
    """

    manifest = parse_manifest(canonical_json({
        "entry": "plugins/ugpio/big.py",
        "firmware_compat": "*",
        "model_compat": "*",
        "name": "big",
        "payload": {"sha256": "0" * 64, "size": 8388609},
        "runtime": "device",
        "type": "ugpio",
    }))
    with pytest.raises(RefusalError) as ex:
        admit_offer(manifest)
    assert ex.value.code == CODE_PAYLOAD_TOO_LARGE


def test_admission_needs_no_payload() -> None:
    # Admission's signature takes no payload at all, which is what makes the
    # "before the first chunk" claim structural rather than a convention.
    manifest = parse_manifest(canonical_json({
        "entry": "plugins/ugpio/ok.py",
        "firmware_compat": "*",
        "model_compat": "*",
        "name": "ok",
        "payload": {"sha256": "0" * 64, "size": 1},
        "runtime": "device",
        "type": "ugpio",
    }))
    admit_offer(manifest)
