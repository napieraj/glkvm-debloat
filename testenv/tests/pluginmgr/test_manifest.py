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
from kvmd.pluginmgr.manifest import canonical_json
from kvmd.pluginmgr.manifest import parse_manifest
from kvmd.pluginmgr.manifest import compare_versions

from .vectors import load_cases
from .vectors import case_ids


# =====
_CASES = load_cases("manifest.json")


@pytest.mark.parametrize("case", _CASES, ids=case_ids(_CASES))
def test_manifest_vector(case: dict) -> None:
    data = (case["raw"].encode("utf-8") if "raw" in case else case["canonical"].encode("utf-8"))

    try:
        manifest = parse_manifest(data)
        manifest.validate()
    except RefusalError as ex:
        assert not case["valid"], \
            f"expected valid, refused with {code_of(ex)!r} ({ex}) -- {case['description']}"
        assert code_of(ex) == case["code"], \
            f"refusal code {code_of(ex)!r}, want {case['code']!r} ({ex}) -- {case['description']}"
        return

    assert case["valid"], f"expected refusal {case.get('code')!r}, got accept -- {case['description']}"
    # Canonical encoding must round-trip byte-stably, or the two languages
    # cannot hash the same manifest to the same value -- which the signing
    # module will depend on.
    assert manifest.canonical_json().decode("utf-8") == case["canonical"]


def test_canonical_json_compact_sorted() -> None:
    assert canonical_json({"b": 1, "a": [2, 3]}) == b'{"a":[2,3],"b":1}'


def test_canonical_json_no_html_escape() -> None:
    # Go escapes <, > and & by default; its encoder turns that off so the two
    # sides agree byte for byte. This pins the Python side of that agreement.
    assert canonical_json({"k": "<&>"}) == b'{"k":"<&>"}'


# =====
def test_compare_versions_orders_numerics() -> None:
    # Bytewise ordering would put "1.10.0" before "1.9.0", which is exactly the
    # bug a firmware_compat constraint must not have.
    assert compare_versions("1.10.0", "1.9.0") > 0
    assert compare_versions("1.9.0", "1.10.0") < 0
    assert compare_versions("1.10.0", "1.10.0") == 0


def test_compare_versions_bytewise_fallback() -> None:
    assert compare_versions("rm1pe", "rm4pe") < 0
    assert compare_versions("rm4pe", "rm1pe") > 0


def test_compare_versions_missing_segments() -> None:
    assert compare_versions("1.10", "1.10.0") < 0
    assert compare_versions("1.10.0", "1.10") > 0
