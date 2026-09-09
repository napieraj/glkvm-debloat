# GLKVM Fork Audit

**Everything broken here was added here.**

GL.iNet's KVM firmware carries 31% more Python than the PiKVM project it forked.
Every security defect found in it lives in code PiKVM never wrote.

| | |
|---|---|
| **Fork** | `gl-inet/glkvm` @ `3e8dd23` (fork v1.10.0, kvmd 4.16) |
| **Upstream** | `pikvm/kvmd` @ `15bccd5` |
| **Scope** | Static analysis of two source trees. No physical device. |

**Key figures**

| Measure | Value |
|---|---|
| API layer growth | **6.5×** — 11,436 lines of route code against upstream's 1,769 |
| New tests for it | **0** — roughly 9,700 added API lines ship with no test of their own |
| Lint, identical config | **742** violations of the fork's own checked-in flake8 rules (upstream: none) |
| Findings, all fork-only | **15** — three reach root, one of them without credentials |

---

## 1. Provenance — the dividing line is clean

Of the 31 API modules in the fork, 21 do not exist upstream at all. Every module
implicated in a security finding is one of those 21.

This matters for where the problems belong. It is tempting to read a vendor fork's
defects as inherited sloppiness from the project it started from. The opposite holds
here. The shared modules are the ones that handle video, input, storage, power and
GPIO, and they are untouched by every finding below. The added modules are the ones
that reach the internet, manage the device's own identity, and grant access.

**Only in the GL.iNet fork (21)**

`tailscale` `zerotier` `netbird` `netbird_daemon` `cloudflare` `astrowarp` `turn`
`repeater` `ap` `modem` `custom_screen` `twofa` `system` `upgrade` `init` `wol`
`redfish` `serial` `recorder` `rndis` `fingerbot`

**Shared with upstream (10)**

`auth` `hid` `streamer` `msd` `atx` `log` `info` `export` `switch` `ugpio`

Presence of `kvmd/apps/kvmd/api/*.py` in each tree. The four modules behind the two
critical findings — `system`, `upgrade`, `init` and the fork's rewritten auth layer —
are all fork-only.

---

## 2. Scale — growth concentrated in the route layer

The fork is a third larger overall, which on its own would be unremarkable for a
vendor adding hardware support. The distribution is what stands out. Nearly all of
the growth sits in the HTTP surface and in authentication, the two places where a
mistake is reachable by anyone who can open a socket.

| Measure | Fork | Upstream | |
|---|---:|---:|---|
| Python lines, whole `kvmd/` | 45,277 | 34,447 | +31% |
| Python lines, API layer | 11,436 | 1,769 | **6.5×** |
| Python lines, `auth.py` | 764 | 322 | 2.4× |
| Python lines, `api/auth.py` | 429 | 150 | 2.9× |
| Test files | 26 | 29 | fewer |
| Test lines | 2,467 | 3,030 | fewer |
| flake8 findings, same config | 742 | 0 | — |
| Unauthenticated routes | 10 | 2 | 5× |
| ...of those, remotely reachable | 7 | 2 | 3.5× |
| `GET` routes | 110 | 30 | 3.7× |
| Reads from the query string | 167 | 80 | 2.1× |
| `except Exception` | 503 | 218 | 2.3× |
| Bare `except:` | 14 | 2 | 7× |
| Commented-out logic | 26 | 8 | 3.3× |

Counts over all `*.py` under each path. The flake8 run uses each repository's own
`testenv/linters/flake8.ini`, and the two files are byte-identical — the fork kept
upstream's standard and stopped meeting it. The largest categories are 370
whitespace-on-blank-line, 75 missing-space-after-comma and 71 unused imports.

---

## 3. Security — fifteen findings, three of them reach root

Severity here is consequence on a device whose stated job is out-of-band access to
other machines. A defect that yields a root shell on the KVM yields the console of
everything the KVM is attached to.

- **verified** — read line by line in this audit
- **reported** — from the maintainer's own pass, not independently confirmed
- **fork-only** — no counterpart upstream

### CRITICAL — A route writes root's `authorized_keys` from the request body

`POST /system/ssh_key` reads the raw body and writes it to
`/root/.ssh/authorized_keys` with no validation, creating the directory and setting
modes to match. The paired `GET` returns the current file. Any authenticated caller
obtains permanent root SSH access, bypassing certificate authentication, any CA
policy, and any intent to keep key material off the device.

