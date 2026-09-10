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


import io
import hashlib
import tarfile

from .errors import RefusalError
from .errors import CODE_BUNDLE_MALFORMED
from .errors import CODE_BUNDLE_UNSAFE_PATH
from .errors import CODE_BUNDLE_UNSAFE_ENTRY
from .errors import CODE_BUNDLE_ENTRY_MISSING
from .manifest import Manifest
from .treehash import TreeFile
from .treehash import tree_hash
from .wire import PROTOCOL_VERSION


# =====
# A v1 bundle is an uncompressed POSIX ustar archive of regular files only.
# Both sides already have a tar reader in their standard library, so the bundle
# costs no dependency on this device.
#
# The checks below are not defence in depth over the verify gate -- they are
# the reason a noop verifier is survivable at all. Path safety is structural
# and is enforced regardless of which Verifier is configured.

# Bounds a bundle's file count, so a well-formed archive cannot become a
# resource-exhaustion path after the size check has passed.
BUNDLE_MAX_ENTRIES = 256

# Per-file readback detail is capped; a larger tree reports tree_sha256 only.
READBACK_MAX_ENTRIES = 64


def read_bundle(data: bytes) -> list[TreeFile]:
    """
    Validates and unpacks a bundle into its files. It refuses before returning
    anything, so a caller can never act on a partially-validated tree.
    """

    files: list[TreeFile] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            for member in tar:
                if len(files) >= BUNDLE_MAX_ENTRIES:
                    raise RefusalError(CODE_BUNDLE_MALFORMED, f"more than {BUNDLE_MAX_ENTRIES} entries")
                if not member.isreg():
                    # Symlinks can redirect a later write outside the root, and
                    # directory entries would smuggle in modes; v1 carries neither.
                    raise RefusalError(CODE_BUNDLE_UNSAFE_ENTRY, f"entry {member.name!r} is not a regular file")
                _check_path(member.name)
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise RefusalError(CODE_BUNDLE_MALFORMED, f"entry {member.name!r} has no content")
                files.append(TreeFile(path=member.name, data=extracted.read()))
    except tarfile.TarError as ex:
        raise RefusalError(CODE_BUNDLE_MALFORMED, f"read: {ex}")
    if not files:
        raise RefusalError(CODE_BUNDLE_MALFORMED, "no entries")
    return files


def _check_path(name: str) -> None:
    """
    Enforces invariant 1 at the archive level: no entry may name a location
    outside the loader-owned root.
    """

    if not name:
        raise RefusalError(CODE_BUNDLE_UNSAFE_PATH, "empty path")
    if name.startswith("/"):
        raise RefusalError(CODE_BUNDLE_UNSAFE_PATH, f"absolute path {name!r}")
    if "\\" in name:
        # Refused rather than normalised: a separator that means one thing on
        # the server and another on the device is exactly the ambiguity that
        # path checks are supposed to remove.
        raise RefusalError(CODE_BUNDLE_UNSAFE_PATH, f"backslash in {name!r}")
    if name.endswith("/"):
        raise RefusalError(CODE_BUNDLE_UNSAFE_ENTRY, f"directory entry {name!r}")
    for segment in name.split("/"):
        if segment in ("", ".", ".."):
            raise RefusalError(CODE_BUNDLE_UNSAFE_PATH, f"unsafe segment in {name!r}")
    for char in name:
        if not 0x20 <= ord(char) <= 0x7E:
            raise RefusalError(CODE_BUNDLE_UNSAFE_PATH, f"non-printable-ASCII in {name!r}")


def require_entry(files: list[TreeFile], manifest: Manifest) -> None:
    """
    Checks that the bundle actually contains the module the manifest names. A
    manifest describing a plugin the bundle does not carry is a refusal, not
    something to discover at import time.
    """

    if not any(f.path == manifest.entry for f in files):
        raise RefusalError(CODE_BUNDLE_ENTRY_MISSING, f"bundle has no {manifest.entry!r}")


def readback_for(manifest_sha256: str, files: list[TreeFile]) -> dict:
    """
    Builds the readback body for a placed tree: what is actually on disk,
    hashed here rather than assumed from what this device was told to write.
    """

    body: dict = {
        "entries": [],
        "sha256": manifest_sha256,
        "tree_sha256": tree_hash(files),
        "v": PROTOCOL_VERSION,
    }
    if len(files) > READBACK_MAX_ENTRIES:
        # Detail is capped; the tree hash still tells the server drift happened.
        return body
    body["entries"] = [
        {"path": f.path, "sha256": hashlib.sha256(f.data).hexdigest()}
        for f in sorted(files, key=(lambda f: f.path.encode("utf-8")))
    ]
    return body
