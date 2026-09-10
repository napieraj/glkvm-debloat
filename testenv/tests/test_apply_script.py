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


import os
import re


# =====
# apply_to_glkvm.sh must never deploy configs/kvmd/webauthn.json.
#
# That file is the empty REFERENCE credential store. Copying it onto an enrolled
# device replaces the credentials with an empty set: kvmd starts, the login page
# offers the security key, nothing matches, and the break-glass password is the
# only way back in. A silent lockout, produced by a script whose entire purpose
# is being safe to re-run.
#
# The hazard is currently latent -- the script copies only kvmd/ and the file
# lives under configs/ -- but docs/lean-plan.md step 14 extends the script to
# copy web/ and files under configs/. This test is the thing that fails when
# that change lands without the exclusion, which is the only moment at which
# anyone would otherwise find out.
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_SCRIPT = os.path.join(_ROOT, "apply_to_glkvm.sh")
_STORE = "webauthn.json"


def _script() -> str:
    with open(_SCRIPT, encoding="utf-8") as file:
        return file.read()


def test_ok__the_never_deploy_guard_is_present() -> None:
    text = _script()
    assert "NEVER_DEPLOY" in text, "the NEVER_DEPLOY guard was removed from apply_to_glkvm.sh"
    assert _STORE in text, f"{_STORE} is no longer named in the guard"


def test_ok__no_copy_of_the_reference_store() -> None:
    # Any scp/rsync line that mentions configs/ must also exclude the store.
    # Written against the shape of the line rather than an exact string so that
    # step 14's rewrite still trips it.
    text = _script()
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not re.search(r"\b(scp|rsync)\b", stripped):
            continue
        if "configs" not in stripped:
            continue
        assert ("exclude" in stripped or _STORE in stripped), (
            "apply_to_glkvm.sh copies configs/ without excluding"
            f" {_STORE}, which silently wipes an enrolled device's"
            f" credentials: {stripped!r}"
        )


def test_ok__the_reference_store_is_not_under_the_copied_tree() -> None:
    # The guard's cheap half: as long as the store lives under configs/ and the
    # script copies kvmd/, it cannot be reached by accident.
    assert os.path.exists(os.path.join(_ROOT, "configs", "kvmd", _STORE))
    assert not os.path.exists(os.path.join(_ROOT, "kvmd", _STORE))
