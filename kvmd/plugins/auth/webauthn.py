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
import re
import json
import time
import base64
import hashlib
import hmac
import socket
import secrets
import textwrap
import tempfile
import dataclasses

from typing import Any

from ...logging import get_logger

from ...yamlconf import Option

from ...validators.auth import valid_user
from ...validators.basic import valid_bool
from ...validators.basic import valid_int_f1
from ...validators.basic import valid_string_list
from ...validators.basic import valid_stripped_string
from ...validators.os import valid_abs_path
from ...validators.os import valid_command

from ...tools import run_command

from . import BaseAuthService


# =====
class WebAuthnError(Exception):
    """Any rejection of an assertion, a challenge or a stored credential.

    The message is for the log only. The route MUST NOT return it to the
    client: a caller must not be able to tell "unknown credential" from "bad
    signature" from "stale challenge".
    """


# =====
_B64U_RE = re.compile(r"^[A-Za-z0-9_-]*$")


def b64u_decode(data: str, name: str="value") -> bytes:
    if not isinstance(data, str) or not _B64U_RE.match(data):
        raise WebAuthnError(f"Malformed base64url {name}")
    try:
        return base64.urlsafe_b64decode(data + ("=" * (-len(data) % 4)))
    except Exception as ex:
        raise WebAuthnError(f"Undecodable base64url {name}: {ex}")


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


# =====
# A deliberately minimal CBOR reader. It exists because the device has no cbor2
# and testenv/requirements.txt would not install one, and because a COSE_Key is
# a flat map of small integers and byte strings -- the full CBOR grammar is not
# needed and every part of it that is not needed is attack surface. Indefinite
# lengths, tags, floats and simple values are all refused rather than skipped.

_CBOR_MAX_DEPTH = 4


def _cbor_head(data: bytes, i: int) -> tuple[int, int, int]:
    if i >= len(data):
        raise WebAuthnError("Truncated CBOR")
    major = data[i] >> 5
    minor = data[i] & 0x1F
    i += 1
    if minor < 24:
        return (major, minor, i)
    size = {24: 1, 25: 2, 26: 4, 27: 8}.get(minor, 0)
    if size == 0:
        raise WebAuthnError(f"Unsupported CBOR additional info {minor}")
    if i + size > len(data):
        raise WebAuthnError("Truncated CBOR argument")
    return (major, int.from_bytes(data[i:i + size], "big"), i + size)


def _cbor_item(data: bytes, i: int, depth: int) -> tuple[Any, int]:
    if depth > _CBOR_MAX_DEPTH:
        raise WebAuthnError("CBOR nesting is too deep")
    (major, arg, i) = _cbor_head(data, i)

    if major == 0:
        return (arg, i)
    if major == 1:
        return ((-1 - arg), i)
    if major in (2, 3):
        if i + arg > len(data):
            raise WebAuthnError("Truncated CBOR string")
        raw = data[i:i + arg]
        return ((raw if major == 2 else raw.decode("utf-8")), (i + arg))
    if major == 4:
        items = []
        for _ in range(arg):
            (item, i) = _cbor_item(data, i, depth + 1)
            items.append(item)
        return (items, i)
    if major == 5:
        pairs: dict = {}
        for _ in range(arg):
            (key, i) = _cbor_item(data, i, depth + 1)
            if not isinstance(key, (int, str)):
                raise WebAuthnError("Unsupported CBOR map key type")
            if key in pairs:
                raise WebAuthnError(f"Duplicate CBOR map key {key!r}")
            (value, i) = _cbor_item(data, i, depth + 1)
            pairs[key] = value
        return (pairs, i)
    raise WebAuthnError(f"Unsupported CBOR major type {major}")


def cbor_loads(data: bytes) -> Any:
    (value, i) = _cbor_item(data, 0, 0)
    if i != len(data):
        raise WebAuthnError("Trailing bytes after the CBOR item")
    return value


# =====
# The 26 fixed bytes at the front of a prime256v1 SubjectPublicKeyInfo, plus the
# 0x04 uncompressed-point marker. Measured, not copied: `openssl ec -pubout
# -outform DER` on a prime256v1 key emits exactly 91 bytes, and this prefix
# followed by x||y reproduces them byte for byte. See docs/webauthn.md section 1.1.
_P256_SPKI_PREFIX = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d03010703420004")

