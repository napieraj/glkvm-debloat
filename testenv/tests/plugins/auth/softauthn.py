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


"""A software authenticator, for tests ONLY.

It exists so the WebAuthn plugin can be exercised against real ES256
signatures with no network, no `cryptography` (which is absent from the test
interpreter, testenv/Dockerfile and testenv/requirements.txt) and no key
material on any device. Everything here shells out to `openssl`, which
testenv/Dockerfile:14-15 provides and which GL.iNet's own runtime code already
depends on (api/system.py:1744 and eight more).

Nothing in this module may be imported by kvmd. Devices do not generate
credentials; see docs/webauthn.md section 5.
"""


import os
import json
import base64
import hashlib
import subprocess

from typing import Any


# =====
OPENSSL = "/usr/bin/openssl"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


# =====
def cbor_head(major: int, arg: int) -> bytes:
    if arg < 24:
        return bytes([(major << 5) | arg])
    if arg < 0x100:
        return bytes([(major << 5) | 24, arg])
    if arg < 0x10000:
        return bytes([(major << 5) | 25]) + arg.to_bytes(2, "big")
    raise AssertionError("The test encoder does not need bigger arguments")


def cbor_int(value: int) -> bytes:
    return (cbor_head(0, value) if value >= 0 else cbor_head(1, (-1 - value)))


def cbor_bytes(value: bytes) -> bytes:
    return cbor_head(2, len(value)) + value


def cbor_text(value: str) -> bytes:
    raw = value.encode("utf-8")
    return cbor_head(3, len(raw)) + raw


def make_cose_key(x: bytes, y: bytes, kty: int=2, alg: int=-7, crv: int=1) -> bytes:
    return (
        cbor_head(5, 5)
        + cbor_int(1) + cbor_int(kty)
        + cbor_int(3) + cbor_int(alg)
        + cbor_int(-1) + cbor_int(crv)
        + cbor_int(-2) + cbor_bytes(x)
        + cbor_int(-3) + cbor_bytes(y)
    )


# =====
def make_auth_data(rp_id: str, flags: int=0x05, sign_count: int=0) -> bytes:
    return (
        hashlib.sha256(rp_id.encode("utf-8")).digest()
        + bytes([flags])
        + sign_count.to_bytes(4, "big")
    )


def make_client_data(
    challenge: str,
    origin: str,
    ctype: str="webauthn.get",
    cross_origin: bool=False,
) -> bytes:

    return json.dumps({
        "type": ctype,
        "challenge": challenge,
        "origin": origin,
        "crossOrigin": cross_origin,
    }).encode("utf-8")


# =====
class SoftKey:
    """One P-256 keypair, generated and used through openssl."""

    def __init__(self, work_dir: str, name: str="softkey") -> None:
        self.__key_path = os.path.join(work_dir, f"{name}.key.pem")
        self.__work_dir = work_dir
        self.__run("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", self.__key_path)
        der = self.__run("ec", "-in", self.__key_path, "-pubout", "-outform", "DER")
        assert len(der) == 91, f"Unexpected SPKI length {len(der)}"
        assert der[26] == 0x04, "Expected an uncompressed point"
        self.spki = der
        self.x = der[27:59]
        self.y = der[59:91]
        self.cred_id = hashlib.sha256(der).digest()[:16]

    def __run(self, *args: str) -> bytes:
        proc = subprocess.run([OPENSSL, *args], check=True, capture_output=True)
        return proc.stdout

    def cose(self, **kwargs: Any) -> bytes:
        return make_cose_key(self.x, self.y, **kwargs)

    def sign(self, message: bytes) -> bytes:
        msg_path = os.path.join(self.__work_dir, "sign-input.bin")
        with open(msg_path, "wb") as file:
            file.write(message)
        return self.__run("dgst", "-sha256", "-sign", self.__key_path, msg_path)

    def store_entry(self, user: str="admin", **extra: Any) -> dict:
        entry = {
            "credential_id": b64u(self.cred_id),
            "public_key_cose": b64u(self.cose()),
            "user": user,
            "sign_count": 0,
            "aaguid": b64u(b"\x00" * 16),
            "label": "test key",
            "roles": ["admin"],
        }
        entry.update(extra)
        return entry


def write_store(path: str, entries: list, version: Any=1) -> None:
    with open(path, "w") as file:
        json.dump({"version": version, "credentials": entries}, file)
