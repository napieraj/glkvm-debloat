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
import socket

from typing import Any

import pytest


# =====
# DEVICE ATTESTATION CONTRACT
#
# What a freshly flashed device is verified against post-migration. Each
# assertion corresponds to a finding in docs/audit.md and to the commit that
# closed it, and each is mutation-checked: reverting the underlying strip or fix
# turns the matching test red. If one of these ever passes while the property is
# untrue, the suite is worse than useless -- it certifies a device as safe.
#
# SCOPE, stated because it is easy to over-read. This suite attests the SHIPPED
# TREE: that a route is absent, that a handler is gone, that a resolver reads the
# socket rather than a header. It cannot attest DEVICE STATE. A unit that ran
# earlier firmware may still carry an attacker's key in
# /root/.ssh/authorized_keys, a cron entry, or a running ttyd from the GL.iNet
# image -- none of which any file in this repository can observe. Those checks
# are marked below and require physical hardware; test_on_device_residuals
# documents them and is skipped by default rather than pretending to cover them.
# Two levels: this file is testenv/tests/, the repo root is its grandparent.
# One level short makes every _grep and every os.path.exists assertion VACUOUS --
# they walk a directory that does not exist and find nothing. Caught by the
# mutation check, which is the only reason it was caught at all.
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_ROUTES = os.path.join(os.path.dirname(__file__), "routes.txt")


def _routes() -> list[str]:
    with open(_ROUTES, encoding="utf-8") as file:
        return [line for line in file.read().strip().split("\n") if line]


def _grep(pattern: str, *rel_dirs: str, exts: tuple[str, ...]=(".py",)) -> list[str]:
    """Every matching line under the given trees, minified assets excluded."""
    hits: list[str] = []
    rx = re.compile(pattern)
    for rel in rel_dirs:
        for (dirpath, dirnames, filenames) in os.walk(os.path.join(_ROOT, rel)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in sorted(filenames):
                if not name.endswith(exts) or ".min." in name:
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="replace") as file:
                    for (n, line) in enumerate(file, 1):
                        if rx.search(line):
                            hits.append(f"{os.path.relpath(path, _ROOT)}:{n}: {line.strip()}")
    return hits


# ===== 1. no ssh_key route, and nothing writes root's authorized_keys
def test_attest__no_ssh_key_route() -> None:
    # audit.md CRITICAL 1. POST wrote the raw request body to
    # /root/.ssh/authorized_keys, so any authenticated caller got permanent root
    # SSH, bypassing the certificate-only policy entirely.
    offenders = [r for r in _routes() if "/system/ssh_key" in r]
    assert not offenders, f"the ssh_key route is back: {offenders}"


def test_attest__nothing_writes_authorized_keys() -> None:
    # The route being gone is not enough on its own: what matters is that no code
    # path writes that file. Checked over the whole daemon, not just the module
    # the route lived in.
    hits = _grep(r"authorized_keys", "kvmd")
    assert not hits, f"something writes or reads authorized_keys: {hits}"


# ===== 2. no ttyd / web-shell
def test_attest__no_web_shell() -> None:
    # audit.md MEDIUM. A shell over HTTP defeats a certificate-only SSH policy.
    hits = _grep(r"\bttyd\b|webterm", "kvmd", "web",
                 exts=(".py", ".js", ".pug", ".html", ".css", ".conf"))
    assert not hits, f"the web terminal is back: {hits}"


def test_attest__no_web_shell_route_or_asset() -> None:
    for rel in ("web/kvm/window-webterm.pug", "web/extras/webterm"):
        assert not os.path.exists(os.path.join(_ROOT, rel)), f"{rel} is back"


# ===== 3. no unauthenticated init
def test_attest__no_unauth_init_route() -> None:
    # audit.md CRITICAL 3. Unauthenticated, ungated, unrate-limited, and it set
    # root's /etc/shadow entry for whoever reached the device first.
    offenders = [r for r in _routes() if "/init/init " in r or r.endswith("/init/init")]
    assert not offenders, f"the unauthenticated init route is back: {offenders}"