_COSE_KTY = 1
_COSE_ALG = 3
_COSE_CRV = -1
_COSE_X = -2
_COSE_Y = -3

_COSE_KTY_EC2 = 2
_COSE_ALG_ES256 = -7
_COSE_CRV_P256 = 1


def cose_es256_to_spki(cose: bytes) -> bytes:
    """COSE_Key -> DER SubjectPublicKeyInfo, ES256 only.

    ES256 is the only algorithm this plugin accepts (alg -7). There is no
    negotiation and no fallback: registration happens off-device, so the only
    place the algorithm can be enforced is on the STORED key, and it is
    enforced when the store loads rather than when someone logs in.
    """
    key = cbor_loads(cose)
    if not isinstance(key, dict):
        raise WebAuthnError("COSE key is not a map")
    if key.get(_COSE_KTY) != _COSE_KTY_EC2:
        raise WebAuthnError(f"COSE kty is not EC2: {key.get(_COSE_KTY)!r}")
    if key.get(_COSE_ALG) != _COSE_ALG_ES256:
        raise WebAuthnError(f"COSE alg is not ES256/-7: {key.get(_COSE_ALG)!r}")
    if key.get(_COSE_CRV) != _COSE_CRV_P256:
        raise WebAuthnError(f"COSE crv is not P-256: {key.get(_COSE_CRV)!r}")
    x = key.get(_COSE_X)
    y = key.get(_COSE_Y)
    for (name, value) in [("x", x), ("y", y)]:
        if not isinstance(value, bytes) or len(value) != 32:
            raise WebAuthnError(f"COSE {name} is not 32 bytes")
    assert isinstance(x, bytes) and isinstance(y, bytes)
    return (_P256_SPKI_PREFIX + x + y)


