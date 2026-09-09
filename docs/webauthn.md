# WebAuthn on the RM1PE — design

Steps 11 and 12 of `docs/lean-plan.md`, design phase. This document is the
design plus the integration checklist; the only code that lands with it is
net-new (`kvmd/plugins/auth/webauthn.py`, its tests, and a sample
`configs/kvmd/webauthn.json`). Nothing here edits `kvmd/apps/kvmd/auth.py`,
`kvmd/apps/kvmd/api/auth.py`, `kvmd/htserver.py` or the login flow — every
change those files need is written down in section 11 instead.

Every line number below was re-derived against the worktree at
`930142e` (`claude/glkvm-webauthn`, branched from `claude/glkvm-status-hutk39`).
Facts are marked **[verified]** when they were read out of this tree or measured
in a run, **[assumed]** when they are a design choice or a claim about the
device that this repository cannot prove, and **[reported]** when they come
from `docs/lean-plan.md` / `docs/audit.md` rather than from a fresh read.

---

## 1. The crypto premise, measured

The plan's step 11 and the design it came from assume ES256 verification has to
go through an `openssl` subprocess because `cryptography` is not on the device.
That assumption was checked before any verification code was written, because
if it were wrong the design would collapse to about forty lines.

**It holds, and the decisive evidence is not the one the plan cites.**

