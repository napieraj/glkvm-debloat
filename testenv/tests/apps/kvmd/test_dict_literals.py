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
# ========================================================================== #


import ast
import os

import pytest


# =====
# A duplicate key in a dict LITERAL is not an error in Python. The last one
# wins and every earlier one is discarded silently, so the source says one
# thing and the program does another.
#
# kvmd/apps/__init__.py carried exactly that: "config" appeared twice in the
# otg scheme, once as Option("", valid_stripped_string) and once as
# Option("Glinet device", valid_stripped_string_not_empty). The first was dead.
# Anyone reading the file would have concluded the USB configuration descriptor
# defaults to empty and accepts empty; neither is true. Reorder the block, or
# delete the surviving line while "fixing" the dead one, and the gadget's
# descriptor silently changes.
#
# Static, over the whole package: this catches the CLASS, not the instance.
# flake8 reports it as F601 and the repo's own lint target has been reporting
# it -- unread -- for as long as it has existed.

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")


def _dict_literals(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            yield node


def _duplicate_keys(path: str) -> list[str]:
    with open(path, encoding="utf-8") as file:
        tree = ast.parse(file.read(), filename=path)
    dups: list[str] = []
    for node in _dict_literals(tree):
        seen: dict[object, int] = {}
        for key in node.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, (str, int, bytes)):
                continue
            if key.value in seen:
                dups.append(f"{os.path.relpath(path, _ROOT)}:{key.lineno}: duplicate key {key.value!r} "
                            f"(first at line {seen[key.value]})")
            seen[key.value] = key.lineno
    return dups


def _py_files() -> list[str]:
    out: list[str] = []
    for (dirpath, dirnames, filenames) in os.walk(os.path.join(_ROOT, "kvmd")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        out.extend(os.path.join(dirpath, n) for n in sorted(filenames) if n.endswith(".py"))
    return sorted(out)


# =====
def test_ok__the_root_resolves() -> None:
    # Four levels up from testenv/tests/apps/kvmd. One short and _py_files
    # walks nothing and this whole module passes VACUOUSLY -- build hazard 3.
    assert os.path.isdir(os.path.join(_ROOT, "kvmd", "apps", "kvmd"))
    assert len(_py_files()) > 50


@pytest.mark.parametrize("path", _py_files(), ids=lambda p: os.path.basename(p))
def test_ok__no_duplicate_keys_in_dict_literals(path: str) -> None:
    dups = _duplicate_keys(path)
    assert not dups, "; ".join(dups)
