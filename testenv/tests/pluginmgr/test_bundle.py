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
import pathlib
import hashlib

import pytest

from kvmd.pluginmgr.errors import RefusalError
from kvmd.pluginmgr.errors import code_of
from kvmd.pluginmgr.errors import CODE_BUNDLE_ENTRY_MISSING
from kvmd.pluginmgr.bundle import read_bundle
from kvmd.pluginmgr.bundle import require_entry
from kvmd.pluginmgr.bundle import readback_for
from kvmd.pluginmgr.manifest import canonical_json
from kvmd.pluginmgr.manifest import parse_manifest
from kvmd.pluginmgr.manifest import PROTOCOL_VERSION
from kvmd.pluginmgr.treehash import TreeFile
from kvmd.pluginmgr.treehash import tree_hash

from .vectors import load_cases
from .vectors import load_blob
from .vectors import case_ids


# =====
_CASES = load_cases("bundles.json")


@pytest.mark.parametrize("case", _CASES, ids=case_ids(_CASES))
def test_bundle_vector(case: dict) -> None:
    try:
        files = read_bundle(load_blob(case["blob"]))
    except RefusalError as ex:
        assert "code" in case, f"unexpected refusal {code_of(ex)!r} ({ex}) -- {case['description']}"
        assert code_of(ex) == case["code"], \
            f"refusal code {code_of(ex)!r}, want {case['code']!r} ({ex}) -- {case['description']}"
        return

    assert "code" not in case, \
        f"expected refusal {case.get('code')!r}, unpacked {len(files)} files -- {case['description']}"

    files.sort(key=(lambda f: f.path.encode("utf-8")))
    assert [f.path for f in files] == [f["path"] for f in case["files"]]
    for (got, want) in zip(files, case["files"]):
        assert hashlib.sha256(got.data).hexdigest() == want["sha256"]
    assert tree_hash(files) == case["tree_sha256"]


# =====
_REFERENCE_MANIFEST = {
    "entry": "plugins/ugpio/acme_relay.py",
    "firmware_compat": ">=1.10.0",
    "model_compat": ">=rm1pe",
    "name": "acme_relay",
    "payload": {"sha256": "0" * 64, "size": 1},
    "revision": 1,
    "runtime": "device",
    "signature": {"entries": [], "model": "hash-only"},
    "type": "ugpio",
}


def _reference_files() -> list:
    return read_bundle(load_blob("reference-bundle.tar"))


def test_require_entry_accepts_named_module() -> None:
    manifest = parse_manifest(canonical_json(_REFERENCE_MANIFEST))
    require_entry(_reference_files(), manifest)


def test_require_entry_refuses_missing_module() -> None:
    # A manifest describing a plugin the bundle does not carry is a refusal,
    # not something to discover at import time.
    manifest = parse_manifest(canonical_json({
        **_REFERENCE_MANIFEST,
        "name": "other_relay",
        "entry": "plugins/ugpio/other_relay.py",
    }))
    with pytest.raises(RefusalError) as ex:
        require_entry(_reference_files(), manifest)
    assert ex.value.code == CODE_BUNDLE_ENTRY_MISSING


def _place(tmp_path: pathlib.Path, files: list[TreeFile]) -> str:
    root = str(tmp_path)
    for file in files:
        full = os.path.join(root, file.path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(file.data)
    return root


def test_readback_reports_placed_tree(tmp_path: pathlib.Path) -> None:
    files = _reference_files()
    root = _place(tmp_path, files)
    body = readback_for("a" * 64, root)
    assert body["v"] == PROTOCOL_VERSION
    assert body["sha256"] == "a" * 64
    assert body["tree_sha256"] == tree_hash(files)
    assert [e["path"] for e in body["entries"]] == sorted(f.path for f in files)
    for entry in body["entries"]:
        got = next(f for f in files if f.path == entry["path"])
        assert entry["sha256"] == hashlib.sha256(got.data).hexdigest()


def test_readback_detects_on_disk_drift(tmp_path: pathlib.Path) -> None:
    """
    The test the disk re-read exists for.

    The bundle is untouched and would hash correctly; only the placed file
    changed. A readback that hashed the received bundle would pass this and
    report a healthy install over a corrupted disk -- which is why it must not.
    """

    files = _reference_files()
    root = _place(tmp_path, files)
    clean = readback_for("a" * 64, root)

    # Corrupt one placed file. The bundle in memory is deliberately untouched.
    with open(os.path.join(root, files[0].path), "ab") as handle:
        handle.write(b"# tampered\n")

    drifted = readback_for("a" * 64, root)
    assert drifted["tree_sha256"] != clean["tree_sha256"], \
        "readback did not notice an on-disk change -- it is hashing the received bundle"
    assert drifted["tree_sha256"] != tree_hash(files), \
        "readback matches the bundle's hash despite the disk differing"


def test_readback_detects_truncation(tmp_path: pathlib.Path) -> None:
    # The partial-write case.
    files = _reference_files()
    root = _place(tmp_path, files)
    with open(os.path.join(root, files[0].path), "wb") as handle:
        handle.write(files[0].data[:len(files[0].data) // 2])
    assert readback_for("a" * 64, root)["tree_sha256"] != tree_hash(files)


def test_readback_detects_missing_file(tmp_path: pathlib.Path) -> None:
    # The failed-rename case.
    files = _reference_files()
    root = _place(tmp_path, files)
    os.remove(os.path.join(root, files[0].path))
    body = readback_for("a" * 64, root)
    assert body["tree_sha256"] != tree_hash(files)
    assert len(body["entries"]) == len(files) - 1
