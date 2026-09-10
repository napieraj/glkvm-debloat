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
import json
import time
import hashlib
import pathlib

from typing import Any

import pytest

from kvmd.yamlconf import make_config

from kvmd.plugins.auth import get_auth_service_class
from kvmd.plugins.auth.webauthn import Credential
from kvmd.plugins.auth.webauthn import CredentialStore
from kvmd.plugins.auth.webauthn import Plugin
from kvmd.plugins.auth.webauthn import WebAuthnError
from kvmd.plugins.auth.webauthn import b64u_decode
from kvmd.plugins.auth.webauthn import b64u_encode
from kvmd.plugins.auth.webauthn import cbor_loads
from kvmd.plugins.auth.webauthn import cose_es256_to_spki
from kvmd.plugins.auth.webauthn import get_default_origins
from kvmd.plugins.auth.webauthn import spki_to_pem
from kvmd.plugins.auth.webauthn import verify_es256
from kvmd.plugins.auth.webauthn import verify_es256_cryptography
from kvmd.plugins.auth.webauthn import verify_es256_openssl

from . import softauthn
from .softauthn import SoftKey


# =====
_RP_ID = "oskar.co"
_ORIGIN = "https://kvm-pve1.oskar.co"
_OPENSSL = [softauthn.OPENSSL]


def _make_plugin(**kwargs: Any) -> Plugin:
    """Construct through make_config, so the option contract is exercised too."""
    cls = get_auth_service_class("webauthn")
    assert cls is Plugin
    config = make_config(kwargs, cls.get_plugin_options())
    plugin = cls(**config._unpack())  # pylint: disable=protected-access
    assert isinstance(plugin, Plugin)
    return plugin


def _enrolled(tmp_path: pathlib.Path, key: SoftKey, **kwargs: Any) -> Plugin:
    store_path = str(tmp_path / "webauthn.json")
    softauthn.write_store(store_path, [key.store_entry()])
    kwargs.setdefault("file", store_path)
    kwargs.setdefault("rp_id", _RP_ID)
    kwargs.setdefault("origins", [_ORIGIN])
    return _make_plugin(**kwargs)


def _assert_args(
    key: SoftKey,
    challenge: str,
    origin: str=_ORIGIN,
    flags: int=0x05,
    sign_count: int=0,
    rp_id: str=_RP_ID,
    ctype: str="webauthn.get",
    cross_origin: bool=False,
    tamper: bool=False,
) -> dict:

    client_data = softauthn.make_client_data(challenge, origin, ctype, cross_origin)
    auth_data = softauthn.make_auth_data(rp_id, flags, sign_count)
    signed = (auth_data + hashlib.sha256(client_data).digest())
    signature = key.sign(signed if not tamper else (signed + b"x"))
    return {
        "credential_id": softauthn.b64u(key.cred_id),
        "client_data_json": softauthn.b64u(client_data),
        "authenticator_data": softauthn.b64u(auth_data),
        "signature": softauthn.b64u(signature),
    }


# ===== base64url =====
def test_ok__b64u_roundtrip() -> None:
    for raw in [b"", b"\x00", b"abc", bytes(range(256))]:
        encoded = b64u_encode(raw)
        assert "=" not in encoded
        assert b64u_decode(encoded) == raw


@pytest.mark.parametrize("bad", ["a+b", "a/b", "a=b", "a b", "!!"])
def test_fail__b64u_rejects_non_urlsafe(bad: str) -> None:
    with pytest.raises(WebAuthnError):
        b64u_decode(bad)


# ===== CBOR =====
def test_ok__cbor_shapes() -> None:
    assert cbor_loads(b"\x00") == 0
    assert cbor_loads(b"\x17") == 23
    assert cbor_loads(b"\x18\xff") == 255
    assert cbor_loads(b"\x19\x01\x00") == 256
    assert cbor_loads(b"\x1a\x00\x01\x00\x00") == 65536
    assert cbor_loads(b"\x1b" + (2 ** 40).to_bytes(8, "big")) == 2 ** 40
    assert cbor_loads(b"\x26") == -7
    assert cbor_loads(softauthn.cbor_bytes(b"hi")) == b"hi"
    assert cbor_loads(softauthn.cbor_text("hi")) == "hi"
    assert cbor_loads(softauthn.cbor_head(4, 2) + b"\x01\x02") == [1, 2]
    assert cbor_loads(softauthn.cbor_head(5, 1) + b"\x01\x02") == {1: 2}