| question | answer | evidence |
|---|---|---|
| `cryptography` in `PKGBUILD` depends? | **no** | `PKGBUILD:51-79` lists 30 `python-*` deps; `cryptography` is not among them. `PKGBUILD:84` and `:104` do list `openssl` and `openssl-1.1`. **[verified]** |
| any Python file in this tree import it? | **no** | `grep -rn 'from cryptography\|import cryptography' --include=*.py .` → zero hits. **[verified]** |
| in the test image? | **no** | `testenv/Dockerfile:37-64` pacman list has no `python-cryptography`; `testenv/requirements.txt` (the `-rrequirements.txt` every tox env pulls, `testenv/tox.ini:14,24,32,49`) is 7 lines and does not list it. **[verified]** |
| importable in the runner? | **no** | `/tmp/claude-0/py312/bin/python -c 'import cryptography'` → `ModuleNotFoundError`. (The container's *system* `python3` has 41.0.7 — a sandbox artefact, not the test interpreter.) **[verified]** |
| `openssl` on the device? | **yes, on GL's own evidence** | `kvmd/apps/kvmd/api/system.py:1744, 1753, 1903, 1934, 1943, 1979, 1987, 2024, 2033` — nine `run_command("openssl", ...)` call sites in GL.iNet's own runtime TLS code. If `openssl` were missing, the fork's certificate handling would be dead on the device. **[verified in-tree]** / **[assumed]** for the device itself |
| `openssl` in the test image? | **yes** | `testenv/Dockerfile:14-15`. In this container: OpenSSL 3.0.13. **[verified]** |
| anything in the tree already does ES256/ECDSA/COSE? | **almost nothing** | `grep -rniE '\bcbor\b\|\bcose\b\|webauthn\|\bfido\b\|ecdsa\|es256\|prime256v1\|secp256r1'` over `*.py` returns exactly one hit: `api/system.py:1744`, `openssl ecparam -name prime256v1` — key *generation*, not verification. No base64url helper exists anywhere in `kvmd/` or `web/share/js/`. **[verified]** |

**The `PKGBUILD` argument is weak and should not be reused.** `docs/lean-plan.md`
already says so at its "CLAIM: python-cryptography is NOT in the PKGBUILD"
entry, and it is right: `PKGBUILD:45,142` sources `pikvm/kvmd` v4.16, `:95`
depends on `raspberrypi-utils`, `:165` installs systemd units — it is upstream
PiKVM's Arch package for a Raspberry Pi and it does not build the RM1PE image.
It cannot even build *this* tree (`setup.py:67-108` omits four packages that
exist on disk, one of which `kvmd/apps/kvmd/__init__.py:41` imports
unconditionally).

The argument that actually decides the question is different and stronger, and
it is about CI rather than about the device: **a `cryptography` code path cannot
be tested here at all.** The pytest interpreter does not have the module and
neither the Dockerfile nor `testenv/requirements.txt` would install it. So even
on a device that happened to ship `cryptography`, shipping it as the primary
verification path would mean shipping the security-critical branch of an
authentication mechanism with zero test coverage. `openssl` is the path that is
both present on GL's own evidence and exercised by the suite.

**Decision.** `openssl dgst` subprocess is the primary and tested path.
`cryptography` is used opportunistically if `import cryptography` succeeds at
call time, because on a device that has it the subprocess is pure cost — but the
module is written so that the openssl path is what the tests drive, and the
`cryptography` branch is a strict fast-path with identical semantics.

A third option — hand-rolled P-256 arithmetic in pure Python — was considered
and rejected. It removes the subprocess and the dependency, and it is about
sixty lines, but it puts bespoke modular arithmetic on the authentication path
of a device that grants console-level control of a hypervisor. Not worth it.

### 1.1 The openssl path, measured end to end

Verified by running it, not by reading man pages:

- `openssl ec -pubout -outform DER` on a `prime256v1` key emits **91 bytes** of
  SubjectPublicKeyInfo: a fixed 26-byte prefix
  `3059301306072a8648ce3d020106082a8648ce3d030107034200`, then `0x04`
  (uncompressed point), then `x` (32) and `y` (32). Reassembling
  `prefix || 0x04 || x || y` from the two COSE coordinates reproduces the DER
  **byte for byte**. **[verified by measurement]**
- Wrapping that DER in `-----BEGIN PUBLIC KEY-----` / base64 / END and calling
  `openssl dgst -sha256 -verify pub.pem -signature sig.bin msg.bin` prints
  `Verified OK` and exits 0; a one-byte change to `msg.bin` prints
  `Verification failure` and exits 1. **[verified by measurement]**
- WebAuthn's ES256 signature is already an ASN.1 `SEQUENCE { r, s }`, which is
  exactly what `dgst -verify` expects — no `(r||s)` → DER conversion is needed.
  The measured signature was 70 bytes, in the normal 70-72 range. **[verified]**
- `-keyform DER` also works on OpenSSL 3.0.13, but PEM is used anyway:
  `PKGBUILD:104` shows the ecosystem still carries `openssl-1.1`, and PEM has no
  version sensitivity. **[verified]**

The module reuses `kvmd.tools.run_command` (`kvmd/tools.py:99-131`), the same
`asyncio.create_subprocess_exec` helper the fork's own openssl call sites use.
It takes an argv list, so no shell is involved and nothing request-derived is
interpolated into a command string — which keeps this code on the right side of
`docs/audit.md` section 3b's shell-subprocess finding.

One inherited wart, recorded rather than fixed: `run_command` wraps
`process.communicate()` in `asyncio.wait_for` (`kvmd/tools.py:124`) and does
**not** kill the child on timeout, so a hung `openssl` leaks a process. Every
`api/system.py` call site has the same behaviour. The plugin passes a short
timeout (5 s) and treats a timeout as verification failure.

---

## 2. What this replaces, and what it does not

TOTP was removed in step 4 and is not coming back (`docs/lean-plan.md`,
"SUPERSEDED — TOTP stays removed"). Between that removal and this landing,
authentication is password-only with no in-application rate limiting
(`docs/audit.md` section 3d). WebAuthn is the replacement second factor and,
for the normal path, the *first* factor too.

What WebAuthn here is **not**:

- **Not a `BaseAuthService` in the ordinary sense.** `AuthManager.authorize()`
  (`kvmd/apps/kvmd/auth.py:136-154`) is the only thing that ever calls a plugin's
  `authorize(user, passwd)`, and it passes a password. A WebAuthn assertion is
  four base64url blobs and cannot be smuggled through a `passwd: str`. The
  plugin therefore lives in `kvmd/plugins/auth/` for shape and discoverability
  and implements `authorize()` as an unconditional `False` (fail closed, so that
  configuring `internal: {type: webauthn}` by mistake authenticates nobody
  rather than everybody), while its real surface is two methods that
  `api/webauthn.py` calls directly.
- **Not a role system.** `_Session` (`auth.py:49-59`) carries `user`,
  `expire_req`, `expire_ts`, `ws_started` and nothing else. Nothing downstream
  of a session consults a role. `roles` in the stored credential is therefore
  *advisory metadata for the enrolment side only*; the plugin exposes it and the
  design forbids treating it as an access control.

---

## 3. Credential model

Shaped like the sibling plugins. The fork's plugin contract, which is **not**
upstream's:

    BasePlugin.__init__(self, **_: Any)          # kvmd/plugins/__init__.py:35-37
    self.__int_service = get_auth_service_class(int_type)(**int_kwargs)
                                                 # kvmd/apps/kvmd/auth.py:108

Upstream changed `BasePlugin.__init__` to take a `yamlconf.Section` and passes
`get_auth_service_class(int_c.type)(int_c)`. That difference is why the
`auth.py` rebase was rejected (`docs/lean-plan.md`, "BLOCKER: the auth.py rebase
is not isolatable"). **This plugin follows the fork: explicit keyword
parameters on `__init__`, `get_plugin_options()` returning
`yamlconf.Option`s, construction via `**kwargs`.** `kvmd/plugins/auth/http.py:20-67`
is the closest template (six options, `unpack_as` unused);
`kvmd/plugins/auth/htpasswd.py:22-32` is the smallest.

Options (`get_plugin_options()`):

| option | default | validator | why |
|---|---|---|---|
| `file` | `/etc/kvmd/user/webauthn.json` | `valid_abs_path`, `unpack_as="path"` | Not `valid_abs_file`: `htpasswd.py:31` uses that and it `os.stat()`s the path at **config load** (`validators/os.py:56-63`), so an unenrolled device with no credential file would fail to start kvmd. **[verified]** |
| `rp_id` | `""` | `valid_stripped_string` | The parent domain. Empty disables the plugin (returns no challenge, verifies nothing). |
| `origins` | `[]` | `valid_string_list` | Exact `https://host[:port]` origins accepted in `clientDataJSON.origin`. Empty means *derive from the device's own hostname* — see §4. |
| `challenge_ttl` | `120` | `valid_int_f1` | Seconds. Longer than `navigator.credentials.get`'s own 60 s so the browser times out first. |
| `max_pending` | `32` | `valid_int_f1` | Bound on outstanding challenges — the challenge route is unauthenticated, so it is a memory-growth primitive without a cap. |
| `require_uv` | `False` | `valid_bool` | Require the UV (user-verified: PIN/biometric) flag, not just UP. Off by default because a bare touch-only key is a legitimate deployment. |
| `openssl_cmd` | `["/usr/bin/openssl"]` | `valid_command` | argv prefix. `valid_command` (`validators/os.py:101-106`) checks `cmd[0]` exists, which turns "openssl is missing" into a startup error instead of a login-time one. |

Public surface beyond `BaseAuthService`:

    make_challenge(purpose: str) -> dict     # the PublicKeyCredentialRequestOptions body
    verify_assertion(...) -> tuple[str, str] # -> (username, purpose); raises WebAuthnError
    get_credentials_info() -> list[dict]     # label/aaguid/roles/user, for the enrolment side
    get_pending_count() -> int               # outstanding challenges, for the cap's test
    is_configured() -> bool                  # rp_id is non-empty
    authorize(user, passwd) -> bool          # always False, fail-closed
    cleanup() -> None                        # drops pending challenges

---

## 4. RP ID, origin, and the fleet — where the plan's story needs an amendment

The plan's premise: **RP ID = the parent domain (`oskar.co`), so one credential
registered once asserts on every device in the fleet.** That premise is correct
and this design keeps it. `authenticatorData.rpIdHash` must equal
`sha256(rp_id)`, so a credential created against `oskar.co` produces assertions
every `*.oskar.co` device can validate against the same `rp_id`. One
registration ceremony, N devices, no per-device enrolment. **[verified against
the WebAuthn assertion structure; the domain value itself is deployment
config]**

**But the naive reading of it is exploitable, and the plan does not say so.**
A shared RP ID makes an assertion *portable*. The only thing that stops a valid
assertion produced for device A from being replayed at device B is the challenge
— each device mints and remembers its own. If the origin check is also
suffix-based (`host == rp_id or host.endswith("." + rp_id)`), then anything that
can serve HTTPS under `*.oskar.co` — a compromised sibling KVM, a stale DNS
record, any other box on that domain — can:

1. fetch a live challenge from `kvm-pve1.oskar.co`,
2. serve a page at `evil.oskar.co` that calls `navigator.credentials.get` with it,
3. collect the assertion (the user sees a normal touch prompt), and
4. POST it to `kvm-pve1.oskar.co/api/auth/webauthn/assert`.

The signature is valid, the `rpIdHash` matches, the challenge matches, and the
`origin` — `https://evil.oskar.co` — passes a suffix check. Session minted.

**Amendment: the RP ID is fleet-wide, the accepted origin is not.** Default
behaviour when `origins` is empty is to accept exactly one origin,
`https://<the device's own FQDN>`, derived from `socket.getfqdn()` at
verification time; an explicit `origins` list overrides it for deployments
behind a name the device does not know it has. Suffix matching is never done.
This costs nothing — a browser will only *offer* the credential to a page whose
origin is a registrable-suffix match of the RP ID anyway — and it makes an
assertion non-transferable between fleet members. **[design decision]**

Consequence for §11: the config needs the device's expected origin, and
`socket.getfqdn()` on an RM1PE is not something this repository can predict.
`docs/lean.md` (step 15) should record what it actually returns on a unit.

**Discoverable credentials are mandatory.** `allowCredentials` is served as an
empty list, matching the plan's step-12 snippet. That is not incidental: the
challenge route is `auth_required=False`, so populating `allowCredentials` would
hand every credential ID on the device to an unauthenticated caller. An empty
list requires the credential to be discoverable, so registration must use
`residentKey: "required"` / `requireResidentKey: true`. The credential is then
located at assert time from the response's own `rawId`. The `userHandle` the
authenticator returns for a discoverable credential is ignored — `credential_id`
is already unique and is the store's index. **[design decision]**

---

## 5. Credential distribution — the enrolment ticket, not an on-device ceremony

There is **no registration endpoint** and no `navigator.credentials.create` on
the device. Registration happens once, off-device, against `oskar.co`; the
resulting credential set is written into the enrolment ticket and lands on the
device as `/etc/kvmd/user/webauthn.json`, the same way and at the same time as
the launcher pin (`docs/lean-plan.md` step 14 adds both to
`apply_to_glkvm.sh`).

Why: an on-device ceremony would need an authenticated session to start from,
which on a fresh device means the factory password — the exact credential
enrolment exists to retire. It would also need `navigator.credentials.create`
to run against `rp_id`, which means the browser must already be on a
`*.oskar.co` origin served by a device that is not yet enrolled. Distribution
sidesteps both.

Consequences, all of which the design accepts deliberately:

- The device never generates key material and never sees a private key.
- The store is **read-only on the device** (`chmod 444`, like the pin). The
  plugin never writes it.
- Rotation is a re-run of `apply_to_glkvm.sh`, not an API call.
- **`sign_count` cannot be persisted.** See §7.3.

---

## 6. The two endpoints

Described, not implemented — registering a route means editing `server.py`'s
`__apis` list, and the handler needs the token mint that lives in a locked file.
`api/webauthn.py` is step 11's job for the integrator; this section is its spec.

### `GET /auth/webauthn/challenge`

    @exposed_http("GET", "/auth/webauthn/challenge", auth_required=False, allow_usc=False)

`auth_required=False` because the point is to log in. `allow_usc=False` to match
`/auth/login` (`api/auth.py:191`). **Do not set `allowed_exe_paths`** —
`_check_exe_path` (`api/auth.py:144-171`) is *exclusive*: a non-matching caller
is `raise ForbiddenError()`, not fallen through, so any route carrying it is
unreachable from a browser. **[verified, `api/auth.py:165-169`]**

Response body is `plugin.make_challenge(purpose)`:

    {"publicKey": {"challenge": "<43-char base64url of 32 random bytes>",
                   "rpId": "oskar.co",
                   "allowCredentials": [],
                   "userVerification": "preferred",
                   "timeout": 60000}}

Server-side it records `challenge -> (purpose, expire_ts)` in a bounded dict.
Expiry uses `time.monotonic()` for the same reason `_Session` does (§11).

### `POST /auth/webauthn/assert`

    @exposed_http("POST", "/auth/webauthn/assert", auth_required=False, allow_usc=False)

Body (form or JSON — form, to match `/auth/login`'s `await req.post()` at
`api/auth.py:193`): `id`, `client_data_json`, `authenticator_data`, `signature`,
and optionally `expire`. Everything is base64url.

Handler: `plugin.verify_assertion(...)` → `(user, purpose)`; then
`auth_manager.login_verified(user, expire)` → `(token, failed_since_last)`; then

    return make_json_response({"token": token,
                               "failed_since_last_success": failed_since_last},
                              set_cookies={"auth_token": token})

mirroring `api/auth.py:217-220`. On any failure: `raise ForbiddenError()`, with
the reason logged and **not** returned to the client — a caller must not be able
to tell "unknown credential" from "bad signature" from "stale challenge".

Nginx needs no change: `location /api` rewrites `^/api/(.*)$` and sets
`auth_request off` (`configs/nginx/kvmd.ctx-server.conf:110-116`). **[verified]**

---

## 7. Verification, step by step

Implemented in `kvmd/plugins/auth/webauthn.py`. Order matters: cheap structural
checks before the subprocess, so an unauthenticated caller cannot make the
device fork `openssl` for free.

1. **Plugin configured.** `rp_id` non-empty and the store non-empty, else reject.
2. **Challenge.** Pop `challenge` from the pending dict — single use, popped
   before verification so a replay of the same challenge cannot race. Reject if
   absent or expired.
3. **`clientDataJSON`.** Parse as UTF-8 JSON. Require `type == "webauthn.get"`,
   `challenge` equal to the base64url of the expected bytes (compared with
   `hmac.compare_digest`), and `origin` in the accepted set (§4). `crossOrigin`,
   if present, must be false.
4. **Credential lookup.** `id` must resolve in the store. This is where the
   `user` field comes from (§8).
5. **`authenticatorData`.** At least 37 bytes. `[0:32]` must equal
   `sha256(rp_id)`. `flags = data[32]`: **UP (`0x01`) is required
   unconditionally**; UV (`0x04`) required if `require_uv`. `signCount =
   int.from_bytes(data[33:37], "big")`.
6. **Signature.** ES256 over `authenticatorData || sha256(clientDataJSON)`
   against the credential's public key. §1.1.
7. **`signCount`.** §7.3.
8. Return `(user, purpose)`.

### 7.1 COSE key handling

The store holds `public_key_cose`: base64url of the COSE_Key the browser
returned at registration. A minimal CBOR decoder — unsigned int, negative int,
byte string, text string, array, map, and nothing else — is enough, and is
included rather than adding a `cbor2` dependency the device does not have and
the test image would not install. It is ~50 lines, refuses trailing bytes,
refuses indefinite-length items, and caps nesting depth.

Required COSE fields for ES256: `1` (kty) == `2` (EC2), `3` (alg) == `-7`,
`-1` (crv) == `1` (P-256), `-2` (x) 32 bytes, `-3` (y) 32 bytes. Anything else
is rejected. That is the whole of "**ES256 only (`alg: -7`)**": there is no
algorithm negotiation, no RS256 fallback, no Ed25519. A credential whose COSE
key says anything else never loads. **[design decision, matches the plan]**

### 7.2 Why not trust the browser's algorithm choice

Registration is off-device (§5), so the device never sees a
`PublicKeyCredentialCreationOptions` and cannot constrain `pubKeyCredParams`.
Enforcement is therefore purely on the *stored* key: the store loader rejects a
non-ES256 COSE key at load time, so an enrolment ticket carrying an RS256
credential fails loudly at startup rather than quietly at login.

### 7.3 `signCount` and the read-only store — an accepted gap

WebAuthn's clone detection wants the RP to persist a monotonically increasing
`signCount` per credential. This store is `chmod 444` and delivered by ticket
(§5), so the plugin **cannot** persist it.

What is implemented: the file's `sign_count` seeds an in-memory high-water mark
per credential; an assertion whose counter is `<=` the mark is rejected; a
successful assertion raises the mark. Authenticators that do not implement a
counter report `0` always, so `0` observed against a `0` mark is accepted
(this is the standard carve-out, not a shortcut).

What is therefore **not** implemented: clone detection across a kvmd restart,
because the mark resets to the ticket's value. **[gap, accepted]** The
mitigations that make it acceptable are that the device is on a management VLAN,
that the credential is a hardware key whose private half never leaves it, and
that a cloned authenticator is a physical-possession attack this project does
not claim to defend against. If it ever needs closing, the fix is a small
writable side-file (`/etc/kvmd/user/webauthn.counters`) separate from the
ticket-owned store — deliberately not done now, because it introduces a
device-writable file into an otherwise immutable credential path.

---

## 8. `webauthn.json` — and the username gap the plan flagged

The plan's step 11 ends by noting a real hole:

> a `_Session` asserts a non-empty UNIX-style user (`auth.py:52-55`) matching
> `valid_user ^[a-z_][a-z0-9_-]*$`, so each stored credential must carry a
> username satisfying that regex — the design's credential tuple
> `{credential_id, public_key_cose, sign_count, aaguid, label}` has no such
> field.

Re-derived: the assertions are at **`auth.py:55-59`** (`__post_init__`, `assert
self.user == self.user.strip()`, `assert self.user`) and the regex is
`kvmd/validators/auth.py:37`. The plan's `52-55` is stale by three lines; the
finding is exactly right. **[verified]**

**Resolution: `user` is a required field on every credential entry, validated
with `valid_user` at load time.** A credential without one, or with one that
fails the regex, is refused when the store loads — not at login. This extends
the plan's tuple by one field, deliberately.

Format (`configs/kvmd/webauthn.json` ships as a documented empty example):

    {
      "version": 1,
      "credentials": [
        {
          "credential_id":   "<base64url>",
          "public_key_cose": "<base64url of the COSE_Key>",
          "user":            "admin",
          "sign_count":      0,
          "aaguid":          "<base64url, 16 bytes, may be all-zero>",
          "label":           "Oskar YubiKey 5C — blue",
          "roles":           ["admin"]
        }
      ]
    }

Rules the loader enforces:

- `version` must be `1`.
- `credentials` must be a list; an **empty list is valid** (an unenrolled
  device) and so is a missing file. Neither is an error; both mean "WebAuthn
  offers nothing", which is why the break-glass password must survive (§10).
- `credential_id` and `public_key_cose` are required, base64url, non-empty;
  `credential_id` must be unique across the file.
- `public_key_cose` must decode to an ES256 COSE key (§7.1).
- `user` is required and must satisfy `valid_user`.
- `sign_count` is an int `>= 0`; absent means `0`.
- `aaguid`, `label`, `roles` are optional metadata, surfaced by
  `get_credentials_info()` and **never** used in an access decision. `roles`
  in particular has no consumer anywhere in kvmd (§2).
- The file is re-read when its `st_mtime_ns`/`st_size` change, so a ticket
  re-apply takes effect without a kvmd restart. A malformed file after a
  successful load is a hard error that keeps the previous good set, so a
  botched ticket cannot silently disable the second factor.

---

## 9. Per-operation user presence

The UP flag is required on **every** assertion (§7 step 5), which makes each
assertion a proof that a human touched the key at that moment. The design uses
that for more than login.

`make_challenge(purpose)` binds an opaque purpose string into the pending-challenge
record, and `verify_assertion` returns it. `purpose == "login"` is the session
mint. Anything else is a **touch-to-confirm** for a single operation: the client
requests a challenge with `purpose = "atx:power_off"`, does a ceremony, and posts
the assertion; the server verifies it, confirms the purpose is the one the route
expects, and only then performs the action. No session grant is issued and
nothing is cached — the presence proof is consumed by one operation.

The candidate operations, in descending order of "an accidental click here ruins
someone's afternoon": `POST /atx/power` with `action=off_hard`, `POST /msd/*`
writes, the firmware upgrade routes, and any password change.

Route-level enforcement is **not** in scope here — it means editing route
decorators across `api/atx.py`, `api/msd.py` and `api/upgrade.py`. The plugin
ships the mechanism (purpose binding, single-use challenges, mandatory UP) and
`get_challenge_purpose`-style plumbing; wiring it to routes is a later step and
belongs in the plan after 11/12. **[scope decision]**

---

## 10. Break-glass password

The password stays. It is held in OpenBao and is **not** on the device in any
recoverable form — only its `{SSHA512}` hash in
`/etc/kvmd/user/htpasswd`, per the hashing fix on the status branch.

Why it cannot be removed, concretely:

- A device before enrolment has a factory password and an empty (or absent)
  `webauthn.json`. Deleting the password path locks the operator out of the
  device they are trying to enrol. `docs/lean-plan.md` step 12 says the same
  and instructs keeping `web/login/index.pug:32-37`.
- A lost or broken hardware key is a total lockout otherwise, and the recovery
  story for an IP-KVM is "drive to the datacentre".
- The plugin's `authorize()` returning `False` (§2) means the *password* path
  keeps going through `htpasswd` as it does today; WebAuthn is additive.

So: WebAuthn is the routine path; the OpenBao password is the break-glass path;
`nginx limit_req` (still outstanding per `docs/audit.md` section 3d) is what
keeps the break-glass path from being a guessing gallery. Adding WebAuthn does
**not** close the audit's interim-posture item — that is `limit_req`, and it is
still open.

---

## 11. Integration requirements — the checklist for the locked files

Nothing in this list is done. Each entry is a change someone else makes after a
rebase, in the files this workstream is forbidden to touch.

### 11.1 `kvmd/apps/kvmd/auth.py` — MANDATORY, one new method

The plan is right that there is no public way to mint a session token without a
password, and the reasons are all still true at `930142e`:

- `login()` (`auth.py:156`) calls `self.authorize(user, passwd)` at
  **`auth.py:162`** before anything else. There is no branch that skips it.
- Every primitive is name-mangled and thus unreachable from another module
  without a `_AuthManager__` hack: `__make_new_token` (**`auth.py:189-194`**),
  `__make_expire_ts` (**`auth.py:196-212`**), `__sessions` (assigned
  **`auth.py:120`**), `__consume_failed_since_last_success`
  (**`auth.py:183-187`**), `__get_now_ts` (**`auth.py:217-218`**), and the
  `_Session` dataclass itself (**`auth.py:47-59`**), which is module-private.

(The plan's citations — `login()` at `:230`, `authorize()` at `:251`,
`__make_new_token` at `:286`, `__make_expire_ts` at `:293`, `__sessions` at
`:159`, `__consume_failed_since_last_success` at `:280`, `_Session` at `:47-55`
— are all stale: they predate the lockout deletion and the WS-session port.
`auth.py` is **384 lines**, not the 361 the plan's measurement table reports.
The conclusion is unaffected.)

Required addition, **inside the `AuthManager` class body** (name mangling is the
whole reason it cannot go anywhere else):

    async def login_verified(self, user: str, expire: int) -> tuple[str, int]:
        assert user == user.strip()
        assert user
        assert expire >= 0
        assert self.__enabled
        token = self.__make_new_token()
        session = _Session(
            user=user,
            expire_req=expire,
            expire_ts=self.__make_expire_ts(expire),
            ws_started=0,
        )
        self.__sessions[token] = session
        failed_since_last = self.__consume_failed_since_last_success()
        get_logger(0).info("Logged in user %r via verified assertion; expire=%s, "
                           "sessions_now=%d, failed_since_last_success=%d",
                           session.user,
                           self.__format_expire_ts(session.expire_ts),
                           self.__get_sessions_number(session.user),
                           failed_since_last)
        return (token, failed_since_last)

Five properties that are non-negotiable, each with the failure mode if missed:

1. **It must not call `authorize()`.** That is the entire point. The caller has
   already proven possession of a hardware key; there is no password to check.
2. **The token must come from `__make_new_token()`.** That is
   `secrets.token_hex(32)` (`auth.py:191`) → 64 lowercase hex, which is what
   `valid_auth_token`'s `^[0-9a-f]{64}$` (`kvmd/validators/auth.py:69`) demands.
   A `token_urlsafe`, a UUID, or an uppercase hex token produces a session that
   mints fine and then fails `_check_token` (`api/auth.py:80-89`) on the very
   next request — a bug that looks like "login works but nothing else does".
   `__make_new_token` also guarantees uniqueness against `__sessions`.
3. **`expire_ts` must come from `__make_expire_ts()`.** `__get_now_ts()` is
   `int(time.monotonic())` (`auth.py:217-218`), an uptime-relative clock, and
   `check()` compares against it at `auth.py:259`. A mint that computes
   `int(time.time()) + expire` produces a number ~1.7 billion larger than any
   monotonic value, so the session **never expires**; a mint that stores a bare
   `expire` produces one smaller than `monotonic()` on any box up for more than
   `expire` seconds, so the session **expires on the next request**. Both are
   silent. `__make_expire_ts` also applies the global `expire` cap
   (`auth.py:200-209`), which a hand-rolled timestamp would bypass.
4. **`ws_started=0`.** The field is new (the WS-session port) and
   `__renew_ws_session` (`auth.py:274-289`) arithmetic depends on it starting at
   zero. `_Session` is frozen with four required fields; omitting it is a
   `TypeError` at mint time.
5. **It must call `__consume_failed_since_last_success()`.** That counter
   (`auth.py:122`, `:183-187`) is the fork's own product feature — the UI shows
   failed attempts since the last success. A WebAuthn login that does not
   consume it means the count keeps climbing across successful logins and the
   UI's warning becomes permanent noise.

`async def` even though the body awaits nothing, so the call site matches
`login()` and does not have to change if this ever grows an await.

Suggested test, which is step 11's "done when": assert `login_verified()`
returns a 64-lowercase-hex token, that `re.fullmatch(r'[0-9a-f]{64}', token)`
holds, that `check(token)` returns the user, and — the one that catches the
`time.time()` bug — that with `expire=1` the session is still valid immediately
and gone after monotonic advances past it.

### 11.2 `kvmd/apps/kvmd/api/auth.py` — no edit required

Deliberately. `WebAuthnApi` is a separate class in a separate file, so nothing
in `api/auth.py` changes. Two things the integrator should know:

- `_COOKIE_AUTH_TOKEN = "auth_token"` is at **`api/auth.py:55`** and is
  module-private. **Do not import it across modules.** Define the literal
  `"auth_token"` again in `api/webauthn.py` with a comment pointing here; a
  duplicated four-word string is cheaper than an underscore-import that pylint
  flags and a future refactor breaks silently.
- `check_request_auth` (`api/auth.py:173-181`) needs no new checker. The
  WebAuthn assert route mints a normal cookie/`Token` session, so
  `_check_token` / `_check_header_token` already resolve it.

### 11.3 `kvmd/htserver.py` — no edit required

`exposed_http` (`htserver.py:112-128`) and
`make_json_response(..., set_cookies=...)` (`htserver.py:181-199`) already do
everything the two routes need.

One observation for whoever *is* allowed to touch it: `set_cookies` sets
`httponly=True, samesite="Strict"` but **not** `secure=True`
(`htserver.py:198`). On a device reached over HTTPS the session cookie is
therefore still sent over a plaintext downgrade. Out of scope here; worth an
entry in `docs/audit.md`.

### 11.4 `kvmd/apps/kvmd/server.py` — one import, one list entry

    from .api.webauthn import WebAuthnApi          # near server.py:80 (AuthApi)
    ...
    WebAuthnApi(auth_manager, webauthn_service),   # in __apis, next to AuthApi

`__apis` is at **`server.py:202-227`** and `AuthApi(auth_manager)` is at
**`server.py:204`** — the plan's `server.py:225` is stale. `_add_exposed(*self.__apis)`
at `server.py:587` picks the routes up with no further registration.

### 11.5 `kvmd/apps/__init__.py` + `kvmd/apps/kvmd/__init__.py` — a new config section

**This is a requirement the plan does not mention, and getting it wrong forces
an unnecessary edit to a locked file.**

The auth config schema has exactly two plugin slots, `internal` and `external`
(`kvmd/apps/__init__.py:441-450`), both wired straight into
`AuthManager(int_type=..., int_kwargs=..., ext_type=..., ext_kwargs=...)`
(`kvmd/apps/kvmd/__init__.py:112-117`), and both are password services.
Making `AuthManager` own the WebAuthn plugin would mean a third constructor
parameter and a new accessor — i.e. a second, larger edit to the locked
`auth.py`.

**Do not do that.** Put the plugin outside `AuthManager`:

- new top-level section in the `kvmd` scheme, `webauthn: {type: Option("")}`
  plus dynamic plugin content, loaded the way `load_auth` does it at
  `kvmd/apps/__init__.py:296-299`;
- construct it in `kvmd/apps/kvmd/__init__.py` alongside `auth_manager=...`
  (`:104`) and hand it to `WebAuthnApi`;
- `AuthManager` gains exactly one method (§11.1) and knows nothing about
  WebAuthn.

`type: ""` (empty, i.e. disabled) must be the default so that an existing
`main.yaml` keeps working untouched.

### 11.6 The login flow — `web/` (step 12, someone else)

Not touched here. The plan's step 12 already lists the three gotchas; two of
them are properties of this design and are restated so they are not lost:

- The options object must be written with `quote-props: always` and double
  quotes (`testenv/linters/eslintrc.js:34-41`), so copy-pasted WebAuthn
  snippets fail eslint.
- `tools.httpRequest` is XHR with a 15 s default timeout (`tools.js:51-79`)
  while a ceremony waits ~60 s for a tap. The challenge is single-use and
  popped on first use, so an XHR that aborts mid-ceremony does not merely fail
  — it burns the challenge, and the retry needs a **fresh** `GET
  /auth/webauthn/challenge`. Pass an explicit timeout and re-fetch on retry.
- There are no base64url helpers in `web/share/js` (`tools.js:115-117`
  `makeTextId` is not one). All four wire fields are base64url; write real
  `ArrayBuffer` ⇄ base64url helpers, and remember `rawId` must be sent, not
  `id`.
- Keep the username and password rows (`web/login/index.pug:32-37`) — §10.

### 11.7 `apply_to_glkvm.sh` (step 14)

Add `webauthn.json` to the same block that writes the launcher pin: `scp` to
`/etc/kvmd/user/webauthn.json`, `chmod 444`, `sync`. It lives outside
`REMOTE_DIR`, so the `rm -R` at line 34 does not clear it — which also means a
re-run does **not** refresh it unless the `scp` is explicit.

**Do not scp `configs/kvmd/webauthn.json`.** That file is the empty reference
example (§13.3). The apply script must copy the *ticket's* store; copying the
in-repo sample over an enrolled device replaces its credentials with an empty
set, which is a silent lockout. If a guard is wanted, refuse to overwrite a
`/etc/kvmd/user/webauthn.json` that has a non-empty `credentials` array with
one that does not.

### 11.8 Linter bookkeeping

- `vulture`: `testenv/tox.ini:37` ignores `@pytest.fixture` but not
  `@pytest_asyncio.fixture`. Any async fixture name must be appended to
  `testenv/linters/vulture-wl.py`. The tests shipped here use plain
  `@pytest.mark.asyncio` test functions and no async fixtures, so nothing is
  needed today.
- `pylint`: `max-args = 10` (`testenv/linters/pylint.ini:14`) and attribute/
  variable names capped at 30 characters (`:70, 73`).
- `mypy`: `disallow_untyped_defs` (`testenv/linters/mypy.ini`), so every test
  needs `-> None`. `python_version = 3.11`.

---

## 12. Corrections to `docs/lean-plan.md` and `docs/audit.md`

Found while re-deriving. Listed so they get fixed rather than re-discovered.

1. **Every `auth.py` line number in step 11 is stale.** The file is 384 lines,
   not 361 (the measurement table's figure) and not the ~800 the step-11 prose
   was written against. Corrected numbers in §11.1. The step-11 *reasoning* is
   correct in every particular.
2. **`server.py:225` for `AuthApi` is stale** — it is `server.py:204`, inside
   the `__apis` list at `202-227`.
3. **`auth.py:52-55` for the `_Session` username assertions is stale** — the
   `__post_init__` assertions are at `auth.py:55-59`, the dataclass at `47-59`.
4. **The plan does not mention that WebAuthn needs a config slot at all**, and
   the obvious place (`auth.internal`/`auth.external`) is the wrong one because
   both feed `AuthManager`'s password path. §11.5. Missing this leads straight
   to a second edit of the locked `auth.py`.
5. **The plan's fleet story needs the origin amendment in §4.** "One credential
   asserts on every device" is true and worth keeping; "so accept any origin
   under the parent domain" — which is how a build agent will read it — creates
   a cross-device assertion relay. The RP ID is fleet-wide; the accepted origin
   must be per-device.
6. **`kvmd/validators/auth.py:72-83` is dead code.** `valid_rate_limit_max_attempts`,
   `valid_rate_limit_time_window` and `valid_rate_limit_lockout_duration`
   survived the lockout deletion with zero remaining callers
   (`grep -rn valid_rate_limit --include=*.py .` → three definition lines and
   nothing else). Not this workstream's file to change, but step 10 should have
   taken them and did not.
7. **The plan's `openssl`-vs-`cryptography` conclusion is right for a reason it
   does not give.** It argues from the device; the stronger argument is that the
   test interpreter and the test image have no `cryptography`, so that branch
   cannot be covered by CI regardless of what the device ships. §1.
8. **`docs/audit.md` section 3d should not be read as closed by this work.**
   WebAuthn removes the *routine* dependence on the password; it does not add
   rate limiting. `nginx limit_req` is still the open item.

---

## 13. What actually shipped with this document

Net-new files only. Nothing in the three locked files or in `web/` was touched.

### 13.1 `kvmd/plugins/auth/webauthn.py`

Follows the fork's plugin contract (§3): explicit keyword parameters on
`__init__`, `get_plugin_options()` returning `yamlconf.Option`s, constructed as
`get_auth_service_class("webauthn")(**kwargs)`. Contents, in order:

- `b64u_decode` / `b64u_encode` — base64url with a `^[A-Za-z0-9_-]*$` gate
  before decoding, because `urlsafe_b64decode` silently tolerates standard
  base64 and garbage alike. These are the first base64url helpers in the tree
  (§1 recorded that none existed).
- `cbor_loads` — a deliberately partial CBOR reader: unsigned int, negative
  int, byte string, text string, array, map, and nothing else. Indefinite
  lengths, tags, floats and simple values are **refused**, not skipped; trailing
  bytes are an error; nesting is capped at 4; duplicate and unhashable map keys
  are rejected. Each of those refusals has a test. A permissive decoder in front
  of a public key is where key confusion lives.
- `cose_es256_to_spki` / `spki_to_pem` — §7.1, with `_P256_SPKI_PREFIX` as a
  measured constant rather than a copied one.
- `verify_es256_cryptography` → `bool | None`, `verify_es256_openssl` → `bool`,
  and `verify_es256` dispatching between them. §1.
- `Credential` (frozen dataclass) and `CredentialStore` — §8. Read-only,
  re-reads on `(st_mtime_ns, st_size)` change, keeps the last good set when a
  file goes bad, and never lowers a counter mark it has already seen even if a
  re-applied ticket says a smaller number.
- `get_default_origins()` — §4, monkeypatchable so the fleet-origin rule is
  testable without a real FQDN.
- `Plugin` — the surface listed in §3.

### 13.2 `testenv/tests/plugins/auth/`

- `softauthn.py` — a software authenticator built entirely on `openssl`
  subprocesses: real P-256 keys, real ES256 signatures, a tiny CBOR *encoder*
  for COSE keys, and builders for `authenticatorData` and `clientDataJSON`.
  No network, no `cryptography`, and no key generation on any device. It is
  test-only and nothing in `kvmd/` may import it.
- `test_webauthn.py` — 84 tests. `_make_plugin()` goes through
  `yamlconf.make_config` and `_unpack()`, so the option contract is exercised
  rather than bypassed, and one test asserts `cose_es256_to_spki` reproduces the
  DER that `openssl ec -pubout -outform DER` emitted for the same key, so the
  measured prefix constant cannot rot silently.

**Mutation-checked**, because 84 tests passing on the first run is not evidence
that any of them bite. Four one-line mutations were applied and reverted:

| mutation | tests that failed |
|---|---|
| skip the UP-flag check | 2 |
| accept any signature | 1 |
| read the pending challenge instead of popping it | 1 (`challenge_is_single_use`) |
| skip the origin check | 3 |

### 13.3 `configs/kvmd/webauthn.json`

The empty reference example. It is **not** auto-installed: `PKGBUILD:173`
copies `configs/*` into `/usr/share/kvmd/configs.default`, and the Makefile's
container targets copy only `*.yaml`, `*passwd` and `*.secret` into `/etc/kvmd`
(`Makefile:86-88, 128-130, 155-157, 178-180`) — no `.json`. Deliberate: an
auto-installed store would let an upgrade or an apply-script re-run replace an
enrolled device's credentials with an empty set. See §11.7.

### 13.4 Numbers

| gate | baseline | after |
|---|---:|---:|
| `pytest testenv/tests` | 681 passed, 0 failed | **765 passed, 0 failed** |
| `flake8` (`kvmd testenv/tests`) | 468 | **468** |

`mypy` reports **0 errors in the three new files**. It does report two
pre-existing errors in `kvmd/tools.py:131` and `:166` (`run_command` and
`run_shell` annotate `-> tuple[int, str, str]` while
`Process.returncode` is `int | None`); those predate this work and are in a file
this workstream did not touch. `pylint` and `vulture` are not installed in this
container and could not be run — the constraints in §11.8 were satisfied by
inspection, not by a run, and `make tox` should be the gate before this merges.
