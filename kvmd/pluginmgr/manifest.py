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


import re
import json
import dataclasses

from typing import Any

from .errors import RefusalError
from .errors import CODE_MALFORMED
from .errors import CODE_BAD_NAME
from .errors import CODE_BAD_TYPE
from .errors import CODE_BAD_RUNTIME
from .errors import CODE_BAD_ENTRY
from .errors import CODE_ENTRY_TYPE_MISMATCH
from .errors import CODE_ENTRY_NAME_MISMATCH
from .errors import CODE_BAD_COMPAT
from .errors import CODE_BAD_PAYLOAD_HASH
from .errors import CODE_BAD_PAYLOAD_SIZE
from .errors import CODE_PAYLOAD_TOO_LARGE
from .errors import CODE_CAPABILITIES_NOT_ALLOWED
from .errors import CODE_BAD_CAPABILITY


# =====
# Caps a bundle at 8 MiB. This device must buffer and hash the whole bundle
# before it may touch the disk, so an unbounded payload is a memory-exhaustion
# path reached *before* the verify gate can protect against it.
PAYLOAD_MAX_SIZE = 8 << 20

# The plugin sub-directories that exist under kvmd/plugins/. A type outside
# this set has no loader and cannot be placed anywhere meaningful.
PLUGIN_TYPES = ("atx", "msd", "hid", "ugpio", "auth")

RUNTIME_DEVICE = "device"
RUNTIME_MANAGEMENT = "management"

# Constrained to what a Python module name may be, because this becomes
# kvmd.plugins.<type>.<name> at import time. Leading underscores are excluded
# because get_plugin_class() in kvmd/plugins/__init__.py already treats them
# as unknown.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_ENTRY_RE = re.compile(r"^plugins/(atx|msd|hid|ugpio|auth)/([a-z][a-z0-9_]{0,31})\.py$")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_CAP_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_COMPAT_RE = re.compile(r"^(>=|<=|==)?[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_REQUIRED = ("entry", "firmware_compat", "model_compat", "name", "payload", "runtime", "type")
_OPTIONAL = ("capabilities", "signature")
_PAYLOAD_REQUIRED = ("sha256", "size")
_SIGNATURE_ALLOWED = ("alg", "key_id", "value")


@dataclasses.dataclass(frozen=True)
class Payload:
    sha256: str
    size: int


@dataclasses.dataclass(frozen=True)
class Manifest:  # pylint: disable=too-many-instance-attributes
    """
    Describes a plugin.

    capabilities and signature are None when absent and a (possibly empty)
    value when present, because canonical encoding omits an absent field
    entirely but must still emit an explicitly empty capabilities list.
    """

    entry: str
    firmware_compat: str
    model_compat: str
    name: str
    payload: Payload
    runtime: str
    type: str  # pylint: disable=redefined-builtin
    capabilities: (tuple[str, ...] | None) = None
    signature: (dict[str, str] | None) = None

    def to_dict(self) -> dict:
        # Keys inserted in bytewise-sorted order; json.dumps(sort_keys=True)
        # makes that explicit rather than relying on insertion order.
        out: dict[str, Any] = {}
        if self.capabilities is not None:
            out["capabilities"] = list(self.capabilities)
        out["entry"] = self.entry
        out["firmware_compat"] = self.firmware_compat
        out["model_compat"] = self.model_compat
        out["name"] = self.name
        out["payload"] = {"sha256": self.payload.sha256, "size": self.payload.size}
        out["runtime"] = self.runtime
        if self.signature is not None:
            out["signature"] = dict(self.signature)
        out["type"] = self.type
        return out

    def canonical_json(self) -> bytes:
        return canonical_json(self.to_dict())

    def validate(self) -> None:
        """
        Applies every structural rule in contract/plugins/manifest.md.

        The call order here is contract, not taste: the vectors pin which code
        comes back when more than one rule is broken.
        """

        self.__validate_identity()
        self.__validate_entry()
        self.__validate_compat()
        self.__validate_payload()
        self.__validate_capabilities()

    def __validate_identity(self) -> None:
        if not _NAME_RE.match(self.name):
            raise RefusalError(CODE_BAD_NAME, f"name {self.name!r}")
        if self.type not in PLUGIN_TYPES:
            # Checked before the entry, because an unknown type would otherwise
            # surface as a bad_entry: the entry pattern enumerates the known
            # types, so it rejects an unknown one for the wrong reason.
            raise RefusalError(CODE_BAD_TYPE, f"type {self.type!r}")
        if self.runtime not in (RUNTIME_DEVICE, RUNTIME_MANAGEMENT):
            # Never defaulted: defaulting a security tier is how tiers stop
            # meaning anything.
            raise RefusalError(CODE_BAD_RUNTIME, f"runtime {self.runtime!r}")

    def __validate_entry(self) -> None:
        groups = _ENTRY_RE.match(self.entry)
        if groups is None:
            raise RefusalError(CODE_BAD_ENTRY, f"entry {self.entry!r}")
        # Invariant 1: entry describes the bundle's shape, it does not instruct
        # where to write. A disagreement with the loader's own derivation from
        # type+name is a refusal, never a redirection.
        if groups.group(1) != self.type:
            raise RefusalError(CODE_ENTRY_TYPE_MISMATCH,
                               f"entry type {groups.group(1)!r}, manifest type {self.type!r}")
        if groups.group(2) != self.name:
            raise RefusalError(CODE_ENTRY_NAME_MISMATCH,
                               f"entry stem {groups.group(2)!r}, manifest name {self.name!r}")

    def __validate_compat(self) -> None:
        for (field, value) in [("model_compat", self.model_compat), ("firmware_compat", self.firmware_compat)]:
            if not valid_compat(value):
                raise RefusalError(CODE_BAD_COMPAT, f"{field} {value!r}")

    def __validate_payload(self) -> None:
        if not _HEX_RE.match(self.payload.sha256):
            # Canonical means one spelling: uppercase hex is a violation, not
            # something to normalise.
            raise RefusalError(CODE_BAD_PAYLOAD_HASH, f"payload.sha256 {self.payload.sha256!r}")
        if self.payload.size < 1:
            raise RefusalError(CODE_BAD_PAYLOAD_SIZE, f"payload.size {self.payload.size}")
        if self.payload.size > PAYLOAD_MAX_SIZE:
            raise RefusalError(CODE_PAYLOAD_TOO_LARGE,
                               f"payload.size {self.payload.size} exceeds {PAYLOAD_MAX_SIZE}")

    def __validate_capabilities(self) -> None:
        if not self.capabilities:
            return
        # Device plugins draw their blast radius from the console they run on,
        # not from a capability grant; allowing the field there would create a
        # second, weaker authorisation story.
        if self.runtime != RUNTIME_MANAGEMENT:
            raise RefusalError(CODE_CAPABILITIES_NOT_ALLOWED, f"runtime {self.runtime!r}")
        for cap in self.capabilities:
            if not isinstance(cap, str) or not _CAP_RE.match(cap):
                raise RefusalError(CODE_BAD_CAPABILITY, f"capability {cap!r}")