def test_attest__the_unauthenticated_surface_is_small() -> None:
    # The audit counted 10 unauthenticated routes against upstream's 2. This is a
    # ratchet, not a target: it may only go down. Raising the number here without
    # a finding to justify it is the thing this catches.
    unauth = [r for r in _routes() if "auth=False" in r]
    assert len(unauth) <= 4, (
        f"the unauthenticated surface grew to {len(unauth)}: {unauth}"
    )


def test_attest__one_exe_gated_route_and_it_is_not_the_gui() -> None:
    # audit.md section 3b. allowed_exe_paths authenticates with NO credential of
    # any kind -- _check_exe_path returns True on a path match alone -- so every
    # route carrying it is a route whose only gate is "which binary opened the
    # socket". The strip (lean-plan steps 3, 5 and 6) took all 31 gl_kvm_gui
    # callers; the one survivor is gl-pion's HID relay. The primitive itself is
    # DECIDED-kept for the beacon's local auth path, which is exactly why its
    # caller count needs a ratchet: a reused primitive regrows callers quietly.
    exe_gated = [r for r in _routes() if not r.endswith("exe=-")]
    assert len(exe_gated) == 1, f"the exe-gated surface changed: {exe_gated}"
    assert "exe=/usr/bin/gl-pion" in exe_gated[0], exe_gated[0]
    assert not [r for r in exe_gated if "gl_kvm_gui" in r], exe_gated


def test_attest__no_gui_process_signalling() -> None:
    # The GUI coupling was two-way: routes in, SIGUSR1 out of every WS open and
    # close. Both halves go, or a kvmd with no gui_* routes still shells out to
    # killall on a binary this build does not ship.
    #
    # Matched QUOTED only. Both live forms of the name were string literals --
    # the killall argument and the allowed_exe_paths entry -- while the three
    # surviving references are prose in a comment or a docstring, where the name
    # appears bare. That is what separates a caller from an explanation here,
    # and why this cannot just grep for the name.
    hits = _grep(r"[\"']gl_kvm_gui[\"']|/usr/sbin/gl_kvm_gui", "kvmd")
    assert not hits, f"live gl_kvm_gui references are back: {hits}"


# ===== 4. header-trust fixed: identity comes from the socket peer
class _FakeTransport:
    def __init__(self, sock: Any, peername: Any) -> None:
        self.__sock = sock
        self.__peername = peername

    def get_extra_info(self, name: str, default: Any=None) -> Any:
        if name == "socket":
            return self.__sock
        if name == "peername":
            return self.__peername
        return default


class _FakeRequest:
    def __init__(self, transport: Any, headers: (dict | None)=None) -> None:
        self.transport = transport
        self.headers = (headers or {})


def test_attest__client_identity_ignores_a_spoofed_header() -> None:
    # audit.md HIGH. _get_client_ip took a headers dict, so every lockout, rate
    # limit and "local network only" decision was keyed on a value the caller
    # supplied. A remote peer claiming to be on the LAN must not be believed.
    from kvmd.apps.kvmd.api.auth import get_client_ip
    req = _FakeRequest(_FakeTransport(None, ("8.8.8.8", 54321)),
                       {"X-Real-IP": "192.168.1.1", "X-Forwarded-For": "10.0.0.1"})
    assert get_client_ip(req) == "8.8.8.8"  # type: ignore[arg-type]


def test_attest__client_identity_trusts_the_local_proxy() -> None:
    # The other half: nginx reaches kvmd over a Unix socket and its X-Real-IP is
    # the only source of a real client address. A fix that ignored it everywhere
    # would collapse every client into one bucket.
    from kvmd.apps.kvmd.api.auth import get_client_ip
    (sock, other) = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        req = _FakeRequest(_FakeTransport(sock, None), {"X-Real-IP": "192.168.7.50"})
        assert get_client_ip(req) == "192.168.7.50"  # type: ignore[arg-type]
    finally:
        sock.close()
        other.close()


