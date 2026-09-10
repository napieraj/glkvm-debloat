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


import hashlib
import dataclasses


# =====
@dataclasses.dataclass(frozen=True)
class TreeFile:
    path: str  # POSIX-relative to the plugin root, no leading "./"
    data: bytes


def tree_hash(files: list[TreeFile]) -> str:
    """
    The canonical tree hash, used by readback and by contract-sync checking.

    Both sides must compute this identically or every readback comparison is
    meaningless, which is why vectors/treehash.json exists.

        for each regular file:
            sha256_hex(content) + "  " + path + "\\n"   (two spaces, as sha256sum)
        concatenated in bytewise path order, then sha256_hex of the whole.

    Directories, symlinks, modes and timestamps are not hashed and are not
    permitted in a v1 bundle, so there is nothing left to disagree about.

    Sorting is on the UTF-8 bytes, not on str: Python's str ordering is by code
    point, which diverges from bytewise ordering above U+007F. Paths are
    restricted to printable ASCII, so the two agree today -- sorting on bytes
    keeps that true if the restriction is ever relaxed.
    """

    lines = b""
    for file in sorted(files, key=(lambda f: f.path.encode("utf-8"))):
        lines += (hashlib.sha256(file.data).hexdigest() + "  " + file.path + "\n").encode("utf-8")
    return hashlib.sha256(lines).hexdigest()
