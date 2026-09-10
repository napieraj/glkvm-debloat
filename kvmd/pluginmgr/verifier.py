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


import abc
import hashlib

from .errors import VerifyError
from .errors import RefusalError
from .errors import CODE_PAYLOAD_HASH_MISMATCH
from .errors import CODE_VERIFY_UNCONFIGURED
from .manifest import Manifest


# =====
class Verifier(abc.ABC):
    """
    The swap seam.

    Signing is deferred, but the place signing will go is not. Everything
    downstream of this interface -- transport, placement, rollback, readback --
    is identical whichever crypto eventually lands, so the crypto is a hook,
    and the hook is specified now and filled later. Nothing downstream knows or
    cares which implementation is behind it.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def verify(self, manifest: Manifest, payload: bytes) -> None:
        """
        Returns normally to accept, raises VerifyError to refuse.
        """

        raise NotImplementedError


class NoopVerifier(Verifier):
    """
    Accepts any payload.

    It does NOT skip the gate's structural checks -- that distinction is the
    whole reason noop is tolerable in a tree at all. It disables authenticity
    checking, not path safety.

    Dev only. Never a default in any real config; resolve() fails closed rather
    than falling back to this.
    """

    @property
    def name(self) -> str:
        return "noop"

    def verify(self, manifest: Manifest, payload: bytes) -> None:
        pass


class HashOnlyVerifier(Verifier):
    """
    The buildable-now floor: integrity without authenticity. Refuses unless the
    payload hashes to what the manifest claims, and ignores the signature block
    entirely.
    """

    @property
    def name(self) -> str:
        return "hash-only"

    def verify(self, manifest: Manifest, payload: bytes) -> None:
        got = hashlib.sha256(payload).hexdigest()
        if got != manifest.payload.sha256:
            raise VerifyError(CODE_PAYLOAD_HASH_MISMATCH,
                              f"payload sha256 {got}, manifest {manifest.payload.sha256}")


def resolve(name: str) -> Verifier:
    """
    Maps a configured verifier name to an implementation.

    Fails closed. An absent name, an unrecognised name, and "signed" (which is
    deliberately not a v1 tier) all refuse rather than silently downgrading to
    noop -- a config typo must not become an open door.

    BUT "noop" IS a name this function accepts, and it disables authenticity.
    That is deliberate and must stay: the shared contract vectors in
    verify.json exercise noop, so removing it here would break the conformance
    suite that proves the two language halves agree.

    The constraint is therefore not enforceable here, and it has to be
    enforced where a name first arrives from configuration. Today nothing
    reaches this function from config -- the only caller is gate_named(), and
    the only caller of that is the vector suite -- so the hazard is latent
    rather than live. WHOEVER WIRES A VERIFIER NAME TO A CONFIG FILE OWNS IT:
    refuse "noop" at that boundary, because verifier.md says it is dev-only
    and never a default in any real config, and nothing but that boundary can
    make it so. noop still keeps the gate's structural path safety, which is
    the only reason it is tolerable in the tree at all.
    """

    if name == "noop":
        return NoopVerifier()
    if name == "hash-only":
        return HashOnlyVerifier()
    raise RefusalError(CODE_VERIFY_UNCONFIGURED, f"verifier {name!r} is not a v1 tier")