def test_attest__no_authorization_from_a_headers_dict() -> None:
    # Structural: the old signature took a dict, so passing headers was
    # expressible at the call site. It now takes the request, and nothing may
    # reintroduce a dict-shaped identity function.
    import inspect
    from kvmd.apps.kvmd.api.auth import get_client_ip
    params = list(inspect.signature(get_client_ip).parameters)
    assert params == ["req"], f"get_client_ip no longer takes the request: {params}"


# ===== 5. shipped config is at defaults
def test_attest__no_cron_in_the_shipped_tree() -> None:
    hits = _grep(r"crontab|cron\.d|/etc/cron", "kvmd", "configs",
                 exts=(".py", ".conf", ".yaml", ".install"))
    assert not hits, f"the tree ships a cron entry: {hits}"


def test_attest__the_reference_credential_store_is_empty() -> None:
    # configs/kvmd/webauthn.json is the documented empty example. If it ever
    # ships with a credential in it, every flashed device trusts that key.
    import json
    path = os.path.join(_ROOT, "configs", "kvmd", "webauthn.json")
    if not os.path.exists(path):
        pytest.skip("no reference credential store in this tree")
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    assert not data.get("credentials"), "the shipped reference store contains a credential"


# ===== the strip stays stripped, and the inventory matches
_STRIPPED = [
    "tailscale", "zerotier", "netbird", "netbird_daemon", "cloudflare",
    "astrowarp", "turn", "repeater", "ap", "modem", "custom_screen", "twofa",
]


@pytest.mark.parametrize("module", _STRIPPED)
def test_attest__stripped_modules_stay_stripped(module: str) -> None:
    path = os.path.join(_ROOT, "kvmd", "apps", "kvmd", "api", f"{module}.py")
    assert not os.path.exists(path), f"api/{module}.py came back"


@pytest.mark.parametrize("module", _STRIPPED)
def test_attest__no_dangling_reference_to_a_stripped_module(module: str) -> None:
    # A file can be deleted while server.py still imports it -- that fails at
    # construction, not import, which is why this is checked separately.
    hits = _grep(rf"\bapi\.{module}\b|from \.{module} import", "kvmd")
    assert not hits, f"something still references the stripped {module}: {hits}"


def test_attest__route_inventory_matches_the_fixture() -> None:
    # The same AST walk as test_routes.py, asserted here too so that an
    # attestation run is self-contained: a device is certified against the
    # inventory, not against whatever the source happens to declare today.
    import sys
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from testenv.tests.test_routes import collect_routes
    assert collect_routes() == _routes()


# ===== the part this suite CANNOT attest
@pytest.mark.skip(reason="requires physical hardware; see the docstring")
def test_on_device_residuals() -> None:
    """Checks that need a flashed unit, recorded so they are not forgotten.

    None of these is observable from this repository, and the source-level tests
    above do NOT cover them. On a device that ran earlier firmware:

      1. /root/.ssh/authorized_keys -- absent or containing only keys the
         operator put there. The ssh_key route is gone, but deleting a writer
         does not delete what it wrote.
      2. crontab -l and /etc/cron.d -- no inherited entries. The tree ships
         none; an image or an intruder may have added some.
      3. ttyd -- the service absent or masked. S80ttyd belongs to the GL.iNet
         image, not this repo, so stripping the client does not remove it.
      4. /etc/kvmd/user/htpasswd -- rehashed. The {SSHA512} fix applies to
         passwords set after it; an existing $apr1$ hash survives an upgrade, so
         the password must be CHANGED.
      5. /etc/shadow -- root's entry is what the operator set, not what an
         unauthenticated /init/init call left behind.

    Implement against a real unit or a device fixture, not by inference from the
    source tree.
    """
    raise AssertionError("unreachable: this test documents the on-device checks")
