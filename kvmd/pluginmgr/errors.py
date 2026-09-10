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


# =====
# Refusal reason codes. These strings cross the wire in install_result.reason
# and are asserted by the shared conformance vectors, so they are contract,
# not implementation detail. See contract/plugins/errors.md.

CODE_MALFORMED = "manifest.malformed"
CODE_UNSUPPORTED_VERSION = "manifest.unsupported_version"
CODE_BAD_NAME = "manifest.bad_name"
CODE_BAD_REVISION = "manifest.bad_revision"
CODE_BAD_TYPE = "manifest.bad_type"
CODE_BAD_RUNTIME = "manifest.bad_runtime"
CODE_BAD_ENTRY = "manifest.bad_entry"
CODE_ENTRY_TYPE_MISMATCH = "manifest.entry_type_mismatch"
CODE_ENTRY_NAME_MISMATCH = "manifest.entry_name_mismatch"
CODE_BAD_COMPAT = "manifest.bad_compat"
CODE_BAD_PAYLOAD_HASH = "manifest.bad_payload_hash"
CODE_BAD_PAYLOAD_SIZE = "manifest.bad_payload_size"
CODE_PAYLOAD_TOO_LARGE = "manifest.payload_too_large"
CODE_SANDBOX_NOT_ALLOWED = "manifest.sandbox_not_allowed"

CODE_PAYLOAD_SIZE_MISMATCH = "payload.size_mismatch"
CODE_PAYLOAD_HASH_MISMATCH = "payload.hash_mismatch"

CODE_VERIFY_REFUSED = "verify.refused"
CODE_VERIFY_UNCONFIGURED = "verify.unconfigured"

CODE_BUNDLE_MALFORMED = "bundle.malformed"
CODE_BUNDLE_UNSAFE_PATH = "bundle.unsafe_path"
CODE_BUNDLE_UNSAFE_ENTRY = "bundle.unsafe_entry"
CODE_BUNDLE_ENTRY_MISSING = "bundle.entry_missing"

CODE_WIRE_BAD_FRAME = "wire.bad_frame"
CODE_WIRE_BAD_SEQUENCE = "wire.bad_sequence"
CODE_WIRE_BAD_FLAGS = "wire.bad_flags"
CODE_WIRE_UNSOLICITED = "wire.unsolicited"
CODE_WIRE_CHUNK_TOO_LARGE = "wire.chunk_too_large"

CODE_POLICY_ROLLBACK_REFUSED = "policy.rollback_refused"
CODE_POLICY_WRONG_RUNTIME = "policy.wrong_runtime"
CODE_POLICY_INCOMPATIBLE_MODEL = "policy.incompatible_model"
CODE_POLICY_INCOMPATIBLE_FIRMWARE = "policy.incompatible_firmware"

CODE_INSTALL_LOAD_FAILED = "install.load_failed"
CODE_INSTALL_PLACE_FAILED = "install.place_failed"
CODE_INSTALL_READBACK_MISMATCH = "install.readback_mismatch"


# =====
class RefusalError(Exception):
    """
    A refusal carries a contract code plus human detail. The code is what the
    server acts on and what the vectors assert; the detail is for operators and
    is deliberately never parsed.
    """

    def __init__(self, code: str, detail: str="") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class VerifyError(RefusalError):
    """
    Raised by a Verifier to refuse a payload. It is a RefusalError so that
    every refusal in this package -- structural, transport or cryptographic --
    is caught and reported through one path.
    """


def code_of(ex: BaseException) -> str:
    """
    Returns the contract code carried by an exception, or "" if it is not a
    refusal. Callers report the code; they never string-match the message.
    """

    return (ex.code if isinstance(ex, RefusalError) else "")