def spki_to_pem(spki: bytes) -> str:
    body = "\n".join(textwrap.wrap(base64.b64encode(spki).decode("ascii"), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----\n"


# =====
def verify_es256_cryptography(spki: bytes, message: bytes, signature: bytes) -> (bool | None):
    """The optional fast path. Returns None when the package is absent, which
    is the signal to fall through to openssl.

    This is the LIVE path in the test container, not a dormant optimisation. It
    was documented and canary-tested here as dead -- "`cryptography` is not
    present in testenv/Dockerfile or testenv/requirements.txt" -- on a grep for
    the name. That grep was right and the conclusion was wrong: `pyghmi`
    (testenv/requirements.txt:2) declares `cryptography>=2.1`, so pip pulls it in
    transitively and every ES256 verification in CI comes through here. The
    canary asserting None is what finally measured it.

    Everything below is therefore reachable, and every exit fails CLOSED. Keep it
    that way: all three `return False` exits have a one-token mutation to `return
    True` that accepts forged assertions, and until this was measured NONE of the
    three reddened a test. They now do -- see the "ES256 verification" block in
    testenv/tests/plugins/auth/test_webauthn.py, which also pins the None
    contract that verify_es256's two halves rest on.

    PKGBUILD:67 lists `python-pyghmi` for the device too, so the device may well
    take this path as well -- unverified, because that needs Arch's dependency
    list for python-pyghmi and archlinux.org is not reachable from where this was
    written. Treat both paths as production. See docs/webauthn.md section 1.
    """
    try:
        # pylint: disable=import-outside-toplevel
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import load_der_public_key
    except ImportError:
        return None
    try:
        key = load_der_public_key(spki)
        if not isinstance(key, ec.EllipticCurvePublicKey):
            # Not mypy narrowing. Deleting this does not change the return value
            # -- a non-EC key reaches key.verify() with an argument too many,
            # raises, and the handler below returns the same False -- so the test
            # covering it keys on the log staying silent. It is the difference
            # between refusing a wrong key type and erroring on the signature gate.
            return False
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False
    except Exception as ex:
        get_logger(0).error("WebAuthn: cryptography verification errored: %s", ex)
        return False


async def verify_es256_openssl(
    spki: bytes,
    message: bytes,
    signature: bytes,
    openssl_cmd: list[str],
    timeout: int=5,
) -> bool:
    """`openssl dgst -sha256 -verify` over three temporary files.

    WebAuthn's ES256 signature is already an ASN.1 SEQUENCE{r,s}, which is
    exactly what `dgst -verify` wants, so there is no (r||s) conversion here.
    The public key is handed over as PEM rather than DER because `-keyform DER`
    is not uniformly available (PKGBUILD:104 still carries openssl-1.1) and PEM
    has no version sensitivity.
    """
    with tempfile.TemporaryDirectory() as tmp:
        pub_path = os.path.join(tmp, "pub.pem")
        sig_path = os.path.join(tmp, "sig.der")
        msg_path = os.path.join(tmp, "msg.bin")
        with open(pub_path, "w") as file:
            file.write(spki_to_pem(spki))
        with open(sig_path, "wb") as file:
            file.write(signature)
        with open(msg_path, "wb") as file:
            file.write(message)
        try:
            (retcode, _, stderr) = await run_command(
                *openssl_cmd, "dgst", "-sha256",
                "-verify", pub_path,
                "-signature", sig_path,
                msg_path,
                timeout=timeout,
            )
        except Exception as ex:
            # A missing binary, or a timeout: run_command wraps communicate() in
            # wait_for and does not kill the child (kvmd/tools.py:124), same as
            # every openssl call site in api/system.py. Fail closed.
            get_logger(0).error("WebAuthn: openssl verification failed to run: %s", ex)
            return False
    if retcode == 0:
        return True
    get_logger(0).error("WebAuthn: openssl rejected the signature (rc=%d): %s", retcode, stderr.strip())
    return False


async def verify_es256(spki: bytes, message: bytes, signature: bytes, openssl_cmd: list[str]) -> bool:
    fast = verify_es256_cryptography(spki, message, signature)
    if fast is not None:
        return fast
    return (await verify_es256_openssl(spki, message, signature, openssl_cmd))


# =====
@dataclasses.dataclass(frozen=True)
class Credential:
    cred_id:    bytes
    spki:       bytes
    user:       str
    sign_count: int
    aaguid:     str
    label:      str
    roles:      tuple[str, ...]


class CredentialStore:
    """Reader for the ticket-delivered /etc/kvmd/user/webauthn.json.

    The file is chmod 444 and is written by apply_to_glkvm.sh, never by kvmd:
    registration happens off-device (docs/webauthn.md section 5). So this class
    never writes, and a missing or empty file is a normal unenrolled device
    rather than an error.
    """

    VERSION = 1

    def __init__(self, path: str) -> None:
        self.__path = path
        self.__stamp: tuple = ()
        self.__creds: dict[bytes, Credential] = {}
        self.__counters: dict[bytes, int] = {}
        self.__complained = False

    def reload(self) -> None:
        try:
            st = os.stat(self.__path)
        except FileNotFoundError:
            if self.__creds or not self.__complained:
                get_logger(0).info("WebAuthn: no credential store at %s; no keys are enrolled", self.__path)
                self.__complained = True
            self.__stamp = ()
            self.__creds = {}
            return
        except OSError as ex:
            self.__keep_previous(f"can't stat {self.__path}: {ex}")
            return

        stamp = (st.st_mtime_ns, st.st_size)
        if stamp == self.__stamp and self.__creds:
            return
        try:
            with open(self.__path, "rb") as file:
                creds = self.__parse(file.read())
        except WebAuthnError as ex:
            self.__keep_previous(str(ex))
            return
        except Exception as ex:
            self.__keep_previous(f"can't read {self.__path}: {ex}")
            return

        self.__stamp = stamp
        self.__creds = creds
        self.__complained = False
        for (cred_id, cred) in creds.items():
            # Seed the high-water mark, but never lower one we have already seen
            # in this process: a re-applied ticket must not roll signCount back.
            self.__counters[cred_id] = max(self.__counters.get(cred_id, 0), cred.sign_count)
        get_logger(0).info("WebAuthn: loaded %d credential(s) from %s", len(creds), self.__path)

    def __keep_previous(self, reason: str) -> None:
        # A broken file must not silently disable the second factor, so the last
        # good set stays live and the failure is loud.
        get_logger(0).error("WebAuthn: keeping the previous credential set; %s", reason)

    def __parse(self, raw: bytes) -> dict[bytes, Credential]:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except Exception as ex:
            raise WebAuthnError(f"malformed JSON in {self.__path}: {ex}")
        if not isinstance(doc, dict):
            raise WebAuthnError(f"{self.__path} is not a JSON object")
        if doc.get("version") != self.VERSION:
            raise WebAuthnError(f"unsupported store version {doc.get('version')!r}, expected {self.VERSION}")
        items = doc.get("credentials", [])
        if not isinstance(items, list):
            raise WebAuthnError("'credentials' is not a list")

        creds: dict[bytes, Credential] = {}
        for (index, item) in enumerate(items):
            cred = self.__parse_one(index, item)
            if cred.cred_id in creds:
                raise WebAuthnError(f"credential #{index} repeats an earlier credential_id")
            creds[cred.cred_id] = cred
        return creds

    def __parse_one(self, index: int, item: Any) -> Credential:
        if not isinstance(item, dict):
            raise WebAuthnError(f"credential #{index} is not an object")
        cred_id = b64u_decode(str(item.get("credential_id", "")), f"credential #{index} credential_id")
        if not cred_id:
            raise WebAuthnError(f"credential #{index} has an empty credential_id")
        cose = b64u_decode(str(item.get("public_key_cose", "")), f"credential #{index} public_key_cose")
        spki = cose_es256_to_spki(cose)

        # The username gap docs/lean-plan.md step 11 flagged: _Session asserts a
        # non-empty UNIX-style user (auth.py:55-59) matching valid_user, and the
        # design's credential tuple had no such field. It is required here, and
        # it is enforced at LOAD time so a bad ticket fails loudly at startup.
        try:
            user = valid_user(item.get("user", ""))
        except Exception as ex:
            raise WebAuthnError(f"credential #{index} has no usable 'user': {ex}")

        sign_count = item.get("sign_count", 0)
        if not isinstance(sign_count, int) or isinstance(sign_count, bool) or sign_count < 0:
            raise WebAuthnError(f"credential #{index} has a bad sign_count {sign_count!r}")

        roles = item.get("roles", [])
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise WebAuthnError(f"credential #{index} has a bad 'roles'")

        return Credential(
            cred_id=cred_id,
            spki=spki,
            user=user,
            sign_count=sign_count,
            aaguid=str(item.get("aaguid", "")),
            label=str(item.get("label", "")),
            # Metadata only. NOTHING in kvmd consults a role: _Session carries a
            # username and nothing else (auth.py:49-59). Never gate on this.
            roles=tuple(roles),
        )

    def get(self, cred_id: bytes) -> (Credential | None):
        return self.__creds.get(cred_id)

    def get_all(self) -> list[Credential]:
        return list(self.__creds.values())

    def get_counter(self, cred_id: bytes) -> int:
        return self.__counters.get(cred_id, 0)

    def bump_counter(self, cred_id: bytes, sign_count: int) -> None:
        self.__counters[cred_id] = sign_count


# =====
@dataclasses.dataclass(frozen=True)
class _Pending:
    purpose:   str
    expire_ts: float


def get_default_origins() -> tuple[str, ...]:
    """The device's own origin.

    The RP ID is fleet-wide on purpose -- one credential registered once
    asserts on every device -- but the accepted ORIGIN is deliberately not.
    Suffix-matching the RP ID would let anything serving HTTPS under the parent
    domain fetch this device's challenge, collect an assertion at its own
    origin and replay it here. docs/webauthn.md section 4.
    """
    return (f"https://{socket.getfqdn().strip().lower()}",)


class Plugin(BaseAuthService):  # pylint: disable=too-many-instance-attributes
    def __init__(  # pylint: disable=super-init-not-called
        self,
        path: str,
        rp_id: str,
        origins: list[str],
        challenge_ttl: int,
        max_pending: int,
        require_uv: bool,
        openssl_cmd: list[str],
    ) -> None:

        self.__rp_id = rp_id.strip().lower()
        self.__rp_id_hash = hashlib.sha256(self.__rp_id.encode("utf-8")).digest()
        self.__origins = tuple(origin.strip().lower() for origin in origins if origin.strip())
        self.__challenge_ttl = challenge_ttl
        self.__max_pending = max_pending
        self.__require_uv = require_uv
        self.__openssl_cmd = list(openssl_cmd)
        self.__store = CredentialStore(path)
        self.__pending: dict[str, _Pending] = {}

    @classmethod
    def get_plugin_options(cls) -> dict:
        return {
            # Not valid_abs_file: that stat()s the path at config-load time
            # (validators/os.py:56-63), so an unenrolled device with no
            # credential file would refuse to start kvmd at all.
            "file":          Option("/etc/kvmd/user/webauthn.json", type=valid_abs_path, unpack_as="path"),
            "rp_id":         Option("", type=valid_stripped_string),
            "origins":       Option([], type=valid_string_list),
            "challenge_ttl": Option(120, type=valid_int_f1),
            "max_pending":   Option(32, type=valid_int_f1),
            "require_uv":    Option(False, type=valid_bool),
            "openssl_cmd":   Option(["/usr/bin/openssl"], type=valid_command),
        }

    # =====

    async def authorize(self, user: str, passwd: str) -> bool:
        """Always False, deliberately.

        AuthManager.authorize() (auth.py:136-154) is the only caller of a
        plugin's authorize(), and it passes a PASSWORD. A WebAuthn assertion
        cannot be smuggled through a passwd: str, so this plugin is not a
        password service and must not be configured as
        kvmd/auth/{internal,external}. Failing closed means such a
        misconfiguration authenticates nobody instead of everybody.
        """
        get_logger(0).error(
            "WebAuthn: refusing password authorization for user %r (passwd len=%d)."
            " This plugin is not an internal/external auth service; see docs/webauthn.md.",
            user, len(passwd),
        )
        return False

    async def cleanup(self) -> None:
        self.__pending.clear()

    # =====

    def is_configured(self) -> bool:
        return bool(self.__rp_id)

    def get_pending_count(self) -> int:
        return len(self.__pending)

    def get_credentials_info(self) -> list[dict]:
        """Enrolment-side view of the store. Metadata only; no key material."""
        self.__store.reload()
        return [
            {
                "credential_id": b64u_encode(cred.cred_id),
                "user":          cred.user,
                "label":         cred.label,
                "aaguid":        cred.aaguid,
                "roles":         list(cred.roles),
                "sign_count":    self.__store.get_counter(cred.cred_id),
            }
            for cred in self.__store.get_all()
        ]

    def make_challenge(self, purpose: str="login") -> dict:
        """The PublicKeyCredentialRequestOptions body for GET /auth/webauthn/challenge.

        allowCredentials is ALWAYS empty. That route is auth_required=False, so
        listing credential IDs would hand the whole store to an unauthenticated
        caller; the credential is instead located from the assertion's own
        rawId. Registration must therefore use residentKey: "required".

        A challenge is issued even when nothing is enrolled, so that the route
        is not an oracle for "is this device enrolled yet".
        """
        if not self.is_configured():
            raise WebAuthnError("WebAuthn is not configured: rp_id is empty")
        assert purpose == purpose.strip()
        assert purpose
        self.__prune_pending()
        challenge = secrets.token_bytes(32)
        key = b64u_encode(challenge)
        self.__pending[key] = _Pending(purpose=purpose, expire_ts=(time.monotonic() + self.__challenge_ttl))
        return {
            "publicKey": {
                "challenge":        key,
                "rpId":             self.__rp_id,
                "allowCredentials": [],
                "userVerification": ("required" if self.__require_uv else "preferred"),
                "timeout":          (self.__challenge_ttl * 1000),
            },
        }

    async def verify_assertion(
        self,
        credential_id: str,
        client_data_json: str,
        authenticator_data: str,
        signature: str,
    ) -> tuple[str, str]:
        """Verify one assertion. Returns (user, purpose); raises WebAuthnError.

        The order is deliberate: every cheap structural check runs before the
        openssl subprocess, so an unauthenticated caller cannot make the device
        fork for free.
        """
        if not self.is_configured():
            raise WebAuthnError("WebAuthn is not configured: rp_id is empty")

        raw_client_data = b64u_decode(client_data_json, "clientDataJSON")
        raw_auth_data = b64u_decode(authenticator_data, "authenticatorData")
        raw_signature = b64u_decode(signature, "signature")
        cred_id = b64u_decode(credential_id, "credential id")

        # Popped before anything else is checked, so a challenge is single-use
        # even against a burst of concurrent replays.
        purpose = self.__consume_challenge(raw_client_data)

        self.__store.reload()
        cred = self.__store.get(cred_id)
        if cred is None:
            raise WebAuthnError(f"Unknown credential {b64u_encode(cred_id)!r}")

        sign_count = self.__check_auth_data(raw_auth_data)

        message = raw_auth_data + hashlib.sha256(raw_client_data).digest()
        if not (await verify_es256(cred.spki, message, raw_signature, self.__openssl_cmd)):
            raise WebAuthnError(f"Bad ES256 signature for credential of user {cred.user!r}")

        self.__check_sign_count(cred, sign_count)

        get_logger(0).info("WebAuthn: verified assertion for user %r (label=%r, purpose=%r, signCount=%d)",
                           cred.user, cred.label, purpose, sign_count)
        return (cred.user, purpose)

    # =====

    def __prune_pending(self) -> None:
        now = time.monotonic()
        for (key, pending) in list(self.__pending.items()):
            if pending.expire_ts <= now:
                del self.__pending[key]
        # The challenge route is unauthenticated, so an uncapped dict is a
        # memory-growth primitive. Evict oldest-first once the cap is reached.
        while len(self.__pending) >= self.__max_pending:
            oldest = min(self.__pending, key=(lambda key: self.__pending[key].expire_ts))
            del self.__pending[oldest]

    def __consume_challenge(self, raw_client_data: bytes) -> str:
        try:
            client_data = json.loads(raw_client_data.decode("utf-8"))
        except Exception as ex:
            raise WebAuthnError(f"Malformed clientDataJSON: {ex}")
        if not isinstance(client_data, dict):
            raise WebAuthnError("clientDataJSON is not an object")

        if client_data.get("type") != "webauthn.get":
            raise WebAuthnError(f"Wrong clientData type {client_data.get('type')!r}, expected 'webauthn.get'")
        if client_data.get("crossOrigin", False):
            raise WebAuthnError("clientData says crossOrigin")

        origin = str(client_data.get("origin", "")).strip().lower()
        accepted = (self.__origins or get_default_origins())
        if origin not in accepted:
            raise WebAuthnError(f"Origin {origin!r} is not in {list(accepted)!r}")

        got = client_data.get("challenge", "")
        if not isinstance(got, str) or not got:
            raise WebAuthnError("clientData carries no challenge")
        for key in list(self.__pending):
            if hmac.compare_digest(key, got):
                pending = self.__pending.pop(key)
                if pending.expire_ts <= time.monotonic():
                    raise WebAuthnError("Challenge has expired")
                return pending.purpose
        raise WebAuthnError("Unknown or already-used challenge")

    def __check_auth_data(self, raw: bytes) -> int:
        if len(raw) < 37:
            raise WebAuthnError(f"authenticatorData is {len(raw)} bytes, need at least 37")
        if not hmac.compare_digest(raw[:32], self.__rp_id_hash):
            raise WebAuthnError(f"rpIdHash does not match rp_id {self.__rp_id!r}")
        flags = raw[32]
        if not flags & 0x01:
            # User presence. Required on EVERY assertion, which is what makes an
            # assertion a proof that a human touched the key just now.
            raise WebAuthnError("The UP (user presence) flag is not set")
        if self.__require_uv and not flags & 0x04:
            raise WebAuthnError("The UV (user verification) flag is not set")
        return int.from_bytes(raw[33:37], "big")

    def __check_sign_count(self, cred: Credential, sign_count: int) -> None:
        """Strictly increasing, in memory only.

        The store is ticket-delivered and read-only (docs/webauthn.md section
        7.3), so the mark cannot be persisted and clone detection does not
        survive a kvmd restart. Authenticators with no counter report 0 forever;
        0 against a 0 mark is the standard carve-out, not a shortcut.
        """
        mark = self.__store.get_counter(cred.cred_id)
        if sign_count == 0 and mark == 0:
            return
        if sign_count <= mark:
            raise WebAuthnError(
                f"signCount did not increase for user {cred.user!r}:"
                f" got {sign_count}, already saw {mark} (cloned authenticator?)"
            )
        self.__store.bump_counter(cred.cred_id, sign_count)