# =====
def canonical_json(obj: Any) -> bytes:
    """
    Canonical form: keys sorted bytewise, UTF-8, no insignificant whitespace.

    Go escapes <, > and & by default and Python does not, so the Go side turns
    HTML escaping off; the two must agree byte for byte or a manifest cannot be
    hashed to the same value on both sides -- which the signing module will
    depend on.
    """

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def parse_manifest(data: bytes) -> Manifest:
    """
    Decodes canonical JSON into a Manifest without validating it.

    Unknown top-level fields are refused rather than ignored: that costs
    forward compatibility and buys the thing worth more, which is that a device
    and a server can never disagree about what a manifest said.
    """

    try:
        raw = json.loads(data)
    except ValueError as ex:
        raise RefusalError(CODE_MALFORMED, f"not JSON: {ex}")
    if not isinstance(raw, dict):
        raise RefusalError(CODE_MALFORMED, "not a JSON object")
    _check_keys(raw, _REQUIRED, _OPTIONAL)

    payload_raw = raw["payload"]
    if not isinstance(payload_raw, dict):
        raise RefusalError(CODE_MALFORMED, "payload is not an object")
    _check_keys(payload_raw, _PAYLOAD_REQUIRED, ())

    size = payload_raw["size"]
    # bool is an int subclass in Python; true is not a size.
    if isinstance(size, bool) or not isinstance(size, int):
        raise RefusalError(CODE_BAD_PAYLOAD_SIZE, f"payload.size {size!r} is not an integer")
    sha256 = payload_raw["sha256"]
    if not isinstance(sha256, str):
        raise RefusalError(CODE_BAD_PAYLOAD_HASH, f"payload.sha256 {sha256!r} is not a string")

    for key in ("entry", "firmware_compat", "model_compat", "name", "runtime", "type"):
        if not isinstance(raw[key], str):
            raise RefusalError(CODE_MALFORMED, f"{key} is not a string")

    caps = raw.get("capabilities")
    if caps is not None:
        if not isinstance(caps, list):
            raise RefusalError(CODE_MALFORMED, "capabilities is not a list")
        caps = tuple(caps)

    sig = raw.get("signature")
    if sig is not None:
        # The stub. Defined now and populated never -- its presence in the
        # schema is exactly what lets signing land as an implementation behind
        # the Verifier seam rather than as a schema migration across a fleet of
        # already-deployed devices. v1 must not reject a manifest for a
        # missing, empty or unrecognised signature, nor treat one as meaningful.
        if not isinstance(sig, dict):
            raise RefusalError(CODE_MALFORMED, "signature is not an object")
        _check_keys(sig, (), _SIGNATURE_ALLOWED)
        sig = {str(k): str(v) for (k, v) in sig.items()}

    return Manifest(
        entry=raw["entry"],
        firmware_compat=raw["firmware_compat"],
        model_compat=raw["model_compat"],
        name=raw["name"],
        payload=Payload(sha256=sha256, size=size),
        runtime=raw["runtime"],
        type=raw["type"],
        capabilities=caps,
        signature=sig,
    )


def _check_keys(raw: dict, required: tuple, optional: tuple) -> None:
    allowed = set(required) | set(optional)
    for key in required:
        if key not in raw:
            raise RefusalError(CODE_MALFORMED, f"missing required field {key!r}")
    for key in raw:
        if key not in allowed:
            raise RefusalError(CODE_MALFORMED, f"unknown field {key!r}")


def valid_compat(constraint: str) -> bool:
    """
    Parses the minimal constraint grammar from manifest.md. Deliberately small:
    compatibility gating is a device-side policy decision, and the contract's
    only job is to make the expression parse identically on both sides.
    """

    return (constraint == "*" or bool(_COMPAT_RE.match(constraint)))


def compare_versions(left: str, right: str) -> int:
    """
    Orders two compat tokens by splitting on "." and "-" and comparing segments
    numerically when both are all-digits, bytewise otherwise.
    """

    left_parts = re.split(r"[.-]", left)
    right_parts = re.split(r"[.-]", right)
    for index in range(max(len(left_parts), len(right_parts))):
        x = (left_parts[index] if index < len(left_parts) else "")
        y = (right_parts[index] if index < len(right_parts) else "")
        if x.isdigit() and y.isdigit():
            if int(x) != int(y):
                return (-1 if int(x) < int(y) else 1)
            continue
        if x != y:
            return (-1 if x < y else 1)
    return 0
