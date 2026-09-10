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
