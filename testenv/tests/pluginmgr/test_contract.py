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

from kvmd.pluginmgr.treehash import TreeFile
from kvmd.pluginmgr.treehash import tree_hash

from .vectors import CONTRACT_PATH
from .vectors import load_cases
from .vectors import b64


# =====
def test_contract_sha256() -> None:
    """
    Fails when this repo's vendored contract has been edited without
    regenerating the hash -- which is how a one-sided contract change is caught
    by the repo that made it, instead of by the other repo months later.
    """

    with open(os.path.join(CONTRACT_PATH, "CONTRACT-SHA256"), "r") as file:
        expected = file.read().strip()

    files: list[TreeFile] = []
    for (dirpath, _, names) in os.walk(CONTRACT_PATH):
        for name in names:
            if name == "CONTRACT-SHA256":
                continue
            full = os.path.join(dirpath, name)
            with open(full, "rb") as file_obj:
                data = file_obj.read()
            rel = os.path.relpath(full, CONTRACT_PATH).replace(os.sep, "/")
            files.append(TreeFile(path=rel, data=data))

    # Deliberately the same algorithm as the readback tree hash: one hashing
    # algorithm in this contract, not two.
    assert tree_hash(files) == expected, \
        "the vendored contract was edited without regenerating CONTRACT-SHA256"


def test_treehash_vectors() -> None:
    for case in load_cases("treehash.json"):
        files = [TreeFile(path=f["path"], data=b64(f["content_b64"])) for f in case["files"]]
        assert tree_hash(files) == case["tree_sha256"], f"{case['id']}: {case['description']}"
