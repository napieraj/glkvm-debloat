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
from kvmd.pluginmgr.errors import VerifyError
from kvmd.pluginmgr.errors import code_of
from kvmd.pluginmgr.errors import CODE_VERIFY_REFUSED
from kvmd.pluginmgr.errors import CODE_VERIFY_UNCONFIGURED
from kvmd.pluginmgr.manifest import Manifest
from kvmd.pluginmgr.manifest import canonical_json
from kvmd.pluginmgr.manifest import parse_manifest
from kvmd.pluginmgr.verifier import Verifier
from kvmd.pluginmgr.verifier import resolve
from kvmd.pluginmgr.gate import gate
from kvmd.pluginmgr.gate import gate_named

from .vectors import load_cases
from .vectors import load_blob
from .vectors import case_ids


# =====
class AlwaysFailVerifier(Verifier):
    """
    Refuses everything. Test-only on purpose: it lives under testenv/tests so
    it can never be reached from kvmd, and resolve() does not know its name.
    """

    @property
    def name(self) -> str:
        return "always-fail"

    def verify(self, manifest: Manifest, payload: bytes) -> None:
        raise VerifyError(CODE_VERIFY_REFUSED, "always-fail verifier")


_CASES = load_cases("verify.json")


@pytest.mark.parametrize("case", _CASES, ids=case_ids(_CASES))
def test_verify_gate_vector(case: dict) -> None:
    manifest = parse_manifest(canonical_json(case["manifest"]))
    payload = load_blob(case["payload_blob"])

    try:
        # "always-fail" is never resolvable by name; every other name goes
        # through resolve() so that fail-closed behaviour is exercised too.
        if case["verifier"] == "always-fail":
            gate(AlwaysFailVerifier(), manifest, payload)
        else:
            gate_named(case["verifier"], manifest, payload)
    except RefusalError as ex:
        assert case["expect"] == "refuse", \
            f"expected accept, refused with {code_of(ex)!r} ({ex}) -- {case['description']}"
        assert code_of(ex) == case["code"], \
            f"refusal code {code_of(ex)!r}, want {case['code']!r} ({ex}) -- {case['description']}"
        return

    assert case["expect"] == "accept", \
        f"expected refusal {case.get('code')!r}, got accept -- {case['description']}"


def test_always_fail_is_not_resolvable() -> None:
    # The test-only verifier must not be reachable through configuration.
    with pytest.raises(RefusalError) as ex:
        resolve("always-fail")
    assert ex.value.code == CODE_VERIFY_UNCONFIGURED


def test_gate_without_verifier_refuses() -> None:
    with pytest.raises(RefusalError) as ex:
        gate(None, None, b"")
    assert ex.value.code == CODE_VERIFY_UNCONFIGURED
