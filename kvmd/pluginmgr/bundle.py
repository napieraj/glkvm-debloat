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
import os
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
    _check_not_importable_ahead_of_source(name)


# Fixed, not derived from importlib.machinery: the server half must refuse the
# same set, and a list that moves with the device's CPython version could not be
# mirrored in Go. .so covers .abi3.so and .cpython-<ver>-<plat>.so, both of which
# end with it.
_SHADOWING_SUFFIXES = (".pyc", ".pyo", ".pyd", ".so")


def _check_not_importable_ahead_of_source(name: str) -> None:
    """
    Refuses any entry that the loader could import in preference to, or instead
    of, the declared source entry.

    The loader imports by dotted name (`kvmd.plugins.<type>.<name>`), and
    FileFinder resolves extensions before source and source before bytecode.
    Two measured consequences, both of which break the correspondence between
    the source a reader can audit and the code the device runs:

      * A `.so` beside a `.py` WINS. Measured: with a valid probe.py and a
        16-byte non-ELF probe.so present, `import pkg.probe` raised ImportError
        on the .so rather than falling through to the source.
      * A `__pycache__/<name>.cpython-*.pyc` whose header (mtime, size) matches
        its .py is executed INSTEAD of the source, in a fresh interpreter, after
        invalidate_caches(). Measured: a .py reading `VERSION = 2` imported as
        `VERSION = 1` from a stale .pyc, with __file__ still naming the .py.

    Readback cannot catch either one. Readback compares the placed tree against
    the bundle the server holds, and both files are in that bundle, so the two
    sides agree exactly. That is invariant 4 failing in the silent direction,
    which is the failure readback exists to prevent -- so the refusal has to be
    here, at admission, before anything reaches disk.
    """

    for segment in name.split("/"):
        if segment == "__pycache__":
            raise RefusalError(CODE_BUNDLE_UNSAFE_ENTRY, f"bytecode cache directory in {name!r}")
    lowered = name.lower()
    for suffix in _SHADOWING_SUFFIXES:
        if lowered.endswith(suffix):
            raise RefusalError(CODE_BUNDLE_UNSAFE_ENTRY, f"entry {name!r} would be imported ahead of source")


def require_entry(files: list[TreeFile], manifest: Manifest) -> None:
    """
    Checks that the bundle actually contains the module the manifest names. A
    manifest describing a plugin the bundle does not carry is a refusal, not
    something to discover at import time.
    """

    if not any(f.path == manifest.entry for f in files):
        raise RefusalError(CODE_BUNDLE_ENTRY_MISSING, f"bundle has no {manifest.entry!r}")


def read_placed_tree(root: str) -> list[TreeFile]:
    """
    Re-reads a placed plugin tree from disk.

    Paths are returned relative to root with POSIX separators, matching the
    bundle entry paths, so a readback is directly comparable with the bundle
    the server still holds.
    """

    files: list[TreeFile] = []
    for (dirpath, _, names) in os.walk(root):
        for name in names:
            full = os.path.join(dirpath, name)
            if os.path.islink(full) or not os.path.isfile(full):
                # A symlink appearing under the loader root after placement is
                # itself a finding, not something to follow and hash.
                raise RefusalError(CODE_BUNDLE_UNSAFE_ENTRY, f"placed entry {full!r} is not a regular file")
            with open(full, "rb") as file:
                data = file.read()
            files.append(TreeFile(path=os.path.relpath(full, root).replace(os.sep, "/"), data=data))
    return files


def readback_for(manifest_sha256: str, root: str) -> dict:
    """
    Builds the readback body by re-reading the placed tree from disk.

    It deliberately takes a root and not the bundle's files: this device must
    hash what is actually on disk, never the bundle it received. The two agree
    only in the happy path and differ in exactly the cases readback exists for
    -- a partial write, a failed rename, an overlay that did not survive the ro
    remount, or a later local edit. Hashing the received bundle would restate
    what chunk sequencing already proved and would say nothing about the disk.

    The server derives its expectation from the bundle it still holds. The
    comparison is meaningful precisely because the two sides are computed from
    different sources.

    ORDERING CONSTRAINT FOR WHOEVER WRITES PLACEMENT: compute the readback
    BEFORE loading the plugin, never after. Importing a module writes
    __pycache__/<name>.cpython-<ver>.pyc under the placement root, so a
    place -> load -> readback order adds a file the server's expectation does
    not contain and reports install.readback_mismatch on every SUCCESSFUL
    install. Measured: readback of a freshly placed tree gave tree_sha256
    38013ee7...; after one get_plugin_class() of a module in it, a1434df0...,
    with the .pyc now among the entries.

    Do not try to assert "nothing touched disk" by making the root read-only
    to model the production ro remount -- as root, the import writes through a
    0555 directory anyway, so permissions are an unfaithful double. Hash the
    store root before and after instead; that assertion is strictly stronger
    and needs no device.
    """

    return _readback_of(manifest_sha256, read_placed_tree(root))


def _readback_of(manifest_sha256: str, files: list[TreeFile]) -> dict:
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