@pytest.mark.parametrize("raw", [
    b"",                                    # empty
    b"\x18",                                # truncated argument
    b"\x42a",                               # truncated byte string
    b"\x00\x00",                            # trailing bytes
    b"\x5f\x42ab\xff",                      # indefinite length
    b"\xc0\x00",                            # tag
    b"\xf5",                                # simple value (true)
    b"\x1c",                                # reserved additional info
    b"\xa2\x01\x01\x01\x02",                # duplicate map key
    b"\xa1\x81\x01\x01",                    # unhashable (array) map key
])
def test_fail__cbor_rejects(raw: bytes) -> None:
    with pytest.raises(WebAuthnError):
        cbor_loads(raw)


def test_fail__cbor_depth_capped() -> None:
    raw = b"\x00"
    for _ in range(8):
        raw = softauthn.cbor_head(4, 1) + raw
    with pytest.raises(WebAuthnError):
        cbor_loads(raw)


# ===== COSE -> SPKI =====
def test_ok__cose_spki_matches_openssl(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    # The whole openssl path rests on this: reassembling the SPKI from the two
    # COSE coordinates must reproduce what `openssl ec -pubout -outform DER` emits.
    assert cose_es256_to_spki(key.cose()) == key.spki
    pem = spki_to_pem(key.spki)
    assert pem.startswith("-----BEGIN PUBLIC KEY-----\n")
    assert pem.endswith("-----END PUBLIC KEY-----\n")


@pytest.mark.parametrize("kwargs", [
    {"kty": 3},     # not EC2
    {"alg": -257},  # RS256
    {"alg": -8},    # EdDSA
    {"crv": 6},     # Ed25519
])
def test_fail__cose_es256_only(tmp_path: pathlib.Path, kwargs: dict) -> None:
    key = SoftKey(str(tmp_path))
    with pytest.raises(WebAuthnError):
        cose_es256_to_spki(key.cose(**kwargs))


def test_fail__cose_short_coordinate(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    with pytest.raises(WebAuthnError):
        cose_es256_to_spki(softauthn.make_cose_key(key.x[:31], key.y))
    with pytest.raises(WebAuthnError):
        cose_es256_to_spki(softauthn.make_cose_key(key.x, key.y + b"\x00"))


def test_fail__cose_not_a_map() -> None:
    with pytest.raises(WebAuthnError):
        cose_es256_to_spki(b"\x01")


# ===== ES256 verification =====
@pytest.mark.asyncio
async def test_ok__es256_openssl_verifies(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    signature = key.sign(b"hello world")
    assert (await verify_es256_openssl(key.spki, b"hello world", signature, _OPENSSL))
    assert not (await verify_es256_openssl(key.spki, b"hello worlX", signature, _OPENSSL))
    assert not (await verify_es256_openssl(key.spki, b"hello world", b"garbage", _OPENSSL))


@pytest.mark.asyncio
async def test_ok__es256_openssl_missing_binary(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    signature = key.sign(b"x")
    assert not (await verify_es256_openssl(key.spki, b"x", signature, ["/nonexistent/openssl"]))


def test_ok__cryptography_absent_here(tmp_path: pathlib.Path) -> None:
    # The measured premise of the design: `cryptography` is not importable by the
    # test interpreter, so the fast path declines and openssl does the work. If
    # this ever starts returning a bool, the fast path has become live and needs
    # its own coverage -- see docs/webauthn.md section 1.
    key = SoftKey(str(tmp_path))
    assert verify_es256_cryptography(key.spki, b"x", key.sign(b"x")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fast", [True, False])
async def test_ok__fast_path_short_circuits(monkeypatch: Any, fast: bool) -> None:
    called: list[int] = []

    async def _never(*_: Any, **__: Any) -> bool:
        called.append(1)
        return True

    monkeypatch.setattr("kvmd.plugins.auth.webauthn.verify_es256_cryptography", (lambda *_: fast))
    monkeypatch.setattr("kvmd.plugins.auth.webauthn.verify_es256_openssl", _never)
    assert (await verify_es256(b"", b"", b"", _OPENSSL)) is fast
    assert not called


# ===== the credential store =====
def test_ok__store_missing_file_is_not_an_error(tmp_path: pathlib.Path) -> None:
    store = CredentialStore(str(tmp_path / "nope.json"))
    store.reload()
    assert store.get_all() == []
    store.reload()
    assert store.get_all() == []


def test_ok__store_loads_and_reloads(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "webauthn.json")
    key1 = SoftKey(str(tmp_path), "k1")
    key2 = SoftKey(str(tmp_path), "k2")
    softauthn.write_store(path, [key1.store_entry(user="admin")])
    store = CredentialStore(path)
    store.reload()
    assert len(store.get_all()) == 1
    cred = store.get(key1.cred_id)
    assert isinstance(cred, Credential)
    assert cred.user == "admin"
    assert cred.label == "test key"
    assert cred.roles == ("admin",)
    assert cred.spki == key1.spki
    assert store.get(key2.cred_id) is None

    softauthn.write_store(path, [key1.store_entry(), key2.store_entry(user="operator")])
    os.utime(path, (1, 1))  # Force a different mtime, whatever the filesystem granularity
    store.reload()
    assert len(store.get_all()) == 2
    second = store.get(key2.cred_id)
    assert second is not None
    assert second.user == "operator"


def test_ok__store_empty_list_is_valid(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "webauthn.json")
    softauthn.write_store(path, [])
    store = CredentialStore(path)
    store.reload()
    assert store.get_all() == []


def test_ok__store_seeds_the_counter(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "webauthn.json")
    key = SoftKey(str(tmp_path))
    softauthn.write_store(path, [key.store_entry(sign_count=17)])
    store = CredentialStore(path)
    store.reload()
    assert store.get_counter(key.cred_id) == 17
    store.bump_counter(key.cred_id, 20)
    assert store.get_counter(key.cred_id) == 20
    # A re-applied ticket must not roll the mark back.
    os.utime(path, (2, 2))
    store.reload()
    assert store.get_counter(key.cred_id) == 20


def test_ok__store_keeps_previous_on_bad_file(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "webauthn.json")
    key = SoftKey(str(tmp_path))
    softauthn.write_store(path, [key.store_entry()])
    store = CredentialStore(path)
    store.reload()
    assert len(store.get_all()) == 1
    with open(path, "w") as file:
        file.write("{ not json")
    os.utime(path, (3, 3))
    store.reload()
    # A botched ticket must not silently disable the second factor.
    assert len(store.get_all()) == 1


def _bad_store(tmp_path: pathlib.Path, entries: list, version: Any=1) -> CredentialStore:
    path = str(tmp_path / "webauthn.json")
    softauthn.write_store(path, entries, version)
    return CredentialStore(path)


def test_fail__store_rejects_bad_version(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    store = _bad_store(tmp_path, [key.store_entry()], version=2)
    store.reload()
    assert store.get_all() == []


@pytest.mark.parametrize("override", [
    {"user": ""},               # missing
    {"user": "Admin"},          # valid_user is ^[a-z_][a-z0-9_-]*$
    {"user": "1admin"},
    {"user": "ad min"},
    {"credential_id": ""},      # empty
    {"credential_id": "a+b"},   # not base64url
    {"public_key_cose": ""},    # undecodable as COSE
    {"sign_count": -1},
    {"sign_count": "3"},
    {"sign_count": True},
    {"roles": "admin"},         # not a list
    {"roles": [1]},
])
def test_fail__store_rejects_bad_credential(tmp_path: pathlib.Path, override: dict) -> None:
    key = SoftKey(str(tmp_path))
    store = _bad_store(tmp_path, [key.store_entry(**override)])
    store.reload()
    assert store.get_all() == []


def test_fail__store_rejects_duplicate_id(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    store = _bad_store(tmp_path, [key.store_entry(), key.store_entry(user="operator")])
    store.reload()
    assert store.get_all() == []


def test_fail__store_rejects_non_es256(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    entry = key.store_entry()
    entry["public_key_cose"] = softauthn.b64u(key.cose(alg=-257))
    store = _bad_store(tmp_path, [entry])
    store.reload()
    assert store.get_all() == []


@pytest.mark.parametrize("doc", ["[]", '{"version": 1, "credentials": {}}', '{"credentials": []}'])
def test_fail__store_rejects_bad_document(tmp_path: pathlib.Path, doc: str) -> None:
    path = str(tmp_path / "webauthn.json")
    with open(path, "w") as file:
        file.write(doc)
    store = CredentialStore(path)
    store.reload()
    assert store.get_all() == []


# ===== the plugin: options and the password contract =====
def test_ok__plugin_option_contract() -> None:
    options = get_auth_service_class("webauthn").get_plugin_options()
    assert set(options) == {"file", "rp_id", "origins", "challenge_ttl", "max_pending", "require_uv", "openssl_cmd"}
    assert options["file"].unpack_as == "path"
    plugin = _make_plugin()
    assert not plugin.is_configured()  # No rp_id by default


@pytest.mark.asyncio
async def test_ok__authorize_always_refuses(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    # A password can never authenticate through this plugin, so configuring it as
    # kvmd/auth/internal authenticates nobody rather than everybody.
    for (user, passwd) in [("admin", "admin"), ("admin", ""), ("root", "hunter2")]:
        assert not (await plugin.authorize(user, passwd))
    await plugin.cleanup()


def test_ok__default_origins_is_the_device_fqdn(monkeypatch: Any) -> None:
    monkeypatch.setattr("socket.getfqdn", (lambda: "KVM-PVE2.Oskar.CO "))
    assert get_default_origins() == ("https://kvm-pve2.oskar.co",)


@pytest.mark.asyncio
async def test_fail__origin_is_matched_exactly_not_by_prefix(tmp_path: pathlib.Path) -> None:
    """
    A pinned origin must not admit anything that merely starts with it.

    The three negative origin cases in test_fail__assertion_rejections are all
    rejected by a prefix match too, so none of them separates exact membership
    from `startswith`. Without this case, relaxing the check to a prefix match
    -- the obvious-looking accommodation for a port or a path suffix -- ships
    green while admitting an attacker-controlled host under a longer name.
    """

    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**_assert_args(
            key, challenge, origin=(_ORIGIN + ".attacker.test")))


@pytest.mark.asyncio
async def test_fail__unconfigured_origins_still_pins_to_the_device(
    tmp_path: pathlib.Path,
    monkeypatch: Any,
) -> None:
    """
    The default path is the one a shipped device takes, and it must pin too.

    `origins` defaults to [] and nothing in configs/ sets it, so a real device
    falls through to get_default_origins(). Every other test in this file
    configures origins explicitly (see _enrolled), which left the fallback
    exercised only in isolation and never through verify_assertion -- so
    neutering it did not redden anything.
    """

    monkeypatch.setattr("socket.getfqdn", (lambda: "kvm-pve1.oskar.co"))
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key, origins=[])
    challenge = plugin.make_challenge()["publicKey"]["challenge"]

    # The device's own origin is accepted through the fallback ...
    await plugin.verify_assertion(**_assert_args(key, challenge, origin=_ORIGIN))

    # ... and a sibling under the same RP ID is not.
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**_assert_args(
            key, challenge, origin="https://evil.oskar.co"))


# ===== challenges =====
def test_fail__challenge_needs_rp_id(tmp_path: pathlib.Path) -> None:
    plugin = _make_plugin(file=str(tmp_path / "webauthn.json"))
    with pytest.raises(WebAuthnError):
        plugin.make_challenge()


def test_ok__challenge_shape(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key, challenge_ttl=90)
    body = plugin.make_challenge()["publicKey"]
    assert body["rpId"] == _RP_ID
    # NEVER populated: the challenge route is unauthenticated, so listing
    # credential ids would hand the store to anyone who asks.
    assert body["allowCredentials"] == []
    assert body["userVerification"] == "preferred"
    assert body["timeout"] == 90000
    assert len(b64u_decode(body["challenge"])) == 32
    assert body["challenge"] != plugin.make_challenge()["publicKey"]["challenge"]


def test_ok__challenge_issued_when_unenrolled(tmp_path: pathlib.Path) -> None:
    # Must not be an oracle for "is this device enrolled yet".
    plugin = _make_plugin(file=str(tmp_path / "absent.json"), rp_id=_RP_ID, origins=[_ORIGIN])
    assert plugin.make_challenge()["publicKey"]["challenge"]


def test_ok__challenge_required_uv(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key, require_uv=True)
    assert plugin.make_challenge()["publicKey"]["userVerification"] == "required"


def test_ok__pending_challenges_are_capped(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key, max_pending=4)
    challenges = [plugin.make_challenge()["publicKey"]["challenge"] for _ in range(50)]
    assert len(set(challenges)) == 50
    # The oldest are evicted, so an unauthenticated caller cannot grow the dict.
    assert plugin.get_pending_count() <= 4


# ===== assertions =====
@pytest.mark.asyncio
async def test_ok__assertion_verifies(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge("login")["publicKey"]["challenge"]
    (user, purpose) = await plugin.verify_assertion(**_assert_args(key, challenge))
    assert (user, purpose) == ("admin", "login")


@pytest.mark.asyncio
async def test_ok__purpose_round_trips(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge("atx:power_off")["publicKey"]["challenge"]
    (_, purpose) = await plugin.verify_assertion(**_assert_args(key, challenge))
    assert purpose == "atx:power_off"


@pytest.mark.asyncio
async def test_fail__challenge_is_single_use(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    args = _assert_args(key, challenge)
    assert (await plugin.verify_assertion(**args))[0] == "admin"
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**args)


@pytest.mark.asyncio
async def test_fail__unknown_challenge(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    plugin.make_challenge()
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**_assert_args(key, b64u_encode(b"\x00" * 32)))


@pytest.mark.asyncio
async def test_fail__expired_challenge(tmp_path: pathlib.Path, monkeypatch: Any) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key, challenge_ttl=1)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    args = _assert_args(key, challenge)
    monkeypatch.setattr(time, "monotonic", (lambda: (time.perf_counter() + 3600)))
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**args)


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"origin": "https://evil.oskar.co"},   # a sibling under the same RP ID
    {"origin": "http://kvm-pve1.oskar.co"},
    {"origin": ""},
    {"ctype": "webauthn.create"},
    {"cross_origin": True},
    {"rp_id": "evil.co"},
    {"flags": 0x04},                       # UV but no UP
    {"flags": 0x00},
    {"tamper": True},
])
async def test_fail__assertion_rejections(tmp_path: pathlib.Path, override: dict) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**_assert_args(key, challenge, **override))


@pytest.mark.asyncio
async def test_fail__require_uv(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key, require_uv=True)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**_assert_args(key, challenge, flags=0x01))
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    assert (await plugin.verify_assertion(**_assert_args(key, challenge, flags=0x05)))[0] == "admin"


@pytest.mark.asyncio
async def test_fail__unknown_credential(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path), "enrolled")
    other = SoftKey(str(tmp_path), "attacker")
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**_assert_args(other, challenge))


