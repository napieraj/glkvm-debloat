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

from kvmd.pluginmgr import errors

from .vectors import CONTRACT_PATH
from .vectors import load_cases


# =====
def _codes_from_doc() -> set[str]:
    with open(os.path.join(CONTRACT_PATH, "errors.md"), "r") as file:
        text = file.read()
    # Every row of every table in errors.md starts with the code in backticks.
    return set(re.findall(r"^\| `([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)` \|", text, re.M))


def _codes_from_module() -> set[str]:
    return {
        value
        for (name, value) in vars(errors).items()
        if name.startswith("CODE_") and isinstance(value, str)
    }


def test_error_codes_match_contract_doc() -> None:
    """
    The refusal vocabulary is contract: a code that exists in one place and not
    the other means the two halves would disagree about why an install failed.

    This also keeps the codes for behaviour that lands in a later cycle
    (placement, loading, runtime-tier policy) honest -- they are defined here
    because the contract defines them, not because something happens to import
    them yet.
    """

    from_doc = _codes_from_doc()
    from_module = _codes_from_module()
    assert from_doc, "no codes parsed out of errors.md -- the table format changed"
    assert from_module - from_doc == set(), \
        f"codes in errors.py but not errors.md: {sorted(from_module - from_doc)}"
    assert from_doc - from_module == set(), \
        f"codes in errors.md but not errors.py: {sorted(from_doc - from_module)}"


def test_every_vector_code_is_a_known_code() -> None:
    # A vector asserting a code this implementation cannot produce would pass
    # vacuously in one language and fail in the other.
    known = _codes_from_module()
    for name in ("manifest.json", "verify.json", "frames.json", "bundles.json"):
        for case in load_cases(name):
            code = case.get("code")
            if code is not None:
                assert code in known, f"{name}:{case['id']} asserts unknown code {code!r}"


def test_refusal_error_carries_its_code() -> None:
    ex = errors.RefusalError(errors.CODE_BAD_NAME, "detail here")
    assert errors.code_of(ex) == errors.CODE_BAD_NAME
    assert "detail here" in str(ex)


def test_code_of_ignores_non_refusals() -> None:
    # Callers report the code; they never string-match the message, so a
    # non-refusal must not be mistaken for one.
    assert errors.code_of(ValueError("boom")) == ""
