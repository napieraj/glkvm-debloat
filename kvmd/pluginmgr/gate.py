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


from .errors import RefusalError
from .errors import CODE_MALFORMED
from .errors import CODE_PAYLOAD_SIZE_MISMATCH
from .errors import CODE_VERIFY_UNCONFIGURED
from .errors import CODE_POLICY_ROLLBACK_REFUSED
from .manifest import Manifest
from .verifier import Verifier
from .verifier import resolve


# =====
def gate(verifier: (Verifier | None), manifest: (Manifest | None), payload: bytes) -> None:
    """
    The single choke point where an install can be refused.

    Both halves call gate() and never a Verifier directly. That is what makes
    invariant 3 a single testable claim rather than a property scattered across
    two codebases and two languages.

    The contract on every caller:

        If gate() refuses, the caller MUST NOT unpack, place, or load.
        Nothing may touch the disk.

    That contract is why install_result distinguishes "refused" from "failed":
    refused means the plugin never reached the disk, and collapsing the two
    would make invariant 3 untestable from the server's side.

    Step order is contract, not implementation detail -- the vectors assert
    which code comes back when a manifest is invalid *and* the payload is
    corrupt, so the Python and Go implementations cannot diverge on precedence:

        1. validate the manifest
        2. check the payload length against manifest.payload.size
        3. call the verifier

    Steps 1 and 2 run before the verifier and run for every verifier, noop
    included. Step 2 is not redundant with hash-only: it bounds the work done
    before hashing, and it still holds when the configured verifier does not
    hash at all.
    """

    if verifier is None:
        raise RefusalError(CODE_VERIFY_UNCONFIGURED, "no verifier configured")
    if manifest is None:
        raise RefusalError(CODE_MALFORMED, "no manifest")
    manifest.validate()
    if len(payload) != manifest.payload.size:
        raise RefusalError(CODE_PAYLOAD_SIZE_MISMATCH,
                           f"payload {len(payload)} bytes, manifest {manifest.payload.size}")
    verifier.verify(manifest, payload)


def gate_named(name: str, manifest: (Manifest | None), payload: bytes) -> None:
    """
    Resolves a configured verifier name and runs the gate. Resolution failure
    is itself a refusal, so a missing or misspelled config cannot be mistaken
    for an accept.
    """

    gate(resolve(name), manifest, payload)


def admit_offer(manifest: (Manifest | None), installed_revision: int=0) -> None:
    """
    Decides whether a plugin.offer is worth transferring, before a plugin.fetch
    is sent and before any payload chunk moves.

    This is a distinct check from gate() step 2, not a duplicate of it. Step 2
    compares the *assembled* length against the declared size and can only run
    once the bytes have arrived; admission compares the *declared* size against
    the protocol ceiling and runs before any do. Without admission an oversized
    bundle is transferred in full and only then refused -- and because a dropped
    transfer restarts from chunk 0, size and link reliability multiply, so a
    bundle too large to transfer must be refused while it is still a claim.

    Admission neither sees nor needs the payload. That is what distinguishes it
    from the verify gate, and it is why it can run on the offer alone.
    """

    if manifest is None:
        raise RefusalError(CODE_MALFORMED, "no manifest")
    manifest.validate()
    check_revision(manifest, installed_revision)


def check_revision(manifest: Manifest, installed_revision: int) -> None:
    """
    Closes the downgrade and freeze attack class: re-serving a
    genuinely-authored older plugin with a known flaw, or re-serving the
    current one forever to prevent an upgrade.

    It is an integer comparison and nothing more, which is exactly why it lands
    now rather than with signing -- it needs no trust model to work, and even
    mature implementations get it subtly wrong when it is buried inside one.

    Equal is refused, not just lower: an identical revision is the freeze half
    of the class. Idempotent re-push is handled by the payload-hash noop path,
    which compares what is actually installed, not by accepting a stale
    revision.
    """

    if manifest.revision <= installed_revision:
        raise RefusalError(CODE_POLICY_ROLLBACK_REFUSED,
                           f"revision {manifest.revision} is not newer than "
                           f"the installed {installed_revision}")