@pytest.mark.asyncio
async def test_fail__short_authenticator_data(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    args = _assert_args(key, challenge)
    args["authenticator_data"] = b64u_encode(b64u_decode(args["authenticator_data"])[:36])
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**args)


@pytest.mark.asyncio
async def test_fail__unconfigured_plugin_verifies_nothing(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key, rp_id="")
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion("", "", "", "")


@pytest.mark.asyncio
async def test_fail__malformed_wire_fields(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    for field in ["credential_id", "client_data_json", "authenticator_data", "signature"]:
        args = _assert_args(key, challenge)
        args[field] = "not+base64url"
        with pytest.raises(WebAuthnError):
            await plugin.verify_assertion(**args)
    args = _assert_args(key, plugin.make_challenge()["publicKey"]["challenge"])
    args["client_data_json"] = b64u_encode(b"{ not json")
    with pytest.raises(WebAuthnError):
        await plugin.verify_assertion(**args)


# ===== signCount =====
@pytest.mark.asyncio
async def test_ok__sign_count_zero_authenticator(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    for _ in range(3):
        challenge = plugin.make_challenge()["publicKey"]["challenge"]
        assert (await plugin.verify_assertion(**_assert_args(key, challenge, sign_count=0)))[0] == "admin"


@pytest.mark.asyncio
async def test_fail__sign_count_must_increase(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    assert (await plugin.verify_assertion(**_assert_args(key, challenge, sign_count=5)))[0] == "admin"
    for bad in [1, 5]:
        challenge = plugin.make_challenge()["publicKey"]["challenge"]
        with pytest.raises(WebAuthnError):
            await plugin.verify_assertion(**_assert_args(key, challenge, sign_count=bad))
    challenge = plugin.make_challenge()["publicKey"]["challenge"]
    assert (await plugin.verify_assertion(**_assert_args(key, challenge, sign_count=6)))[0] == "admin"


# ===== enrolment-side metadata =====
def test_ok__credentials_info(tmp_path: pathlib.Path) -> None:
    key = SoftKey(str(tmp_path))
    plugin = _enrolled(tmp_path, key)
    info = plugin.get_credentials_info()
    assert len(info) == 1
    assert info[0]["user"] == "admin"
    assert info[0]["label"] == "test key"
    assert info[0]["roles"] == ["admin"]
    assert info[0]["aaguid"] == softauthn.b64u(b"\x00" * 16)
    assert info[0]["credential_id"] == softauthn.b64u(key.cred_id)
    assert info[0]["sign_count"] == 0


def test_ok__sample_store_ships_valid() -> None:
    # configs/kvmd/webauthn.json is the documented empty example that
    # apply_to_glkvm.sh copies to /etc/kvmd/user/webauthn.json.
    sample = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "configs", "kvmd", "webauthn.json")
    with open(sample) as file:
        doc = json.load(file)
    assert doc == {"version": 1, "credentials": []}
    store = CredentialStore(os.path.abspath(sample))
    store.reload()
    assert store.get_all() == []