*fork-only · verified · `api/system.py:1651, 1673–1690`*

### CRITICAL — A GET request factory-resets the device

`GET /upgrade/reset_default` spawns `/usr/sbin/reset_default.sh`. A
state-destroying operation behind a safe verb, and a factory reset discards
whatever enrolled identity the device holds, so one request un-provisions the
machine.

Cross-site triggering is mitigated: the session cookie is set `httponly` and
`SameSite=Strict` (`htserver.py:198`), so a browser will not attach it to a
request from another site. That leaves same-origin paths (a prefetch or an XSS
on the device's own UI) and any non-browser client holding credentials. The
chain that matters is with the finding below: a reset returns the device to the
uninitialised state in which `/init/init` will set the admin password for
whoever asks first.

**The chain is the point.** A reset clears `/etc/kvmd/user/init_state.json`,
which returns the device to the uninitialised state where the unauthenticated
route below sets root's SSH password. So an authenticated web session converts
into permanent root, and it survives the reset. Worse, once reset the device is
claimable by *anyone* who reaches it, so an owner resetting a compromised device
to recover it must win a race against the attacker to re-initialise it first.
Factory reset does not reliably recover this device.

*fork-only · verified · `api/upgrade.py:781`*

### CRITICAL — An uninitialised device hands root to whoever arrives first

`GET /init/init` is unauthenticated, ungated, and not rate-limited. While the
device reports itself uninitialised it accepts a password and calls
`InitManager.init()`, which does two things: sets the web admin password via
htpasswd, **and rewrites root's entry in `/etc/shadow`** with a SHA-512 crypt of
the same value (`init.py:95–138`). So this is not "an attacker becomes web
admin". An unauthenticated attacker who reaches the device first sets root's SSH
password and gets a root shell, and therefore the console of every machine the
KVM is attached to.

The password arrives as a query parameter, so the credential it establishes is
also written to the access log and to every proxy log in the path.

Two things widen the window beyond "a brand-new device". `GET
/upgrade/reset_default` above returns a device to this state, as does the
physical reset button. And the uninitialised flag is not a property of the
system, it is `/etc/kvmd/user/init_state.json`: `_load_state()` sets
`inited = False` when the file is absent, and its `except Exception` leaves the
constructor's `False` in place when the file is unreadable or malformed
(`init.py:51–77`). The flag fails open.

*fork-only · verified · `api/init.py:62–67`, `init.py:51–77, 95–163`*

### HIGH — A route hands out the device's TLS private key

`GET /system/ssl_cert` reads both the certificate and the private key from disk and
returns them together in the JSON body, under `ssl_cert` and `ssl_key`. Any
authenticated caller receives the key that identifies the device's API, which is
enough to impersonate the KVM to anything that trusts its certificate.

Taken with the `authorized_keys` route above, an authenticated web session yields
persistent root SSH *and* the device's TLS identity. Neither requires an exploit;
both are documented routes behaving exactly as written.

*fork-only · verified · `api/system.py:2074`, response body at `:2105–2110`*

### HIGH — Client identity is whatever the client says it is

`_get_client_ip(self, req_headers: dict)` takes only a headers dictionary, so it
cannot consult the socket even in principle. It returns `X-Real-IP`, then the first
entry of `X-Forwarded-For`, then the literal string `'unknown'`. Every lockout
decision, every rate-limit decision and every "local network only" check is keyed on
that value.

The `'unknown'` fallback is its own problem: with no proxy in front, every client
shares one bucket and they lock each other out.

*fork-only · verified · `auth.py:594–607`*

### HIGH — The rate limiter runs for one percent of clients

Both call sites guard on `hash(client_ip) % 100 == 0`. Python randomises string
hashing per process, so which one percent is throttled changes on every restart and
is not reproducible. Combined with the finding above, where the key is an
attacker-chosen string, an attacker simply varies the header until they land in the
unthrottled remainder and can tell by observation when they have.

Deleting the sampling is necessary but not sufficient. It only becomes a limiter
once the identity is real.

*fork-only · verified · `auth.py:248, 413`*

### HIGH — Lockouts can be inspected and cleared for any address

`/auth/rate_limit_status` accepts an arbitrary `client_ip` and reports on it;
`/auth/unlock_client` accepts an arbitrary `client_ip` and clears its lockout.
Together with header-controlled identity, that is a complete lock, inspect and
unlock primitive against any identity an attacker cares to name.

*fork-only · verified · `api/auth.py:350, 366–377`*

### MEDIUM — Passwords travel in the query string, with the guard commented out

`/init/change_password` reads `user`, `old_password` and `new_password` from the
query string, so both passwords reach the logs. Directly above them, the
initialisation guard sits commented out rather than removed.

*fork-only · verified · `api/init.py:92–101`*

### MEDIUM — Session tokens are accepted in URLs

Three sites read `auth_token` from the query string. Tokens in a URL are recorded by
access logs and forwarded in the `Referer` header of anything the page loads.

*verified · `api/auth.py:123, 245` · `server.py:556`*

### MEDIUM — Logging out does not invalidate the user's other sessions

`logout(token)` deletes exactly the one token it is handed. Every other session
belonging to the same user stays valid, so a user who logs out — or an operator who
logs out a session believed to be compromised — has revoked nothing but the token in
their own browser.

This is a deliberate fork change, not an oversight. Upstream's loop, which walked
`self.__sessions` and dropped every session whose `user` matched, is still present
directly above the replacement, commented out, under a developer comment reading
`去掉删除所有此用户token的代码, 实在太蠢` — "removed the code that deletes all of this
user's tokens, it's really too stupid". The `del self.__sessions[token]` that replaced
it is a single-token delete.

The consequence is that no route on the device can terminate a session it does not
hold the token for. There is no "log out everywhere", and the token an attacker minted
by any of the paths above survives the victim logging out, changing nothing but their
own cookie. Note that a password change does not close sessions either: nothing in
`change_password` touches `__sessions`.

*fork-only · verified · `auth.py:333–345`, the commented-out loop at `:337–341`*

### MEDIUM — A web terminal ships enabled

The device serves a browser terminal backed by `ttyd`, wired through the UI and
restarted by the fork's own client-management route. A shell over HTTP defeats any
policy that SSH access be certificate-only.

*fork-only · verified · `api/system.py:321` · `web/kvm/window-webterm.pug`*

### MEDIUM — Raw video bypasses the API's own access check

The `/streamer` location is proxied under the server-wide authentication check only,
so any logged-in session can pull the video stream regardless of what the snapshot
API enforces above it.

*reported · nginx configuration*

### MEDIUM — Storage device and path arrive unvalidated at the route

The partition-switch device and the format path reach path resolution and a format
operation without being checked against the storage backend's own device list. A
guard exists two layers down, which is both too late and easy to lose in a refactor.

*reported · mass storage routes*

### MEDIUM — Wake-on-LAN input is stored and logged unvalidated

MAC address, IP and device name are persisted and written to logs without
validation, despite a MAC validator already existing in the fork's shared helpers.

*fork-only · reported · `api/wol.py`*

### MEDIUM — The daemon fails to start if a hardware file is missing

`get_model_name()` catches a missing model file and calls `get_logger` to report the
fallback, but the module never imports it. The recovery path raises `NameError`
instead of returning the default, and because a route module calls it at import
time, the whole daemon fails to load. A missing file turns into a dead KVM.

*fork-only · verified · `kvmd/utils.py:34–40`, call at `:39`*

---

## 4. Comparison — upstream already solved three of these

The most useful result of the comparison is not the count. It is that the correct
implementations sit in the same files the fork edited.

**Identify the peer from the socket.** Upstream resolves the connecting process
through the transport socket and `SO_PEERCRED` in `htserver.py`. That is exactly the
mechanism the fork's header-based identity should have used, and it also answers the
open question about executable-path authorisation. The fix is to read the file the
fork already forked.

**Treat proxy headers as logging, not identity.** Upstream references `X-Real-IP`
only in access-log format strings, and sets it itself in its own nginx configuration
from `$remote_addr`. It never makes an authorisation decision from a header. The fork
took a logging convenience and promoted it to an identity.

**Upstream has no lockout machinery at all.** There is no rate limiting, no lockout
and no unlock in upstream's authentication. The entire subsystem is the fork's
invention, and it is both bypassable and a gift to an attacker. Removing it outright
is therefore a legitimate option that moves the file back toward upstream, rather
than repairing a feature that never existed to begin with.

---

## 5. Recommendations

**Close the two bypasses first.** Delete both `ssh_key` handlers and the
factory-reset route. Neither has a legitimate caller on a device where SSH access is
certificate-based and provisioning is automated. These are deletions, not redesigns.

**Rebuild identity on the socket, then re-decide the feature.** Change the signature
so that passing a headers dictionary is impossible, take the peer from the transport,
and honour proxy headers only from loopback. Once identity is real, decide whether the
lockout subsystem is wanted at all; upstream ships without it.

**Stop accepting credentials in URLs.** Passwords and session tokens in query strings
are a systemic pattern here, not three isolated slips, and every one of them ends up
in a log. Move them to request bodies and headers.

**Give the added surface tests.** Roughly 9,700 lines of route code carry no test. The
fork kept upstream's test harness and its lint configuration, so the scaffolding is
already present and unused. Restoring the lint gate alone would clear 742 findings and
catch the 71 unused imports that make dead code hard to spot.

**Report these to GL.iNet, not to PiKVM.** Every finding is fork-introduced. Nothing
here reflects on upstream, and none of it belongs in an upstream-facing issue.

---

## Method and confidence

**Method.** Static analysis of two source trees, with no access to a physical device.
Line counts cover all `*.py` under each path. The lint comparison runs flake8 7.3.0
against each repository's own configuration file, which are byte-identical. Nothing
here was executed on hardware, and no runtime behaviour was observed.

**Confidence.** Findings marked verified were read line by line against the source
during this audit. Findings marked reported come from the maintainer's own review and
are recorded as stated rather than independently confirmed; they are ranked on
described consequence.

**One finding was retracted.** An earlier draft carried "executable-path
authorisation runs before credentials" as a medium. Reading the enforcement
settles it in the vendor's favour and it is withdrawn: when a route declares
`allowed_exe_paths`, a non-matching caller is refused outright rather than
falling through to the ordinary auth checks, and the peer is resolved with
`SO_PEERCRED`, which cannot succeed over TCP. Those routes are therefore
local-Unix-socket-only and return 403 to any HTTP request, which is why the
remotely reachable unauthenticated surface is seven routes rather than ten. Any
residual exec-after-connect race applies only to local callers.

**Two caveats worth stating.** An earlier run of this comparison reported zero lint
findings for both trees. That was wrong: flake8 was not installed, and the empty
output was mistaken for a clean result. The figures above come from a run verified to
have executed. Separately, upstream produces two parse errors under Python 3.11
because it uses f-string syntax introduced in 3.12; those are an artefact of the
analysis environment, not defects in upstream, and are excluded from its count.

---

## Verification addendum (2026-09-09)

Re-checked against `napieraj/glkvm-debloat` at `3e8dd23` — the same commit this
audit was written against, and still the tip of `main`. All fourteen findings of
the original pass are present and unfixed. (The session-invalidation finding is a
fifteenth, added later from the test-harness work rather than from that pass; the
counts above include it.) flake8 under the repository's own
`testenv/linters/flake8.ini` still reports exactly **742** violations. The
structural counts were re-derived and hold: 232 `@exposed_http` decorators
under `kvmd/apps/kvmd/`, of which exactly one is multi-line
(`api/upgrade.py:702-708`, `GET /upgrade/gui_compare`).

Two corrections to the findings above.

**Finding 13 (Wake-on-LAN) is overstated as written.** `valid_mac()` *is*
applied, at `api/wol.py:142` (`/wol/wake`) and `:165` (`/wol/add`). What is
actually unvalidated is `ip` and `name` (`:168-169`), both persisted to the
on-device list and written to the log; `/wol/remove` also skips validation but
only deletes a matching row. The "a MAC validator already exists in the fork's
shared helpers" framing is wrong — it is used, just not on every field. The
remaining defect is real but narrower than the entry claims.

**Finding 14 upgrades from a static read to an observed failure.** Running the
MCP branch's test suite in a container with no `/proc/gl-hw-info/model`, the
`except` branch in `get_model_name()` executed and collection died with
`NameError: name 'get_logger' is not defined` (`kvmd/utils.py:39`; the module
imports only `sys` and `types` at `:23-24`). Because `api/msd.py:65`,
`api/system.py:62`, `api/fingerbot.py:46` and both OTG plugins call
`get_model_name()` at import time, one missing hardware file takes the entire
daemon down. This is also what makes the repository's own test harness red
before any change is made, independently of anything else in this audit.
