# kvmd-lean — build plan (from reconnaissance, 7 agents)

> **Drift stamp — added when this plan was committed to the repo, 2026-09-09.**
>
> This plan was derived against `653f840` (fork 1.10.0 + the first MCP commit).
> The `mcp` branch has since advanced to `7b1cdbb`, two further commits that
> touch only `mcp.py`, `mcp_test.py` and `docs/mcp.md`.
>
> - **`server.py` and vendor-file citations still hold.** Re-verified at
>   `7b1cdbb`: the MCP import is still `server.py:112` and the registration
>   still `server.py:259`, because the later commits add no lines to
>   `server.py`. Every line number quoted below for `server.py`, `auth.py`,
>   `api/*.py`, `web/`, `PKGBUILD` and the `Makefile` is unaffected.
> - **Every `mcp.py` citation is stale by roughly +14 lines.** The file grew
>   1,418 → 1,649 lines. The one citation used below — `mcp.py:282-283`, the
>   `read_json_file` / `valid_mac` imports from `api/common.py` — is
>   **`mcp.py:296-297` at `7b1cdbb`**. The dependency itself is unchanged, so
>   the conclusion (do not delete `api/common.py`; `read_json_file` is not
>   dead) stands.
>
> Step 0's own instruction — re-derive line numbers at HEAD rather than
> trusting the ones written here — now applies to this document itself.

> **THIS TREE IS A DAEMON INSIDE A FIRMWARE IMAGE NOBODY HERE HAS.** `kvmd` is
> one process in a GL.iNet buildroot system. The init scripts, the updater
> binaries, the bootloader and its environment, and the tunnel client are all
> outside both repositories and cannot be read, changed or removed from here.
>
> So **"not in the repo" never means "not on the device"**, and a search of this
> tree can only ever prove the absence of a CALLER, never of a mechanism. Three
> findings in two sessions turned on exactly this: `rtty` (GL ships it as
> `S99rtty`), the updater (`updateEngine` and `swupdate_start.sh`, invoked here
> by name and shipped by neither tree), and the flash trigger (`--misc=update`
> writes a partition the BOOTLOADER reads). Each time the repo-scoped conclusion
> was "orphaned, therefore inert", and each time it was wrong.
>
> When a question is about device state or device behaviour it goes to
> `test_on_device_residuals` in the attestation suite — not into this plan, and
> not into a grep. Where it needs a procedure rather than a yes/no, it goes to
> `docs/bench-checks.md`.

> **SIX BUILD HAZARDS. All six have bitten in this project, three of them twice,
> and every one returns SILENTLY rather than failing loudly.**
>
> **1. The local flake8 gate does not catch dead code.** flake8 reports unused
> IMPORTS (F401); it says nothing about an unused module-level function or class.
> Those need `vulture`, which is in the tox envlist and is NOT installed in the
> usual working container. Two consequences: removing dead code often leaves the
> lint count unchanged, which is not evidence the removal was unnecessary; and a
> deletion pass that orphans helpers passes every gate you can run by hand. The
> lockout deletion left three `valid_rate_limit_*` validators in
> `validators/auth.py` with zero callers, the count did not move, and they were
> found later by someone reading the file. `make tox` is the only gate that would
> have caught it.
>
> **2. Never put a non-zero-exiting linter before a command that must run, in an
> `&&` chain.** `flake8` exits 1 whenever it reports findings, and this project
> always has findings. So `git stash && flake8 > out && git stash pop` does NOT
> pop — the chain short-circuits and the tree is left stashed, which looks exactly
> like the edits were never made. All of Task 2 sat in `stash@{0}` while the tests
> reported nonsense. Use `;`, or run the linter last.
>
> **3. A test suite in `testenv/tests/` has the repo root as its GRANDPARENT.**
> `os.path.dirname(__file__)` is `testenv/tests`, so the root is `"..", ".."`. One
> level short is not an error: `os.walk` on a directory that does not exist yields
> nothing and `os.path.exists` returns False, so a grep-based assertion finds no
> offenders and an absence assertion trivially holds. Five assertions in
> `test_attestation.py` passed VACUOUSLY on that mistake, caught only because the
> mutation pass reverted a fix and the matching test stayed green.
> `test_routes.py` gets it right — copy from it. And distrust a path-based
> assertion that passes on its first run until you have mutated what it checks.
>
> **4. `git checkout <sha> -- <path>` STAGES what it restores**, so the obvious
> undo does not undo. A later `git checkout HEAD -- <path>` leaves files that are
> not in HEAD (they are in the index now), and `git clean -fd` skips them because
> staged paths are not untracked. A mutation experiment therefore leaves its
> reverted files on disk and the next run fails on your own leftovers rather than
> on the code — the attestation suite went red on exactly that, twice. Recovery,
> in order and with `;` per hazard 2:
>
>     git reset HEAD -- . ; git checkout HEAD -- . ; git clean -fdx
>
> **5. `git checkout -- <path>` on UNCOMMITTED work destroys it, with no stash
> and no reflog.** The sibling of hazard 4, and the one that bites when reverting
> a mutation: `git checkout -- <file>` restores from HEAD, so it discards every
> uncommitted edit in that file, not just the mutation you meant to undo. Step 6
> lost its whole `api/system.py` edit that way — four handlers, the constructor
> reduction, the import fix — and it was recoverable only because the edits were
> scripted and could be replayed verbatim. `git checkout` reverts to a COMMIT;
> a mutation on uncommitted work must be reverted to a SNAPSHOT:
>
>     cp <file> $SNAP/<file>.ok      # before mutating
>     ... mutate, run the test ...
>     cp $SNAP/<file>.ok <file>      # never git checkout
>
> **6. The test deps are not all installed, and their absence reads as failure,
> not as absence.** A run in a container missing `pytest-aiohttp`, `pytest-mock`
> and `python-pam` reports **6 failed, 700 passed, 16 errors** — not "skipped",
> not "cannot collect". Every one of those is the environment, and a bisect
> against them finds nothing. Restore with:
>
>     python3 -m pip install --break-system-packages pytest-aiohttp pytest-mock python-pam
>
> and confirm the whole suite is green BEFORE trusting a red on your own change.
> Related correction: `testenv/tox.ini` says `basepython = python3.12`, but in
> the working container **pytest and the runtime deps are installed for 3.11**
> and 3.12 has neither. Runs reported in this project's history as "green on
> python3.12" were green on 3.11 — the tox config was read as if it described
> the interpreter that actually ran. Check with `python3 -V` and
> `python3 -c "import pytest"`, do not infer it from the config.
> **A PARTIAL TESTENV GIVES A FALSE GREEN. Read this before believing any
> "the tests pass" claim, including your own.**
>
> Step 1 was first reported complete against a partial environment, and the
> number was wrong in the dangerous direction. 21 tests in
> testenv/tests/apps/htpasswd were failing on missing configuration —
> /etc/kvmd/main.yaml, /usr/share/kvmd/extras, the TLS material, /usr/bin/
> ustreamer, /sbin/ip — and were written off as "environmental". They were
> not. Once the environment was completed, those config errors stopped firing
> first and **9 genuine code divergences appeared underneath them**, including
> the one that revealed kvmd-htpasswd and the web password path hash
> differently (now docs/audit.md, HIGH). A missing config file and a real
> defect produce the same red line, and the config error wins the race.
>
> So: an incomplete environment does not merely hide tests, it *misclassifies*
> them, and it does so silently. Any claim that the suite passes must be made
> against the COMPLETE testenv and on BOTH interpreters. **Now actually done,
> and they agree exactly: 745 passed / 2 skipped on 3.12.3, and 745 passed / 2
> skipped on 3.11.15** — same tree, same staged environment. The substitution
> worry (`tarfile`, dict ordering, stdlib hashes) is closed for this branch. The
> label correction in hazard 6 stands on its own: earlier counts really were
> reported against the wrong interpreter, they were simply not wrong numbers.
>
> Staging 3.12 took six packages beyond the 3.11 set, each presenting as a
> collection ERROR rather than a skip (hazard 6 again): aiofiles, evdev, pillow,
> python-xlib, zstandard, async_lru — on top of pytest, pytest-mock,
> pytest-aiohttp, pytest-asyncio, python-pam, aiohttp-basicauth, passlib,
> pyyaml, dbus-next, pyserial, setproctitle, psutil, netifaces and pygments.
> `systemd-python` does not build here; neither interpreter has it and nothing
> in the suite needs it. tox pins
> basepython = python3.12 (testenv/tox.ini:6) while a bare `python3` on a
> workstation is often 3.11, and the two disagree about which optional test
> dependencies are installed.
>
> The reference numbers, for comparison after the strip: **666 passed, 0
> failed, 0 errors** with the environment fully staged — recorded at the time as
> "on python3.12", but see hazard 6: the interpreter that actually ran was 3.11.
> Nothing in this project has yet been measured on the declared 3.12. Quote the
> dep set with the count, not just the interpreter: a run missing pytest-aiohttp,
> pytest-mock or python-pam reports failures, not skips. To stage
> it outside the container, follow the `tox` recipe in the Makefile (85-91):
> the config copy, the platform file, main.yaml from the platform variant,
> and the extras/keymaps/configs.default paths, plus pytest-mock,
> pytest-aiohttp, python-pam and the ustreamer stub.


Line numbers below were derived on a tree at 1.10.0 + the MCP commit.
Step 0 says to re-derive them; do that before trusting any of them.

## Steps

### 0. STOP — re-derive server.py line numbers; the worktree is NOT pristine 1.10.0

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/server.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/mcp.py

**Done when:** git log --oneline -2 shows 653f840 on top of 3e8dd23 (1.10.0), and you have re-grepped server.py at HEAD instead of trusting any server.py line number in the reconnaissance.

HEAD = 1.10.0 + commit 653f840 'kvmd: MCP endpoint for agent-driven console control', which adds kvmd/apps/kvmd/api/mcp.py (1418 lines) plus exactly 2 lines to server.py: the import at server.py:112 and the registration McpApi(...) at server.py:259. Every recon agent read server.py at the tag, so its citations are LOW BY 1 below line 112 and LOW BY 2 below line 259. Verified HEAD numbers: doomed imports 84,85,87,88,89,90,92,93,94,95,109 (unchanged, they precede 112); __EV_ constants 174-177 (recon said 173-176); attribute assignments 216-220 (recon said 215-219); __apis doomed entries 227,228,231,232,233,234,235,236,237,238,239 (recon said 226-238); SystemApi(...) block 240-244 (recon said 239-243); __subsystems doomed entries 275-278 (recon said 273-276); the two gl_kvm_gui killalls at 663 and 671 (recon said 661,669); /hid/ws exe-path route at 580 (recon said 578). Applying edits by the recon's line numbers will corrupt server.py. Also: api/mcp.py is a KEEP and imports read_json_file and valid_mac from api/common.py (mcp.py:282-283), so common.py has two surviving importers and read_json_file is NOT dead after the strip.

### 1. Make the test harness green before touching anything else

**Files:** /home/user/glkvm-lean/kvmd/utils.py, /home/user/glkvm-lean/testenv/tests/apps/kvmd/test_auth.py

**Done when:** make tox E=pytest collects and passes on an otherwise unmodified tree. Commit alone, so every later failure is attributable.

Reproduced in this sandbox: pytest dies at collection with NameError: name 'get_logger' is not defined, raised from kvmd/utils.py:39 inside get_model_name()'s except branch; the module imports only sys and types (utils.py:23-24). Fix: add `from .logging import get_logger` to kvmd/utils.py (design section 4 line 260 already schedules this; it is not tidying, it is what un-breaks the harness). Second, independent break: testenv/tests/apps/kvmd/test_auth.py:42-44 constructs HttpExposed with 4 positional args, but the fork's dataclass has 6 fields — method, path, auth_required, allow_usc, allowed_exe_paths, handler (kvmd/htserver.py:94-100). Rewrite those three lines as 6-arg calls. Third: the AuthManager fixture at test_auth.py:61-73 and :192-204 uses stale upstream kwargs (internal_type/internal_kwargs/force_internal_users/external_type/external_kwargs) and omits the required expire/usc_users/usc_groups; the real signature is auth.py:96-119. Rewrite both call sites now — you must edit them again in step 4 anyway to drop totp_secret_path (test_auth.py:72,203).

### 2. Snapshot the route inventory with an AST walk (the 'before' for the regression test)

**Files:** /home/user/glkvm-lean/kvmd/htserver.py, /home/user/glkvm-lean/testenv/tests/

**Done when:** A committed fixture lists every (method, path, auth_required, allow_usc, allowed_exe_paths) tuple in kvmd/apps/kvmd/, and a test regenerates and diffs it.

Do not use a line regex: of the 232 @exposed_http decorators under kvmd/apps/kvmd/, 231 are single-line and exactly one is multi-line — kvmd/apps/kvmd/api/upgrade.py:702-708, GET /upgrade/gui_compare. A grep-based sweep silently misses the one route that most needs finding. Walk the tree with `ast` instead; no imports, no server instance, no MODEL_PATH monkeypatch needed. KvmdServer itself contributes 4 http routes (server.py:509,538,546,580) and 2 ws (593,598). Do NOT bake /switch routes into the expected set: SwitchApi is registered only when switch is not None (server.py:261-262, 282-283) and kvmd/apps/kvmd/__init__.py:94-101 sets switch = Switch(...) only when get_hw_model() == 'rm4pe'. On an RM1PE there is no switch and no /switch routes, before or after the strip.

### 3. The strip — delete the 12 files and fix all 35 dangling lines in server.py, atomically

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/api/tailscale.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/zerotier.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/netbird.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/netbird_daemon.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/cloudflare.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/astrowarp.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/turn.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/repeater.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/ap.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/modem.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/custom_screen.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/twofa.py, /home/user/glkvm-lean/kvmd/apps/kvmd/server.py

**Done when:** python3 -c 'import kvmd.utils as u; u.MODEL_PATH="/etc/hostname"; import kvmd.apps.kvmd.server' succeeds, and the route inventory from step 2 shrinks by exactly 86 routes with no kept route missing.

Deleting these 12 files breaks exactly ONE file: server.py. Verified by per-module grep over the whole worktree: nothing in kvmd/apps/__init__.py, kvmd/apps/kvmd/__init__.py, configs/, web/, nginx, setup.py, PKGBUILD, Makefile, kvmd.install or testenv/ names them. netbird_daemon.py has exactly one importer, netbird.py:43, so the two go together. The 35 server.py lines are enumerated in danglingReferences. Order inside the step matters: if you remove the API objects at 216-220 but leave the _Subsystem.make lines at 275-278, you get a hard failure at construction, not a soft one. CORRECTION, measured: the exception is AttributeError, not AssertionError — _Subsystem.make reads its state with getattr(obj, ..., None), so a MISSING api object blows up earlier, at the `self.__X_api` read itself. AssertionError is the OTHER case: an api object that exists but has no trigger_state/poll_state. Both were reproduced against testenv/tests/apps/kvmd/test_server_smoke.py; both are dead-daemon-at-startup, so the atomicity requirement stands unchanged — _Subsystem.__post_init__ (server.py:142-144) asserts trigger_state and poll_state whenever event_type is truthy. Consumers to sanity-check afterwards: self._add_exposed(*self.__apis) at server.py:632 publishes the routes; __subsystems is walked at 569, 612, 623, 649. DO NOT delete kvmd/apps/kvmd/api/common.py — wol.py:38 imports make_device_name_from_mac/run_process/valid_mac from it and mcp.py:282-283 imports read_json_file/valid_mac. Route count removed: tailscale 16, zerotier 12, netbird 14, cloudflare 4, astrowarp 6, turn 1, repeater 10, ap 4, modem 6, custom_screen 7, twofa 6 = 86. chardet (imported by ap.py:10, modem.py:10, repeater.py:9, custom_screen.py:29) is an undeclared dependency today and simply stops being needed — do not add it to PKGBUILD.

### 4. Remove TOTP everywhere, in one commit, including the login page field

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/auth.py, /home/user/glkvm-lean/kvmd/apps/kvmd/__init__.py, /home/user/glkvm-lean/kvmd/apps/__init__.py, /home/user/glkvm-lean/kvmd/apps/totp/__init__.py, /home/user/glkvm-lean/setup.py, /home/user/glkvm-lean/PKGBUILD, /home/user/glkvm-lean/kvmd.install, /home/user/glkvm-lean/configs/kvmd/totp.secret, /home/user/glkvm-lean/Makefile, /home/user/glkvm-lean/web/login/index.pug, /home/user/glkvm-lean/web/login/index.html, /home/user/glkvm-lean/web/share/js/login/main.js, /home/user/glkvm-lean/web/share/css/login/login.css, /home/user/glkvm-lean/testenv/tests/apps/kvmd/test_auth.py

**Done when:** grep -rin 'totp\|pyotp\|2fa\|code-input' kvmd/ web/ setup.py PKGBUILD kvmd.install configs/ returns nothing; a password with a 6-char suffix authenticates unchanged; make tox is green.

Deleting twofa.py (step 3) does NOT remove TOTP — enforcement lives in AuthManager and runs on EVERY credential path, not just the login form: /auth/login (api/auth.py:219), the X-KVMD-User/X-KVMD-Passwd header path (api/auth.py:70-80) and HTTP Basic (api/auth.py:94-107). Remove, in this order: auth.py:31 `import pyotp`; auth.py:111 the required param `totp_secret_path: str,` (it sits between ext_kwargs at 109 and the rate_limit defaults at 113); auth.py:157 `self.__totp_secret_path = totp_secret_path`; auth.py:206-215, the whole enforcement block — keep 199-205 and 217-228 verbatim, `logger = get_logger(0)` at 204 is still used at 225/227. Then the single production call site, kvmd/apps/kvmd/__init__.py:118 `totp_secret_path=config.auth.totp.secret.file,` (inside the AuthManager block 104-126). Then the schema at kvmd/apps/__init__.py:450-454. WEB IS ATOMIC WITH THIS: web/share/js/login/main.js:61 concatenates the code into the password (`$("passwd-input").value + $("code-input").value`) and auth.py:211-215 slices it back off. Removing the field without removing the server slice silently eats the last 6 chars of every real password whenever /etc/kvmd/user/totp.secret is non-empty; removing the slice without the field appends garbage. Edit web/login/index.pug:38-40 (delete the tr) AND web/login/index.html:75-80 (the generated mirror — PKGBUILD:171 strips .pug, so the .html is what ships), drop #code-input from main.js:43, 61, 97, 103 and from the selector at web/share/css/login/login.css:53-58. The kvmd-totp CLI is a SEVENTH consumer nobody listed: kvmd/apps/totp/__init__.py:26 imports pyotp, :27 qrcode, and :34-38 reads config.kvmd.auth.totp.secret.file — removing the schema key turns the shipped binary into a crash-on-start, so delete the package and setup.py:96 (`"kvmd.apps.totp",`) and setup.py:125 (`"kvmd-totp = kvmd.apps.totp:main",`) in the same commit. Only then may you drop PKGBUILD:56 python-pyotp and :57 python-qrcode (and testenv/Dockerfile:49-50). PACKAGING TRAP: configs/kvmd/totp.secret is the ONLY file matching *.secret, and the glob appears in PKGBUILD:180, PKGBUILD:195 and in FIVE &&-chained Makefile recipes (88 tox, 130 run, 157 run-cfg, 180 run-ipmi, 203 run-vnc). Deleting it makes cp exit non-zero and `make tox` never reaches tox. Either keep the 0-byte file or edit all seven sites plus PKGBUILD:147 (backup=) and kvmd.install:21. Finally drop totp_secret_path from test_auth.py:72 and :203. Bonus: auth.py:208's open() is unguarded, so removing this block also fixes a latent total-lockout bug when /etc/kvmd/user/totp.secret is absent.

### 5. Remove the two-step (gl_kvm_gui approval) login — a separate second factor from TOTP

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/auth.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/auth.py, /home/user/glkvm-lean/kvmd/apps/kvmd/__init__.py, /home/user/glkvm-lean/kvmd/apps/__init__.py

**Done when:** grep -rn 'two_step' kvmd/ returns nothing; POST /auth/login unconditionally returns {token, failed_since_last_success} with the auth_token cookie set.

This is NOT a schema cleanup, it is a hard dependency: /auth/two_step_pending, _approve and _reject are gated by allowed_exe_paths=['/usr/sbin/gl_kvm_gui'] (api/auth.py:287,295,310), and _check_exe_path is EXCLUSIVE — any HTTP caller gets ForbiddenError (api/auth.py:146-159). With the GUI masked (design section 5) a two-step login can never be approved and every login hangs at status 'pending' forever. In api/auth.py: delete 201-217 (the `if self.__auth_manager.is_two_step_login_enabled():` branch) and de-indent the single-step body at 218-230 so it is unconditional — that body is the break-glass path and must survive; keep the RateLimitError handler at 231-237. Delete POST /auth/two_step_complete (261-285), GET /auth/two_step_pending (287-293), POST /auth/two_step_approve (295-308), POST /auth/two_step_reject (310-323), GET+POST /auth/two_step_login (325-345). Line 344 is the only use of the import at api/auth.py:53 (`from .config_utils import set_yaml_value as _set_yaml_value`) — delete that import. In auth.py: delete the _TwoStepSession dataclass (58-72), the ctor param at 118 and the state at 181-187, the accessor trio 382-392, pre_login 394-449 (which carries the `killall -SIGUSR2 gl_kvm_gui` at 435), complete_two_step_login 451-491, __make_new_two_step_token 493-498, and the helpers 500-555. `from ... import tools` (auth.py:37) is then orphaned — its only use in the file is line 435; `from ... import aiotools` (auth.py:36) must STAY, it is still used at auth.py:557 (@aiotools.atomic_fg on cleanup()). Then kvmd/apps/kvmd/__init__.py:125 and the schema at kvmd/apps/__init__.py:463-465. Stale kvmd/auth/two_step_login/enabled keys already written into /etc/kvmd/user/boot.yaml by the old POST route are harmless — yamlconf.make_config iterates the SCHEME, not the raw dict (kvmd/yamlconf/__init__.py:200-207) — so no DEPRECATED_BOOT_KEYS entry is needed. web/ needs no change here: grep for two_step across web/ returns zero hits; that client lives in the GL.iNet binary.

### 6. Remove the surviving gl_kvm_gui coupling in KEPT modules

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/api/system.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/upgrade.py, /home/user/glkvm-lean/kvmd/apps/kvmd/server.py

**Done when:** grep -rn 'gl_kvm_gui' kvmd/ returns only the comment at kvmd/htserver.py:302; grep -rn 'allowed_exe_paths' kvmd/ returns exactly one hit, server.py:580 (gl-pion).

Full verified inventory of allowed_exe_paths at HEAD: tailscale.py 8 (210,289,320,401,490,525,712,731), netbird.py 7 (204,240,290,308,324,372,459), zerotier.py 6 (215,250,285,361,438,461) — all gone with step 3; api/auth.py 5 (287,295,310,325,332) — gone with step 5; api/system.py 4; api/upgrade.py 1; server.py 1 (gl-pion, KEEP). That is 32 routes across seven files, not the 12 in two files that findings 3 claims. Delete in system.py: GET /system/clients (163-216; 218 begins GET /system/capability which stays), DELETE /system/clients/{client_id} (243-344; 346 begins _get_ethernet_service_id which stays), GET /system/gui_get_param (824-827, a 4-line delegate to get_param_handler at 785), POST /system/gui_set_param (952-955, a delegate to set_param_handler at 829). Then SystemApi's three ctor kwargs (system.py:67-69 declarations, 72-74 storage) become dead — their only readers are 167,173,247,270,294,296,312,339, all inside the two deleted handlers — so reduce the construction at server.py:240-244 to `SystemApi(),`. The callbacks themselves (htserver.py:503,506) must stay; kvmd/apps/pst/server.py also uses _get_wss. NOTE R4.1 dependency: deleting DELETE /system/clients removes the only `/etc/init.d/S80ttyd restart` (system.py:321) and also the only `killall janus` and `/etc/init.d/S99gl-pion restart` in the tree — you lose the only recovery for a wedged WebRTC/ttyd session; accept that deliberately. In upgrade.py delete GET /upgrade/gui_compare (702-708, the tree's only multi-line @exposed_http). In server.py delete the killall lines 663 and 671 with their comments at 662 and 670; `tools` is then used nowhere else in server.py (verified: the only `tools.` hits are 663 and 671), so drop `from ... import tools` at server.py:45 — keep aiotools (server.py:43), used at 285,622,627,630,631,637,639.

### 7. R4.1 — strip ttyd and the web terminal

**Files:** /home/user/glkvm-lean/web/kvm/window-webterm.pug, /home/user/glkvm-lean/web/kvm/windows.pug, /home/user/glkvm-lean/web/kvm/navbar-system.pug, /home/user/glkvm-lean/web/share/js/kvm/info.js, /home/user/glkvm-lean/web/kvm/index.html, /home/user/glkvm-lean/web/extras/webterm/

**Done when:** grep -rn 'ttyd\|webterm' over kvmd/ web/ (excluding .min.js) returns nothing, and htmlhint passes on web/kvm/index.html.

Verified hits: web/kvm/windows.pug:5 (`include window-webterm.pug`), web/kvm/navbar-system.pug:14-15 (the 'Term' button), web/kvm/window-webterm.pug:1,11, web/share/js/kvm/info.js:252-271, and api/system.py:321 which step 6 already removed. Delete web/kvm/window-webterm.pug and web/extras/webterm/. web/kvm/index.html is GENERATED (Makefile:231, `pug --pretty web/kvm/index.pug -o web/kvm`, target `make pug`, which depends on the testenv container) and carries the webterm markup at 148-149 and 3028-3039. Per R5.15, regenerate with `make pug` and commit the generated file in the same commit; only hand-edit if the container is unavailable, and then keep it byte-consistent with the pug. htmlhint lints web/*.html and web/*/*.html (testenv/tox.ini:59-61), so a hand-edit that breaks tag pairing turns make tox red on an unrelated env.

### 8. R4.2 — delete GET and POST /system/ssh_key

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/api/system.py

**Done when:** grep -rn 'authorized_keys' over the whole tree returns nothing.

GET at system.py:1651-1670 leaks the current /root/.ssh/authorized_keys; POST at system.py:1672-1702 reads the raw request body (`await request.text()`, 1677) and writes it verbatim with no validation, creating /root/.ssh at 0700 and the file at 0600. Any authenticated caller gets permanent root shell that bypasses the cert-only sshd config and the OpenBao SSH CA. Verified: the tree's only three authorized_keys references are system.py:1655, 1683 (comment) and 1684, so the R4.4 contract test is exact after this. Note this closes the beacon's own route to writing authorized_keys — that is intended (R4.3: AuthorizedKeysFile none), and the beacon writes sshd_config directly as root anyway.

### 9. R5.14 / D-008 — split api/upgrade.py, keep EDID, delete the WAN and reset routes

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/api/upgrade.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/edid.py, /home/user/glkvm-lean/kvmd/apps/kvmd/server.py

**Done when:** grep -n 'fw.gl-inet.com\|reset_default' kvmd/ returns nothing; the three EDID routes still answer; EdidApi is registered next to UpgradeApi in __apis.

Verified routes in upgrade.py: WAN egress is BASE_URL at 38 and BETA_BASE_URL at 39, consumed at 603-605 and exposed by GET /upgrade/download (794), GET /upgrade/beta/download (800), GET /upgrade/download_cancel (827), GET /upgrade/download_info (842) — all contradict D-001. GET /upgrade/reset_default (781-792) runs `/usr/sbin/reset_default.sh` via create_subprocess_shell (792); since a factory reset clears the launcher pin (design 3.3), one authenticated GET un-enrols the device. Delete 781-792 and 794-849, plus POST /upgrade/start (721) per R5.14. Move POST /upgrade/edid (851), GET /upgrade/get_edid (905), GET /upgrade/edid_list (922) into a new api/edid.py. Keep in a trimmed upgrade.py: POST /upgrade/upload (665), GET /upgrade/compare (697), GET /upgrade/version (710), GET /upgrade/reboot (716), GET /upgrade/status (777), GET+POST /upgrade/log (935,939). Register EdidApi in server.py's __apis list next to UpgradeApi (currently line 252). Note upgrade.py:37 duplicates MODEL_PATH; after step 3 the surviving duplicates are utils.py:32, kvmd/apps/kvmd/__init__.py:45 and upgrade.py:37 — consider consolidating on kvmd.utils.MODEL_PATH so tests can monkeypatch one constant.

### 10. Revision 5 security pass — one commit and one test per item

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/auth.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/auth.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/init.py, /home/user/glkvm-lean/kvmd/apps/kvmd/server.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/wol.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/msd.py, /home/user/glkvm-lean/configs/nginx/kvmd.ctx-server.conf

**Done when:** Each numbered R5 item has a commit and a test; no credential or token is read from req.query anywhere in kvmd/apps/kvmd/.

Verified line numbers at HEAD. R5.1: auth.py:594 `def _get_client_ip(self, req_headers: dict)` cannot see the socket peer by construction; callers api/auth.py:186, 353, 387. Change the signature to take the Request and derive the peer, honouring X-Real-IP/X-Forwarded-For only from loopback — findings 8 notes upstream already does this with SO_PEERCRED at pikvm/kvmd/htserver.py:305-309; copy that rather than inventing one. R5.2: delete the sampling condition `hash(client_ip) % 100 == 0` at auth.py:248 AND auth.py:413 (the second is inside pre_login, which step 5 deletes wholesale — so after step 5 only :248 remains; do not report the item as done from the pre_login deletion alone). R5.4: GET /init/init at api/init.py:62 is auth_required=False and takes the password in a query param (init.py:67) — recommend deleting the route outright. R5.5: api/init.py:97-99 read user/old_password/new_password from req.query and the is_inited guard at 94-95 is commented out; move to the POST body and restore the guard. R5.8: api/auth.py:350 rate_limit_status takes an arbitrary client_ip and :366-377 unlock_client clears any address. R5.9: remove query-token acceptance at api/auth.py:122-131, :245 and the fallback at server.py:557. R5.11: /redfish/v1 is auth_required=False at api/redfish.py:68. Findings 8's recommendation is worth taking seriously: the entire rate-limit/lockout/unlock subsystem is a GL invention with zero upstream counterpart, is bypassable (R5.2) and is an attacker primitive (R5.8) — deleting it returns auth.py toward upstream and removes more code than fixing it does.

### 11. Add the passwordless mint on AuthManager, then api/webauthn.py

**Files:** /home/user/glkvm-lean/kvmd/apps/kvmd/auth.py, /home/user/glkvm-lean/kvmd/apps/kvmd/api/webauthn.py, /home/user/glkvm-lean/kvmd/apps/kvmd/server.py

**Done when:** A unit test asserts login_verified() returns a 64-lowercase-hex token that AuthManager.check() resolves to the right user, and the assert route answers with set_cookies={'auth_token': token}.

Design 3b says 'success mints the same session token the password path mints today', but there is NO public way to do that: login() at auth.py:230 always calls authorize() first (auth.py:251), and every primitive is name-mangled — __make_new_token (auth.py:286), __make_expire_ts (auth.py:293), __sessions (auth.py:159), __consume_failed_since_last_success (auth.py:280), plus the _Session dataclass (auth.py:47-55). api/webauthn.py cannot reach any of them. Add a public method inside the AuthManager class body, e.g. login_verified(self, user: str, expire: int) -> tuple[str, int], mirroring auth.py:251-264 exactly and calling __consume_failed_since_last_success or the UI's failed-count silently stops resetting. Route through __make_expire_ts: session expiry uses time.monotonic() (auth.py:314-315), so a mint that computes expire_ts from time.time() produces sessions that expire immediately or never. The token must be 64 lowercase hex or every later request fails valid_auth_token's ^[0-9a-f]{64}$ (kvmd/validators/auth.py:69). Register routes as @exposed_http('GET', '/auth/webauthn/challenge', auth_required=False, allow_usc=False) and the POST equivalent; do NOT set allowed_exe_paths — it is exclusive (api/auth.py:146-159) and would make the route unreachable from any browser. Add WebAuthnApi(auth_manager) to __apis next to AuthApi(auth_manager) at server.py:225. nginx needs no change: location /api rewrites ^/api/(.*)$ and sets auth_request off (configs/nginx/kvmd.ctx-server.conf:110-116). Verify: a _Session asserts a non-empty UNIX-style user (auth.py:52-55) matching valid_user ^[a-z_][a-z0-9_-]*$, so each stored credential must carry a username satisfying that regex — the design's credential tuple {credential_id, public_key_cose, sign_count, aaguid, label} has no such field.

### 12. Login page: add the security-key button (do not delete the username/password rows)

**Files:** /home/user/glkvm-lean/web/login/index.pug, /home/user/glkvm-lean/web/login/index.html, /home/user/glkvm-lean/web/share/js/login/main.js, /home/user/glkvm-lean/web/share/css/login/login.css

**Done when:** make pug regenerates web/login/index.html with no diff against the hand state, eslint and htmlhint pass, and the button completes a ceremony against a virtual authenticator.

Add the button row after the login button (web/login/index.pug:53-55 / web/login/index.html:104-109) and add #webauthn-button to the width rule at web/share/css/login/login.css:49-51. Bind it with tools.el.setOnClick (tools.js:154-162) next to main.js:42 — both buttons sit inside <form action='javascript:void(0)'> (index.html:50) and a <button> with no type defaults to submit, so a plain onclick reloads the page mid-ceremony. Three gotchas that will bite: (1) eslint enforces quote-props 'always' and double quotes (testenv/linters/eslintrc.js:34-41), so the options object must be written {"publicKey": {"challenge": ..., "rpId": "oskar.co", "userVerification": "required", "allowCredentials": []}} — copy-pasted WebAuthn snippets fail lint. (2) tools.httpRequest is XHR+callback with a 15 s default timeout (tools.js:51-79) while navigator.credentials.get typically waits 60 s for a tap; pass an explicit timeout or the XHR aborts mid-ceremony. (3) There are no base64url helpers anywhere in web/share/js — the only base64 code is tools.js:115-117 makeTextId, which is for DOM ids and replaces only the first '='; write real ArrayBuffer<->base64url helpers. Keep the username and password rows (index.pug:32-37): design 3.4 and section 8 both keep the password as break-glass, and the pre-enrolment device has a factory password and no credentials at all. 'No username field' means the ceremony needs no username, not that the fields are deleted.

### 13. Build kvmd/apps/beacon/ as a plain module with an init.d script, not a systemd unit

> **RESOLVED — `POST /upgrade/upload` is deleted, and "no reader" was wrong.**
> It was retained one commit on the authority of the step-9 KEEP list, which
> was written while `/upgrade/start` still consumed the uploaded image. Deleting
> the consumer made the entry stale, and re-deriving a plan means re-deriving
> the REASONING, not only the line numbers.
>
> The "no consumer" claim was also scoped to this repo, which is not the device
> — the rtty mistake again. The read half is two binaries this daemon invoked
> by name and neither tree ships: `updateEngine --image_url=/userdata/update.img
> --misc=update` on most models, `swupdate_start.sh -i /userdata/update.img` on
> rmq1. `--misc=update` writes the Rockchip misc partition, which is a
> BOOTLOADER-facing flag, so the reader is not even confined to userspace.
> `/userdata` is persistent (it also holds the MSD images and the logs), so a
> staged image survives a rootfs-only reflash, which puts it in the same
> device-verifiable class as the residual `authorized_keys` and cron entries.
>
> NOT ESTABLISHED: whether anything consumes `/userdata/update.img` WITHOUT an
> explicit trigger. That question is DEVICE-verifiable, not source-verifiable,
> so it does not belong here — it is item 7 and the lettered procedure in
> `test_on_device_residuals`, with everything else that needs a unit on the
> bench. Do not attempt it from a source checkout: this container's network
> policy blocks `fw.gl-inet.com` at CONNECT anyway, and an image is the wrong
> tool for it — a unit is.
>
> If enrolment needs to stage an image it BUILDS a pinned-signature path; it
> does not inherit this one. Ratcheted by
> `test_attest__no_route_writes_the_flash_staging_path`.


> **HAZARD — enrolment must not re-open CRITICAL 3.** `GET /init/init` is deleted,
> but `InitManager.init()` survives and now has NO caller in the tree. It is kept
> precisely because enrolment needs that operation: it sets the admin password AND
> rewrites root's entry in `/etc/shadow`. Wiring it back up is therefore
> re-exposing the method behind a CRITICAL, and the shape of the exposure is the
> whole question.
>
> Gate it behind the pinned-certificate provisioning path — an enrolment ticket
> verified against the launcher pin — and never behind anything resembling the old
> route: no `auth_required=False`, no "while the device reports itself
> uninitialised", no password in a query parameter. The old design's failure was
> not the operation; it was that an anonymous caller could invoke it while the
> uninitialised flag failed open, which `init.py:51-77` still does.
>
> `testenv/tests/test_attestation.py` catches the careless version — it asserts the
> unauthenticated surface is at most 4 routes, a ratchet that may only go down, so
> an enrolment route with `auth_required=False` turns it red. That is a backstop,
> not a design.

**Files:** /home/user/glkvm-lean/kvmd/apps/beacon/__init__.py, /home/user/glkvm-lean/setup.py, /home/user/glkvm-lean/testenv/linters/vulture-wl.py, /home/user/glkvm-lean/testenv/linters/pylint.ini

**Done when:** python3 -m kvmd.apps.beacon --run starts and exits 0 with no pin file; unit tests cover key idempotence, announcement schema and every ticket-rejection case in design section 7.

The device has no systemd — kvmd's own code says so: kvmd/apps/__init__.py:826 '# TODO:没有SYSTEMD,回头改' above a commented-out systemctl call, and kvmd/apps/kvmd/info/extras.py:98 '已经确定无法引入systemd'. Every service the fork touches is /etc/init.d/S<NN><name> invoked start|stop|restart (system.py:320-321,1540-1542,1713,2555; astrowarp.py:43,46; tailscale.py:272,303; zerotier.py:123,156; netbird.py:185,218; cloudflare.py:96,127,169; switch/sysfs_device.py:469,483). Ship /etc/init.d/S98kvmd-beacon (before whatever starts kvmd, per D-002). There is also no /usr/bin/kvmd-beacon after apply_to_glkvm.sh: console_scripts wrappers come only from `pip install` in PKGBUILD:161, and the script copies the package tree only — so the start command must be `/usr/bin/python3 -m kvmd.apps.beacon --run`, the pattern the Makefile uses for every app (Makefile:139,161,184,207). Add `"kvmd.apps.beacon",` to setup.py packages and the console_scripts line for the dev path, but do not rely on either for deployment; note setup.py's list is already stale (kvmd.apps.kvmd.switch, kvmd.apps.localhid, kvmd.apps.media, kvmd.apps.swctl all exist on disk and are absent from setup.py:67-108, and switch is imported unconditionally at kvmd/apps/kvmd/__init__.py:41), so `pip install .` from this tree yields a kvmd that cannot import its own server. TESTABILITY: expose SN_PATH and MAC_PATH as module constants and monkeypatch them — env.PROCFS_PREFIX will not help, because no /proc/gl-hw-info reader uses it and testenv/env.py is bind-mounted only in the `run` target (Makefile:109), never in `tox`. Take the beacon's file paths from config so tests can point them at tmp_path; /etc/kvmd/user does not exist until some kvmd code path makes it (init.py:81) and the tox recipe never creates it. Lint constraints: pylint max-args=10 and attr/var names capped at 30 chars (testenv/linters/pylint.ini); mypy disallow_untyped_defs, so every test needs `-> None`; any @pytest_asyncio.fixture name must be appended to testenv/linters/vulture-wl.py (only @pytest.fixture is in --ignore-decorators, tox.ini:37), as must any announcement-schema field written but never read.

### 14. Extend apply_to_glkvm.sh — it is at the repo root and does almost nothing today

**Files:** /home/user/glkvm-lean/apply_to_glkvm.sh

**Done when:** A single run syncs kvmd/, writes the pin, installs the beacon init script, deploys the web assets, and re-applies the daemon masks — and is safe to re-run after a firmware update.

The file is /home/user/glkvm-lean/apply_to_glkvm.sh, NOT scripts/apply_to_glkvm.sh; scripts/ holds only kvmd-bootconfig, kvmd-certbot, kvmd-gencert, kvmd-udev-hdmiusb-check, kvmd-udev-restart-pass. Patching the design's path creates a second, dead file. The whole current body (36 lines): vars at 3-7 (LOCAL_DIR=kvmd relative, so it must run from the repo root; REMOTE_HOST=glkvm.local; REMOTE_DIR=/usr/lib/python3.12/site-packages/kvmd; root; port 22), a directory check at 9-12, a client check at 14-17, `ssh root@glkvm.local "rm $REMOTE_DIR/* -R"` at 34 with its exit status discarded, and `scp -r -P 22 kvmd/* ...` at 20. It runs on the developer's workstation, not on the device. It installs no service, writes nothing to /etc, and deploys neither web/ nor configs/. Add, after the transfer succeeds (inside the branch at 22-24): mkdir -p /etc/kvmd/user; scp the launcher pin to /etc/kvmd/user/launcher_pin.pub then chmod 444 and `sync`; scp the S98kvmd-beacon init script to /etc/init.d and chmod 755; scp web/ to /usr/share/kvmd/web (VERIFY that path on a real unit first); run the daemon-masking block. /etc/kvmd/user is outside REMOTE_DIR so the rm at 34 does not touch it — but equally, a re-run will not refresh the pin unless you add the explicit scp, and design 3.3's rotation story depends on it being rewritten every run. Harden the rm in the same pass (design section 8 requires idempotence): add set -e, quote and validate REMOTE_DIR, check the ssh return code. If you move the file into scripts/ it comes under shellcheck (testenv/tox.ini:65) and its existing `command -v scp &> /dev/null` bashism at line 14 under a #!/bin/sh shebang, plus SC2181 on `if [ $? -eq 0 ]` at 22, become CI failures — fix them if you move it. Keep the rm: it is what guarantees the 12 deleted modules and their __pycache__ actually vanish on-device.

### 15. Contract and regression tests, plus docs/lean.md (a new file in a new directory)

**Files:** /home/user/glkvm-lean/testenv/tests/, /home/user/glkvm-lean/docs/lean.md, /home/user/glkvm-lean/testenv/Dockerfile, /home/user/glkvm-lean/testenv/tox.ini

**Done when:** make tox is green with the contract tests in place, and docs/lean.md records the on-device facts the repo cannot prove.

There is no docs/ directory — `ls -d docs` fails; top level is LICENSE, Makefile, PKGBUILD, README.md, apply_to_glkvm.sh, configs, contrib, extras, genmap.py, hid, keymap.csv, kvmd, kvmd.install, scripts, setup.py, testenv, web. Contract tests, all implementable as AST or grep over the tree with no imports: (a) no reference to authorized_keys, ttyd, webterm, or gl_kvm_gui; (b) the only allowed_exe_paths left is server.py:580 gl-pion; (c) the serial appears in no announcement and no API route — after step 3, astrowarp.py:53 SN_PATH is gone and /proc/gl-hw-info/device_sn has no reader but the beacon, so write the test to permit the beacon's internal read and forbid transmission; (d) R4.4's shell test must be phrased as 'no ast.JoinedStr, BinOp(%|+) or .format() is passed as the command argument to run_shell/run_command/create_subprocess_shell', which is true today — a naive 'first arg is a string literal' assertion produces two false positives, system.py:325 (loop variable over the constant list at 318-322) and switch/sysfs_device.py:223 (a wrapper whose three callers at 274,469,482 all pass literals). Design section 7's container end-to-end test needs work that does not exist: `make run` is the only full-stack target and it is interactive (-it), --privileged, and hard-blocked on a host `sudo modprobe gpio-mockup` (Makefile:97-100,122) plus /dev/video0 (114), so it cannot run in CI; the container is not booted with systemd (testenv/Dockerfile:112 CMD /bin/bash, systemd-tmpfiles hook nulled at 3-4), so no unit can be started; openssh is NOT in the pacman list (Dockerfile:10-79), so there is no sshd and no ssh-keygen to accept or refuse anything — add openssh and rebuild with `make testenv NC=1` if you want R4.3 exercised; /etc/init.d and /etc/glinet do not exist, so set_firewall_config returns an error unless you stub them. openssl IS present (Dockerfile:14-15), so the 3b option-2 ES256 path is testable as-is. Write the integration test as pytest inside make tox, not as a make run scenario. Record in docs/lean.md: the real /etc/kvmd/main.yaml from an RM1PE, `ss -tulpn` before and after (R5.12), the exact init.d script names to mask (R5.13/section 5 — do not guess), whether /etc/kvmd/nginx/ssl is a symlink into /etc/kvmd/user/ssl, whether ssh-keygen exists on the unit, the S99firewall whitelist semantics, and the _check_exe_path race analysis (R5.3).

## Dangling references

- kvmd/apps/kvmd/server.py:84 — from .api.twofa import TwoFaApi (delete)
- kvmd/apps/kvmd/server.py:85 — from .api.astrowarp import AstrowarpApi (delete)
- kvmd/apps/kvmd/server.py:87 — from .api.turn import TurnApi (delete)
- kvmd/apps/kvmd/server.py:88 — from .api.repeater import RepeaterApi (delete)
- kvmd/apps/kvmd/server.py:89 — from .api.modem import ModemApi (delete)
- kvmd/apps/kvmd/server.py:90 — from .api.ap import ApApi (delete)
- kvmd/apps/kvmd/server.py:92 — from .api.tailscale import TailscaleApi (delete)
- kvmd/apps/kvmd/server.py:93 — from .api.netbird import NetbirdApi (delete)
- kvmd/apps/kvmd/server.py:94 — from .api.cloudflare import CloudflareApi (delete)
- kvmd/apps/kvmd/server.py:95 — from .api.zerotier import ZerotierApi (delete)
- kvmd/apps/kvmd/server.py:109 — from .api.custom_screen import CustomScreenApi (delete). KEEP 86 fingerbot, 91 wol, 96-108, 110-112 (112 is McpApi).
- kvmd/apps/kvmd/server.py:174 — __EV_REPEATER_STATE = "repeater" (delete)
- kvmd/apps/kvmd/server.py:175 — __EV_MODEMO_STATE = "modem" (note the typo MODEMO; grep for it) (delete)
- kvmd/apps/kvmd/server.py:176 — __EV_AP_STATE = "ap" (delete)
- kvmd/apps/kvmd/server.py:177 — __EV_TURN_STATE = "turn" (delete). Nothing in web/ consumes these event names.
- kvmd/apps/kvmd/server.py:216 — self.__turn_api = TurnApi() (delete)
- kvmd/apps/kvmd/server.py:217 — self.__repeater_api = RepeaterApi() (delete)
- kvmd/apps/kvmd/server.py:218 — self.__modem_api = ModemApi() (delete)
- kvmd/apps/kvmd/server.py:219 — self.__ap_api = ApApi() (delete)
- kvmd/apps/kvmd/server.py:220 — self.__custom_screen_api = CustomScreenApi() (delete). KEEP 214 fingerbot, 215 serial, 221 recorder, 222 hid.
- kvmd/apps/kvmd/server.py:227 — TwoFaApi(), in __apis (delete)
- kvmd/apps/kvmd/server.py:228 — AstrowarpApi(), in __apis (delete)
- kvmd/apps/kvmd/server.py:231 — self.__repeater_api, in __apis (delete)
- kvmd/apps/kvmd/server.py:232 — self.__modem_api, in __apis (delete)
- kvmd/apps/kvmd/server.py:233 — self.__ap_api, in __apis (delete)
- kvmd/apps/kvmd/server.py:234 — self.__custom_screen_api, in __apis (delete)
- kvmd/apps/kvmd/server.py:235 — TailscaleApi(), in __apis (delete)
- kvmd/apps/kvmd/server.py:236 — NetbirdApi(), in __apis (delete)
- kvmd/apps/kvmd/server.py:237 — CloudflareApi(), in __apis (delete)
- kvmd/apps/kvmd/server.py:238 — ZerotierApi(), in __apis (delete)
- kvmd/apps/kvmd/server.py:239 — self.__turn_api, in __apis (delete). KEEP 229 fingerbot, 230 WolApi(). Consumed at server.py:632 self._add_exposed(*self.__apis).
- kvmd/apps/kvmd/server.py:275 — _Subsystem.make(self.__repeater_api, "Repeater", self.__EV_REPEATER_STATE) (delete)
- kvmd/apps/kvmd/server.py:276 — _Subsystem.make(self.__modem_api, "Modem", self.__EV_MODEMO_STATE) (delete)
- kvmd/apps/kvmd/server.py:277 — _Subsystem.make(self.__ap_api, "Ap", self.__EV_AP_STATE) (delete)
- kvmd/apps/kvmd/server.py:278 — _Subsystem.make(self.__turn_api, "turn", self.__EV_TURN_STATE) (delete). Leaving these while deleting 216-220 raises AssertionError at construction via _Subsystem.__post_init__ (server.py:142-144), not a soft failure. __subsystems is walked at 569, 612, 623, 649.
- kvmd/apps/kvmd/api/netbird.py:43 — from .netbird_daemon import NetbirdDaemonClient, NetbirdDaemonUnavailableError. The only importer of netbird_daemon.py; both files go together.
- kvmd/apps/kvmd/api/common.py — MUST NOT be deleted with the cloud cluster. Four of its importers are doomed (tailscale.py:42, zerotier.py:38, netbird.py:42, cloudflare.py:34) but wol.py:38 needs make_device_name_from_mac/run_process/valid_mac and api/mcp.py:282-283 needs read_json_file/valid_mac. Only is_process_running, is_process_running_by_name, run_command and update_json_file become dead; read_json_file does NOT.
- kvmd/apps/kvmd/auth.py:230 — SIGNATURE NOTE, not a deletion. `login()` is `async def login(self, user: str, passwd: str, expire: int, client_ip: str = 'unknown') -> tuple[str | None, int]`. Two departures from upstream that every auth call site must honour: `expire` is REQUIRED and positional (asserted `>= 0`; 0 means "infinite session, apply the global expire from the constructor", auth.py:293-300), and the return is `(token, failed_since_last_success)`, NOT a bare token — the failure path returns `(None, 0)` and the success path `(token, count)` after consuming the counter (auth.py:251-264, 277). Code that writes `token = await manager.login(...)` gets a tuple and fails later, at `check()`, not at the call. Verified at 3e8dd23 while repairing testenv/tests/apps/kvmd/test_auth.py, whose ten call sites all predate both changes. Step 11's new `login_verified()` must mirror this return shape or the UI's failed-count stops resetting. Note also that `login()` can RAISE RateLimitError before authorize() is ever reached (auth.py:237-245), so a caller that only handles a None token is not handling every failure.
- kvmd/apps/kvmd/auth.py:31 — import pyotp, orphaned once auth.py:206-215 goes
- kvmd/apps/kvmd/auth.py:111 — totp_secret_path: str (required param, no default)
- kvmd/apps/kvmd/auth.py:157 — self.__totp_secret_path = totp_secret_path
- kvmd/apps/kvmd/auth.py:206-215 — the TOTP enforcement block, the ONLY enforcement point; reached from /auth/login, X-KVMD-Passwd headers and HTTP Basic
- kvmd/apps/kvmd/__init__.py:118 — totp_secret_path=config.auth.totp.secret.file (the only production AuthManager construction, block 104-126)
- kvmd/apps/__init__.py:450-454 — the totp.secret.file schema block; removing it without kvmd/apps/kvmd/__init__.py:118 gives AttributeError on config.auth.totp at startup, and breaks kvmd-totp even if that app is kept
- kvmd/apps/totp/__init__.py:26,27,34-38 — pyotp, qrcode, and the read of config.kvmd.auth.totp.secret.file; a seventh TOTP consumer the design and findings both omit
- setup.py:96 — "kvmd.apps.totp", in packages; setup.py:125 — "kvmd-totp = kvmd.apps.totp:main", in console_scripts. Deleting kvmd/apps/totp without both breaks pip install . (PKGBUILD:161)
- PKGBUILD:56 python-pyotp and :57 python-qrcode (plus testenv/Dockerfile:49-50); pyotp has exactly 3 importers (auth.py:31, api/twofa.py:26, apps/totp/__init__.py:26), qrcode exactly 1
- PKGBUILD:147 (backup= etc/kvmd/totp.secret), PKGBUILD:180 and :195 (the *.secret glob), kvmd.install:21 (chown), configs/kvmd/totp.secret (0-byte, the ONLY *.secret file), and Makefile:88,130,157,180,203 (five &&-chained `cp .../*.secret /etc/kvmd`). Deleting the file without all nine sites makes `make tox` abort before tox runs.
- kvmd/apps/kvmd/auth.py:58-72 (_TwoStepSession), :118 (two_step_login_enabled param), :181-187 (state), :382-392 (accessors), :394-449 (pre_login, incl. the SIGUSR2 killall at 435), :451-491 (complete_two_step_login), :493-498, :500-555 (helpers)
- kvmd/apps/kvmd/auth.py:37 — from ... import tools, orphaned once auth.py:435 goes; auth.py:36 aiotools must STAY (used at auth.py:557)
- kvmd/apps/kvmd/api/auth.py:201-217 (two-step branch in the login handler), :261-285, :287-293, :295-308, :310-323, :325-330, :332-345
- kvmd/apps/kvmd/api/auth.py:53 — from .config_utils import set_yaml_value as _set_yaml_value, orphaned once api/auth.py:344 goes
- kvmd/apps/kvmd/__init__.py:125 — two_step_login_enabled=config.auth.two_step_login.enabled; kvmd/apps/__init__.py:463-465 — the two_step_login schema block
- kvmd/apps/kvmd/api/system.py:163-216 and :243-344 — the two /system/clients routes; their removal orphans SystemApi's ctor kwargs at system.py:67-69/72-74 (readers only at 167,173,247,270,294,296,312,339) and the arguments at server.py:240-244
- kvmd/apps/kvmd/api/system.py:824-827 and :952-955 — the two gui_*_param delegates
- kvmd/apps/kvmd/api/upgrade.py:702-708 — GET /upgrade/gui_compare, a gl_kvm_gui allow-path in a KEPT module and the tree's only multi-line @exposed_http
- kvmd/apps/kvmd/server.py:662-663 and :670-671 — the two `killall -SIGUSR1 gl_kvm_gui` calls in _on_ws_opened/_on_ws_closed; removing both orphans `from ... import tools` at server.py:45 (verified: its only uses are 663 and 671). server.py:43 aiotools must STAY.
- testenv/tests/apps/kvmd/test_auth.py:72 and :203 — totp_secret_path= kwargs; also :42-44 (HttpExposed with 4 of 6 args) and :61-73/:192-204 (stale internal_*/external_*/force_internal_users kwargs, missing expire/usc_users/usc_groups). These fail TODAY, before any edit.
- web/login/index.pug:38-40, web/login/index.html:75-80, web/share/js/login/main.js:43,61,97,103, web/share/css/login/login.css:53-58 — the 2FA field. Atomically coupled to auth.py:206-215; changing one side alone corrupts password auth.
- /etc/kvmd/user/tailscale.json (tailscale.py:56), zerotier.json + zerotier/ (zerotier.py:44,141), netbird.json (netbird.py:51), cloudflare.json (cloudflare.py:40) — on-device files orphaned by the strip; the post-apply script should remove them alongside the daemon masking.

## Open decisions

### Strip the frozen 4.82 base, or rebase the security-critical files toward 4.213?

**DECIDED, as two separate calls with different timing:**

- **auth.py rebase — DEFERRED, re-measure after steps 4/5/10.** Not judged at 568 diff lines, because most of that excess is exactly what those steps delete: TOTP, the two-step state machine, and the rate-limit/lockout subsystem. Measuring divergence before removing code the plan already commits to removing would decide the question against a number that is about to be wrong. Re-run the diff once 4, 5 and 10 have landed, and decide then.
- **htserver.py rebase — OPTIONAL, low-diff, DEFERRED.** 136 diff lines against upstream, so it is rebaseable early and cheaply. Not urgent: the reason to want it was the socket-peer resolver, and the fork already has that resolver — as of this branch the authorisation decisions use it (see the client-identity fix), so the rebase now buys upstream's other fixes rather than any specific one this project needs.

The strategic case below stands regardless and should be read before step 3 goes further, because the two paths differ in what they leave behind.

The fork's base is kvmd 4.82 (kvmd/__init__.py:23); upstream is 4.213. That is ~131 releases of fixes to auth.py, htserver.py, validators/, the MSD and HID plugins and the streamer client that this tree does not have and, on the evidence, will never receive — docs/audit.md establishes GL patches userland CVEs on a normal cadence while leaving the forked core frozen, and live devices are reported still on 4.82. So patching the frozen fork is not standing still: every upstream release makes the gap wider, and the strip as written inherits that gap permanently.

The measured case for rebasing the shared files specifically, taken against pikvm/kvmd @ 15bccd5:

- htserver.py — upstream 541 lines, fork 569, **136 diff lines**. This is nearly rebasable as-is, and it is where the correct socket-peer resolver lives. Rebasing it plus re-pointing _get_client_ip closes R5.1 by deletion rather than by writing new security code.
- auth.py — upstream 322, fork 764, 568 diff lines. Most of the excess IS what steps 4, 5 and 10 already remove: TOTP, two-step, and the rate-limit/lockout subsystem. Strip those first and what remains should be much closer to upstream than 568 lines suggests, at which point rebasing becomes tractable rather than a rewrite. Do the strip steps first, then measure again.
- Keep GL's hardware-specific code (glatx, the RKNN OCR path, switch/sysfs_device.py, the otg plugins' device handling) on the fork side regardless. Nothing upstream serves an RM1PE.

Do NOT read this as "abandon the plan". Steps 1, 2, 4, 5, 6 and 10 all reduce the diff against upstream, so they are the same work either way. What changes is the endpoint: patch-in-place leaves a permanently divergent 4.82, while rebase-forward converges the security-critical files onto something maintained.

### Adopt from upstream rather than inventing — four components confirmed present at 15bccd5

Verified by inspection of a real upstream clone. Each of these is a better starting point than the corresponding item elsewhere in this plan.

- **plugins/auth/onetime.py** — exists upstream, absent from the fork (fork has forbidden, htpasswd, http, ldap, pam, radius). A one-time auth primitive is exactly the base for the OTP / boot-unlock work; do not invent one.
- **kvmd/nbd/** — an entire subsystem upstream (controller, device, link, process, types) with **nbd/remotes/{http,sftp,smb}.py**, and completely absent from the fork. This is upstream's mature answer to mounting remote media, and it is the right replacement for the fork's POST /msd/write_remote (api/msd.py:248), which is the route behind the storage finding class in docs/audit.md.
- **apps/kvmd/api/redfish/** — a package upstream (__init__, atx, msd, root) against the fork's single api/redfish.py. Per the Redfish open decision above, the fork's version is worth keeping; upstream's is the better base for real BMC interop.
- **plugins/msd/otg/fs.py** — 85 lines upstream, and the fork simply does not have the file (fork ships __init__, drive, storage; upstream ships those plus fs). Diff the three shared files and account for the missing fourth before trusting the fork's MSD path. Note also that upstream has no apps/kvmd/streamer.py — it lives at clients/streamer.py and api/streamer.py — so any streamer comparison must be done against those paths rather than by filename.

### The lockout subsystem: repair R5.2/R5.8, or delete toward upstream?

**DECIDED: delete it.** And it is the single biggest lever on the auth.py rebase question below, which is why the two are decided together.

Measured at the end of step 3. The subsystem is auth.py:596-805 — **210 lines**, the whole tail of the class — plus its two routes in api/auth.py. Upstream `pikvm/kvmd` contains **zero** occurrences of rate_limit, lockout or unlock_client in its auth.py: this is not a feature the fork changed, it is a feature the fork invented.

The case for deleting rather than repairing:

- Repairing means deleting the `hash(client_ip) % 100 == 0` sampling (auth.py:252 and :417 — note :417 is inside pre_login, which step 5 deletes wholesale, so do not count that one as done by step 5 alone) AND removing the two routes that let any caller inspect and clear any address's lockout (api/auth.py:360, :379). After all that you still own a bespoke lockout with no upstream counterpart to track, in the file you are trying to converge.
- Deleting removes 210 of the roughly 416 deletable lines in auth.py — over half — and closes R5.2 and R5.8 by construction rather than by patch.
- The client-identity fix earlier on this branch made the identity real, which was the precondition for the limiter *working*. That is not the same as being worth keeping. It remains an attacker primitive by design (a route that unlocks any named address) on a device that belongs on a management VLAN behind certificate-only SSH.

**State the counter-argument honestly:** a lockout does defend against online password guessing, and this device's admin password is stored with apr1/MD5 (docs/audit.md, HIGH), so a guessed or cracked password is worth real money to an attacker. If rate limiting is wanted, put it in nginx with `limit_req` — one location block, no in-daemon state, and no route that hands an attacker a lock-and-unlock primitive. Do not rebuild it in Python.

### MEASURED: auth.py after steps 4, 5 and the lockout deletion

Steps 4, 5 and the lockout deletion have now run. The measurement, against `pikvm/kvmd` @ `15bccd5`:

| | before | after |
|---|---:|---:|
| fork auth.py | 804 lines | **361 lines** |
| upstream auth.py | 322 | 322 |
| size gap | 482 | **39** |
| diff lines | 608 | **199** |
| diff hunks | — | **10** |

The projection said ~388 lines and a ~66-line gap; the actual is 361 and 39. Under the ≲100 criterion, **the recommendation is to rebase.** The divergence is also concentrated rather than scattered — ten hunks, not a hundred.

What remains fork-only in auth.py is six things, and only three are real product need:

- `_get_client_ip`, `__is_trusted_peer`, `__get_peer_ip` — the socket-peer identity fix. Its only surviving consumer is `/same_check`'s local-network gate. If `same_check` is rebuilt per its own open decision, these move there and auth.py loses them entirely.
- `login()` returning `(token, failed_since_last_success)` plus `__consume_failed_since_last_success` — a real GL product feature (the UI shows failed attempts since last success). Genuine delta, keep.
- `refresh_token_expiry` — **drop this one in the rebase.** Upstream solves the same concern better with `start_ws_session` / `stop_ws_session` / `__renew_ws_session`, called from its own server.py. Re-applying the fork's version would keep the worse of two designs.

What the rebase would INHERIT, beyond 131 releases of unnamed fixes: upstream's WS session lifecycle, `sysprep()`, and config-driven construction via `yamlconf.Section`.

### SUPERSEDED — TOTP stays removed. Do NOT restore it.

**This overrides the "TOTP returns with the rebase" reasoning below and any handoff note saying the same.** That reasoning was conditional on a rebase happening: a rebase would have re-imported upstream's TOTP, so removing it again would have been a patch to re-apply on every future rebase, and letting it come back was the cheaper option. The scope decision was a BEHAVIOUR-PORT instead. There is no future rebase to re-apply against, so the standing-patch cost is zero and the only argument for restoring TOTP is gone with it.

Concretely: do not restore `pyotp`, `qrcode`, `configs/kvmd/totp.secret`, `kvmd/apps/totp/`, the `#code-input` field, or the enforcement block. Step 4 stands.

Interim auth is therefore **password-only**, defended by network isolation and (still to be added) `nginx limit_req`, until WebAuthn lands in steps 11 and 12. A future reader finding TOTP absent should NOT "fix" it by restoring it — that reopens exactly the divergence this note settles.

### CORRECTION: step 4 removed UPSTREAM code, not fork cruft

This matters for the rebase and the plan is wrong about it. Upstream 4.213 has TOTP: the same enforcement block with the same six-character slice (`auth.py:137-142`), the same `kvmd-totp` CLI (`kvmd/apps/totp/`), and the same `#code-input` field in `web/login/index.{pug,html}`. The fork INHERITED all of it. The fork's own addition was only `api/twofa.py`, the six routes, which upstream has no counterpart for and which step 3 removed as module 3.

So step 4 was a product decision — this project replaces TOTP with WebAuthn in steps 11 and 12 — and not a debloat. It **increased** divergence from upstream. Two consequences:

1. The plan's strategic argument that "steps 1, 2, 4, 5, 6 and 10 all reduce the diff against upstream, so they are the same work either way" is wrong for step 4. It is the same work only if the WebAuthn replacement actually lands.
2. A rebase onto 4.213 brings TOTP back, and removing it becomes a permanent fork delta to re-apply on every future rebase. Budget for that, or reconsider whether removing it was worth it given upstream maintains it and WebAuthn is not written yet.

### The other two shared files, measured at the same point

- `htserver.py` — upstream 541, fork 569, **136 diff lines**. Unchanged by this work and still the cheapest rebase available.
- `api/auth.py` — upstream 150, fork 290, **214 diff lines**. Now the LARGEST remaining divergence in the auth stack, having overtaken auth.py. It still holds `/same_check`, the query-token acceptance (R5.9) and the header-parsing call sites. Whatever is decided for auth.py, this file needs its own pass.

### MEASURED: api/auth.py is contract-CLEAN, but a rebase still buys almost nothing

Measured, no edits. Unlike `auth.py`, upstream's `api/auth.py` is rebasable in principle: it imports nothing plugin-related — no `Section`, no `get_auth_service_class`, no `BasePlugin` — and every `AuthManager` method it calls (`authorize`, `check`, `check_unix_credentials`, `is_auth_enabled`, `is_auth_required`, `login`, `logout`) already exists in the fork's ported manager. So the contract blocker that stopped `auth.py` does not apply here.

The headline number overstates the divergence badly. 214 diff lines, but only **5 hunks**, and a large share is one cosmetic rename: upstream calls the parameter `auth`, the fork calls it `auth_manager`, in seven function signatures. The genuine fork-only surface is:

| fork-only | disposition |
|---|---|
| `_check_exe_path` | **KEEP** — DECIDED, survives for beacon reuse |
| `_is_local_network` + `GET /same_check` | **REBUILD** on the socket peer, do not delete |
| `_check_query_token` | **DELETE** — this is R5.9 |
| `_check_header_token` | keep; it is upstream's `_check_token` split in two, and the header half is legitimate |
| User-Agent parsing / device+browser logging | keep, GL product feature |

And upstream-only is almost nothing the fork wants: an `allow_redirects` allowlist in the `AuthApi` constructor, which nobody has asked for.

**Recommendation: behaviour-port again, not a rebase.** Rebasing means taking upstream's 150 lines and re-applying roughly 50 lines of kept deltas to get back to where we are, in exchange for a redirect feature and a parameter rename. Porting the three real improvements in is four edits.

#### R5.9 — the stream path does NOT need a query token, and upstream already shows why

Three sites, re-derived: `api/auth.py:121` (`_check_query_token`), `api/auth.py:229` (logout), `server.py:521` (the WS handshake).

The WS site looked like the hard one — a browser opening a WebSocket cannot set headers, so the token had to travel somehow. Upstream's answer needs no ticket at all: `set_request_auth_info(req, info, token="")` stashes the token on the request object during the auth check it is already doing (`htserver.py:282-287`), and `_get_request_auth_token(req)` reads it back when the session is built (`htserver.py:424`, `WsSession(wsr, _get_request_auth_token(req), kwargs)`). The server never needs the client to re-send in the URL, because it already authenticated that request and knows the token. The fork has none of this plumbing (`_REQUEST_AUTH_TOKEN` does not exist in its `htserver.py`) — porting it is about six lines and no contract.

So: **delete all three sites.** No single-use stream ticket, no short TTL to manage. That also removes the reason `server.py:521` reads the query at all, and it composes with the WS-session lifecycle just ported, which needs the same token.

#### Item 3 — header-derived authorisation: confirmed gone

Six header reads remain in `api/auth.py` and none is header-derived identity:

- `:69, :72` `X-KVMD-User` / `X-KVMD-Passwd` — a credential path, and upstream has it too (`api/auth.py:51, 54`)
- `:93` `Authorization` — HTTP Basic, upstream has it
- `:108, :228` `Token` — a credential
- `:204` `User-Agent` — logging only

The authorisation-from-a-header pattern the audit flagged is gone: `_get_client_ip` reads the socket peer, and its only consumer is `same_check`'s gate, which is what the rebuild moves. Any future header-derived authz is a regression.

### BLOCKER: the auth.py rebase is not isolatable — the 39-line measurement measured the wrong thing

Found on starting Task 1, before any edit. The 39-line / 10-hunk figure for `auth.py` is correct **as a file comparison** and misleading **as a rebase estimate**, because upstream's `auth.py` cannot be dropped into this tree at all. Line 102 and 111 of upstream's `auth.py` construct the auth services like this:

    self.__int_service = get_auth_service_class(int_c.type)(int_c)

Upstream passes a `yamlconf.Section`. The fork passes `**kwargs`. That is not a difference inside `auth.py`; it is a **plugin-construction contract** that upstream changed at its root: `BasePlugin.__init__` went from `(self, **_: Any)` to `(self, c: Section)` (`plugins/__init__.py:36` in both trees). Upstream's `auth.py` therefore requires upstream's plugins, and upstream's plugins require upstream's `BasePlugin`, which every other plugin family inherits.

The real scopes, measured against `15bccd5`:

| scope | files | diff lines | also needs |
|---|---:|---:|---|
| `auth.py` alone | 1 | 199 | **does not work** — calls a contract the fork lacks |
| auth family only | 7 | **401** | config schema reshape (`internal`/`external` → Section), `apps/kvmd/__init__.py:111-116`, plugin tests, `test_auth.py` |
| full contract | ~37 | 401 + the rest | `BasePlugin`, all 5 plugin families (auth 7, atx 4, hid 3, msd 2, ugpio 19), and the `**kwargs` construction at `apps/kvmd/__init__.py:85, 141, 142` |

And most of the auth-family divergence is in backends this device never loads. The default internal service is `htpasswd` (`apps/__init__.py:437`), and `htpasswd.py` is only **16** diff lines. The other 151 lines are `http.py` (74), `ldap.py` (46) and `radius.py` (31) — upstream feature work on backends an RM1PE does not use.

**Recommendation: port upstream's auth.py BEHAVIOUR into the fork's auth.py, keeping the fork's plugin contract.** That captures what the rebase was actually for — the WS-session lifecycle (`start_ws_session` / `stop_ws_session` / `__renew_ws_session` with the `extend` flag and `_Session.expire_req` / `ws_started`), `sysprep()`, and the session-expiry handling — in one file, without reshaping the config schema or migrating five auth backends. It leaves the full contract migration exactly as available as it is today, and it does not pretend that "131 releases of auth hardening" lands in `auth.py`: for a device on htpasswd, most of it lands in backends that are dead weight here.

Do NOT proceed with either rebase scope without an explicit decision. The approved decision was made on the isolated-file number, and none of the three options above is "one commit".

### Does auth.py get rebased onto 4.213, or patched in place?

**STILL DEFERRED, and the deferral condition has NOT been met.** Steps 4, 5 and 10 have not run — only step 3 (the strip) and the client-identity part of step 10 are done — so the honest answer is that there is nothing new to measure yet. What has changed is that the projection is now quantified rather than guessed:

| | lines | vs upstream 322 |
|---|---:|---|
| auth.py today | 804 | 608 diff lines |
| step 4 removes (TOTP) | ~13 | |
| step 5 removes (two-step state machine) | ~193 | |
| deleting the lockout subsystem (above) | 210 | |
| **projected after all three** | **~388** | **~66 lines of size gap** |

That is the number the decision actually turns on, and it moves the answer. At 608 diff lines a rebase is a rewrite; at a ~66-line gap it is a merge. So: **run steps 4 and 5 and delete the lockout subsystem, then re-measure and decide.** Do not decide it before, and do not treat the projection above as the measurement — it assumes the plan's own line ranges and none of those deletions have been performed.

### Is the executable-path primitive stripped, or hardened and reused for the beacon?

**Recommendation:** Reuse it. It is the only local-caller authentication the fork has that actually works, and the beacon needs exactly that. DECIDED: the primitive SURVIVES the strip deliberately. htserver.get_request_exe_path, htserver.get_request_unix_credentials and api/auth._check_exe_path are KEEPS, and all three now carry DO-NOT-REMOVE comments pointing here, because after steps 3, 5 and 6 they have one caller left and will otherwise read as dead code to whoever runs the lint pass.

Step 6 removes the gl_kvm_gui allow-paths, and steps 3 and 5 remove 26 of the 31 routes that use them, so the mechanism itself ends up with one surviving user (server.py:578, gl-pion) and looks like dead weight. It is not. docs/audit.md section 3b establishes that it holds against spoofing: SO_PEERCRED (htserver.py:331) fails on a TCP socket, and an HTTP request arriving through nginx resolves to nginx's own binary because nginx proxies over unix:/run/kvmd/kvmd.sock, so both paths fail closed. That is a working answer to "is this caller a specific local program", which design section 7 needs and which the usc/uid path cannot give as shipped (the default usc group kvmd-selfauth is created nowhere, apps/__init__.py:436 and configs/os/sysusers.conf).

Two things to harden if it is reused. It authenticates a PATH, not a principal, so its security is the filesystem ownership of the allowlisted binary — the beacon's own path must be root-owned and not on any writable mount. And /run/kvmd/kvmd.sock is 0660 (apps/__init__.py:422-424), so group membership is the real outer gate and the exe check is the only thing between "in the group" and "authenticated"; tighten the group rather than relying on the allowlist alone. Also note _check_exe_path returns True with no credential at all (api/auth.py:146-159), so any route it gates is fully authenticated by it — that is a property to use deliberately, not to inherit by accident.

### Is /same_check deleted, or hardened and reused as the local-identity check?

**Recommendation:** Do not simply delete it — the shape is useful, the gate is not.

As shipped it is a finding (docs/audit.md, MEDIUM): auth_required=False, and its only gate is _is_local_network() over the header-derived client IP, so X-Real-IP satisfies it from anywhere. But "does this caller already know the device's MAC" is a reasonable pre-enrolment liveness check for a launcher or a beacon that has the device inventory, and it is the one route designed for a caller that has no credentials yet. Rebuild it on the socket peer (D-009 / R5.1) rather than a header, or move it behind the exe-path primitive above, and it becomes usable. Deleting it leaves the pre-enrolment path with nothing.

Note it also reaches into the auth manager's private _get_client_ip from outside the class (api/auth.py:387), so it is a second caller to fix when that signature changes.

### Does the strip delete Redfish, or keep a hardened endpoint?

**Recommendation:** Keep it. It is standards-shaped interop the fork gets right, and the audit's concern about it did not survive investigation.

docs/audit.md section 3b: only GET /redfish/v1 is open, and it returns a static ServiceRoot document. ComputerSystem.Reset, GET /Systems, GET /Systems/0 and PATCH /Systems/0 all carry no auth_required and therefore default to True. There is no unauthenticated power control, so R5.11 is narrower than it looks — the item is "should the service root be open at all", not "power control is exposed". A Redfish endpoint means standard out-of-band tooling can drive the device without anything KVMD-specific, which is worth more than the few lines it costs. If the open root is unwanted, closing that one decorator is the whole change.

### Does the strip land on top of the MCP commit (653f840), or does the MCP module get rebased onto the stripped tree?

**Recommendation:** Strip on top of 653f840, and treat api/mcp.py as a first-class KEEP throughout.

mcp.py already couples to the code you are about to change: it imports read_json_file and valid_mac from api/common.py (mcp.py:282-283), which changes the 'dead helpers' analysis, and its 1418 lines register at server.py:259 inside the same __apis list you are editing. Rebasing later means redoing the server.py surgery and re-verifying the common.py dependency. Whichever you choose, decide it before step 3 — the recon's server.py line numbers are only valid on the tag, not on HEAD.

### Delete configs/kvmd/totp.secret, or keep the 0-byte file?

**Recommendation:** Keep it, and delete only the code and the schema.

It is the only file matching *.secret and that glob appears in nine places: PKGBUILD:180, PKGBUILD:195, and five &&-chained Makefile recipes (88, 130, 157, 180, 203) plus PKGBUILD:147 and kvmd.install:21. An unmatched glob makes cp exit non-zero and aborts `make tox` before tox starts — a packaging failure with nothing to do with the Python strip. A 0-byte file with no reader costs nothing; revisit it in a dedicated packaging commit if at all.

### Fix GL.iNet's rate-limit / lockout / unlock subsystem (R5.1, R5.2, R5.8), or delete it?

**Recommendation:** Delete it and rebuild nothing.

Findings 8 establishes that upstream pikvm/kvmd has no rate limiting, lockout or unlock machinery at all — the whole subsystem (auth.py:594-764, api/auth.py:347-382) is a fork invention. It is bypassable by construction (auth.py:248 samples hash(client_ip) % 100 == 0, and client_ip is an attacker-chosen header per auth.py:594) and doubles as an attacker primitive (api/auth.py:350 inspects any address, :366-377 unlocks any address). On a management VLAN behind WebAuthn and cert-only SSH it earns little. Deleting removes ~170 lines and returns auth.py toward upstream; fixing it means reimplementing socket-peer identity for a feature you do not need. If kept, it MUST be rebuilt on the socket peer per D-009.

### Does the beacon drive kvmd's HTTP API, or write files and run init scripts directly as root?

**Recommendation:** Direct files and init scripts for hostname, firewall, TLS and NTP; use the API only for network.

D-002 requires the beacon to work when kvmd is broken, and the HTTP path is dead in exactly that case. Every route except network is pure file-write plus init script and is exactly reproducible by root: hostname = /etc/hostname + `hostname <n>` + `/usr/bin/gl_mdns system restart` (system.py:1596-1611); firewall = /etc/glinet/firewall.conf + /etc/init.d/S99firewall (1533-1542); tls = /etc/kvmd/user/ssl/server.{crt,key} + /etc/init.d/S99kvmd-nginx restart (2222-2245); ntp = /etc/ntp.conf and /etc/kvmd/user/ntp.conf + /etc/init.d/S49ntp restart (2540-2555). Network is the exception: the durable state lives in connman, not a file — /etc/kvmd/user/network.json (written at system.py:1144-1152) has NO reader in the repo, so writing it applies nothing. Using the API would also require the beacon to hold the admin password at the moment enrolment is randomising it, and the only password-free local path (usc uid auth over /run/kvmd/kvmd.sock) is inert as shipped: the default usc group is kvmd-selfauth (apps/__init__.py:436) and no such user or group is created anywhere (configs/os/sysusers.conf).

### Where does the beacon read its configuration from?

**Recommendation:** Its own JSON/YAML under /etc/kvmd/user/, with defaults compiled into kvmd/apps/beacon/ — not configs/kvmd/beacon.yaml.

Two independent reasons a beacon.yaml does not work. apply_to_glkvm.sh copies only kvmd/*, so configs/ never reaches the device. And even installed to /etc/kvmd/beacon.yaml nothing would read it: kvmd loads exactly one entry file, /etc/kvmd/main.yaml (apps/__init__.py:136, _init_config at 186-217), and pulls in others only via explicit !include tags — and the device's main.yaml comes from the GL.iNet firmware image, not this repo (configs/kvmd/main/ holds only PiKVM rpi/zero2w platform variants, no rm1pe). Worse, kvmd/yamlconf/loader.py:79 silently skips a missing !include and :82-86 only warns on a parse error, so a beacon.yaml that fails to deploy yields a running daemon with default settings and no visible error — the exact failure mode an enrolment path cannot afford.

### Does the login page keep the username and password rows?

**Recommendation:** Keep them. 'No username field' in design 3b means the WebAuthn ceremony needs no username, not that the fields are deleted.

Design 3.4 keeps the password as break-glass from OpenBao, and section 8 says the first boot before enrolment has a factory password and no WebAuthn credentials at all. Deleting web/login/index.pug:32-37 locks the operator out of an unenrolled device. Settle this explicitly or a build agent will read section 3b literally.

### How is the ticket's ed25519 signature verified on the device — ssh-keygen -Y verify or openssl?

**Recommendation:** openssl, unless ssh-keygen is confirmed on a real unit first.

Design section 4 line 269 asserts ssh-keygen is present 'because sshd is'. Nothing in the repo shows that: `ssh-keygen` appears exactly once, at scripts/kvmd-bootconfig:112, inside a PiKVM-only first-boot block that exits at kvmd-bootconfig:39-41 on any non-PiKVM box, is installed only by PKGBUILD:163, and is driven by a systemd unit the device does not run. sshd's presence proves nothing about a stripped openssh build including ssh-keygen, and -Y verify needs a fairly modern OpenSSH. openssl is proven by GL.iNet's own runtime code (system.py:1744,1753,1903,1934,1943,1979,1987,2024,2033). The testenv image has openssl but NOT openssh, so the openssl path is also the only one testable today.

### What does the ticket's firewall block actually look like?

**Recommendation:** Do not finalise the ticket schema until S99firewall's semantics are read off a device; the design's {"allow": [...]} shape does not exist.

POST /system/set_firewall_config takes {"enable", "enable_v6", "whitelist": {<iface>: [...]}} and HARD-REQUIRES a wwan0 key when enable is true and wwan0_v6 when enable_v6 is true (system.py:1515-1524) — wwan0 is the cellular interface the RM1PE does not have. There is no flat allow list and no eth0 key. What the whitelist means is implemented entirely in /etc/init.d/S99firewall, which is not in this repo, so nothing here shows this route can restrict inbound access on eth0 by source address at all. Design section 2's central claim about the firewall is unverified.

### Keep GET /system/ssl_cert, which hands the TLS private key to any authenticated caller?

**Recommendation:** Delete or restrict it in the same pass as R4.2.

system.py:2074-2113 returns {"ssl_cert", "ssl_key", "is_default"} — the private key, over the API. The beacon does not need it (it holds the key it generated). This is the same class of hole as the ssh_key routes that R4.2 removes, and the design does not mention it.

## Contradictions with the design

### CLAIM: Implicit throughout the brief and the recon: /home/user/glkvm-lean is a pristine git worktree of gl-inet/glkvm at the fork's 1.10.0 tag.

**Reality:** HEAD is 1.10.0 plus one commit that adds a 1418-line MCP module. Every server.py line number quoted in the reconnaissance is therefore wrong at HEAD — low by 1 below line 112 and low by 2 below line 259. Applying edits by those numbers will corrupt server.py. api/mcp.py is also a new KEEP with its own coupling to api/common.py, which changes the dead-code analysis for that file.

**Evidence:** git log --oneline -2 → 653f840 'kvmd: MCP endpoint for agent-driven console control' on 3e8dd23 '1.10.0'. git diff --stat 3e8dd23 HEAD → kvmd/apps/kvmd/api/mcp.py 1418 insertions, kvmd/apps/kvmd/server.py 2 insertions. Verified at HEAD: import at server.py:112, registration at server.py:259; __EV_ constants at 174-177 not 173-176; __apis doomed entries at 227-239 not 226-238; __subsystems at 275-278 not 273-276; killalls at 663 and 671 not 661 and 669; /hid/ws at 580 not 578. api/mcp.py:282-283 imports read_json_file and valid_mac from api/common.py.

### CLAIM: Design section 4: 'kvmd/apps/kvmd/server.py — remove the ten registrations' and 'kvmd/apps/kvmd/api/*.py — delete the ten modules'.

**Reality:** There are eleven modules (twelve files, counting netbird_daemon.py) and eleven __apis entries, plus 5 attribute assignments, 4 __EV_ constants and 4 __subsystems entries — 35 lines in server.py, not ten. The count 'ten' appears nowhere in the source; the design's own section 1 table lists eleven rows.

**Evidence:** kvmd/apps/kvmd/server.py: eleven imports at 84,85,87,88,89,90,92,93,94,95,109; eleven __apis entries at 227,228,231,232,233,234,235,236,237,238,239; attrs 216-220; constants 174-177; subsystems 275-278.

### CLAIM: Design section 4: 'kvmd/apps/kvmd/server.py ... remove gl_kvm_gui allow-paths'. Design section 1 and findings 3: the GUI allow-paths are in auth.py, system.py and tailscale.py — '8 routes in api/tailscale.py and 4 in api/system.py'.

**Reality:** server.py contains NO allowed_exe_paths for gl_kvm_gui at all — its only exe-path route is /hid/ws for gl-pion, which must be KEPT. What server.py contains is two `killall -SIGUSR1 gl_kvm_gui` calls fired on every websocket open and close. And the allow-path inventory is 32 routes across seven files, not 12 across two: tailscale 8, netbird 7, zerotier 6, auth 5, system 4, upgrade 1, plus the gl-pion keeper. upgrade.py is on the KEEP list, so GET /upgrade/gui_compare survives the strip as an orphan GUI route the design never mentions — and it is the tree's only multi-line @exposed_http, so a grep-based sweep misses it.

**Evidence:** Exhaustive grep -rn 'allowed_exe_paths=\[' kvmd/ --include=*.py: tailscale.py:210,289,320,401,490,525,712,731; netbird.py:204,240,290,308,324,372,459; zerotier.py:215,250,285,361,438,461; api/auth.py:287,295,310,325,332; api/system.py:163,243,824,952; api/upgrade.py:705 (decorator spans 702-708); server.py:580 (/usr/bin/gl-pion). Killalls: server.py:663, server.py:671 (SIGUSR1), auth.py:435 (SIGUSR2) — three, not one.

### CLAIM: Design section 4 and findings 2: removing TOTP means touching auth.py, the config schema in kvmd/apps/__init__.py, and 'the yaml defaults'. Findings 2 enumerates four sites plus api/twofa.py and says revision 3 incorporates it.

**Reality:** There are no yaml defaults to touch, and there are seven consumers, not five. configs/kvmd/auth.yaml is literally `{}`; override.yaml has only a commented vncauth example; configs/kvmd/main/*.yaml are upstream PiKVM platform files with no auth section. A grep of configs/ for totp/two_step/2fa returns nothing. The uncounted consumers are a whole CLI app, kvmd/apps/totp/ (imports pyotp AND qrcode, reads the schema key), wired into setup.py twice, plus PKGBUILD deps, a backup= entry, a kvmd.install chown, a tracked configs/kvmd/totp.secret and testenv/Dockerfile deps. Removing the schema at apps/__init__.py:450-454 without deleting kvmd/apps/totp turns the shipped kvmd-totp binary into a crash-on-start.

**Evidence:** configs/kvmd/auth.yaml is 3 bytes containing `{}`. kvmd/apps/totp/__init__.py:26 import pyotp, :27 import qrcode, :34-38 reads config.kvmd.auth.totp.secret.file. setup.py:96, setup.py:125. PKGBUILD:56,57,147,180,195. kvmd.install:21. configs/kvmd/totp.secret (0 bytes). Makefile:88,130,157,180,203 all glob *.secret in &&-chains.

### CLAIM: Design section 4 folds two-step into a single clause with TOTP: 'remove two_step/totp config options from the schema'.

**Reality:** These are two independent second factors with different owners and different removal work, and treating them as one leaves half behind. TOTP is always on whenever the secret file is non-empty, verified inside authorize(), with no config toggle beyond the path. Two-step is a separate ~175-line state machine in AuthManager with its own schema key (default False), its own wiring, five gl_kvm_gui-gated routes and a write-back that persists into boot.yaml. And removing the GUI does not merely orphan two-step — it makes it a hard dependency: approve/reject/pending are reachable ONLY from gl_kvm_gui, allowed_exe_paths is exclusive, so with the GUI masked a two-step login can never be approved and every login hangs at 'pending' forever.

**Evidence:** TOTP: auth.py:206-215. Two-step: auth.py:58-72, 118, 181-187, 382-392, 394-449, 451-491, 493-498, 500-555; api/auth.py:201-217, 261-285, 287-293, 295-308, 310-323, 325-345 (the write-back at 344); schema at kvmd/apps/__init__.py:463-465 Option(False); wiring at kvmd/apps/kvmd/__init__.py:125. Exclusivity at api/auth.py:152-158.

### CLAIM: Design section 3b: 'Success mints the same session token the password path mints today', and section 4 lists auth.py under removals only.

**Reality:** There is no public way to mint a session token without a password. login() always calls authorize() first, and every primitive is double-underscore name-mangled inside AuthManager, so api/webauthn.py cannot reach any of them. A new public method on AuthManager is mandatory work the design's file list does not budget for. Session expiry also uses time.monotonic(), not wall clock, so a mint that computes its own expire_ts produces sessions that expire immediately or never.

**Evidence:** kvmd/apps/kvmd/auth.py:230 login(), :251 `if (await self.authorize(user, passwd)):`, :286 def __make_new_token, :293 def __make_expire_ts, :159 self.__sessions, :280 def __consume_failed_since_last_success, :314-315 time.monotonic(). The only public mint entry points are login() and complete_two_step_login() (auth.py:451), and the latter is being deleted.

### CLAIM: Design sections 4 and 5, findings 1, and D-003 all refer to scripts/apply_to_glkvm.sh, and section 3.3 says it 'runs as root on the device to install the fork and the beacon service; in the same pass it writes the launcher's public key'. Section 5 says a post-apply script runs after syncing kvmd/.

**Reality:** Wrong path and wrong capability. The file is at the repository ROOT; scripts/ holds only kvmd-bootconfig, kvmd-certbot, kvmd-gencert and two udev helpers, so a patch to scripts/apply_to_glkvm.sh creates a second, never-executed file. It runs on the developer's workstation, not on the device. Its entire body is: check ./kvmd exists, check scp/ssh exist locally, `ssh root@glkvm.local "rm $REMOTE_DIR/* -R"`, `scp -r kvmd/*` back. It installs no service, writes nothing to /etc, deploys neither web/ nor configs/, and has no post-apply hook to run anything after the sync. The pin file, the beacon service, the daemon masking, the web login change and configs/kvmd/beacon.yaml all need transport that does not exist.

**Evidence:** /home/user/glkvm-lean/apply_to_glkvm.sh:1-36 in full — vars at 3-7 (LOCAL_DIR="kvmd", REMOTE_DIR="/usr/lib/python3.12/site-packages/kvmd"), local client check at 14-17, transfer_files at 19-28 (the single scp at 20), the single ssh at 34, the single call at 36. ls scripts/ returns five kvmd-* files.

### CLAIM: Design section 4: 'systemd: kvmd-beacon.service — Before=kvmd.service; Restart=always'. Section 5: 'systemctl mask ...'. Section 3.1: 'a small separate systemd service'.

**Reality:** The RM1PE does not run systemd, and the fork's own source says so in two languages. Every service the GL.iNet code touches is a BusyBox /etc/init.d/S<NN><name> script invoked start|stop|restart, including kvmd's own nginx. A kvmd-beacon.service and `systemctl mask` are both no-ops on the device — and adding configs/os/services/kvmd-beacon.service silently changes the Arch package (PKGBUILD:165 globs that directory) while doing nothing for the RM1PE, so it will look installed in the diff and be absent on the unit.

**Evidence:** kvmd/apps/__init__.py:826 comment '# TODO:没有SYSTEMD,回头改' above a commented-out systemctl call; kvmd/apps/kvmd/info/extras.py:98 '已经确定无法引入systemd'. Real service calls: api/system.py:320-321 (S99gl-pion, S80ttyd), :1540-1542 (S99firewall), :1713 (S99kvmd-nginx), :2555 (S49ntp); astrowarp.py:43,46; tailscale.py:272,303; zerotier.py:123,156; netbird.py:185,218; cloudflare.py:96,127,169; switch/sysfs_device.py:469,483. The only systemctl strings in kvmd/ are help text and a commented-out line.

### CLAIM: Design 3.4: 'Apply hostname + domain via the existing /api/system/set_hostname path'. Design 3.2: network as {"mode":"static","addr":"10.0.0.15/24","gw":...,"dns":[...],"ntp":[...]} via /api/system/set_network_config, and firewall as {"allow":[...]}.

**Reality:** None of the three payload shapes match the real routes. set_hostname takes exactly one query param, `hostname`, and its validator rejects dots — an FQDN cannot be submitted at all, and there is no domain concept anywhere in the API; nothing writes /etc/hosts or a search domain. set_network_config takes QUERY params named mode/ip_address/netmask/gateway/dns_servers, where netmask is a dotted quad not a prefix length and dns_servers is one comma-separated string; there is no ntp field (NTP is a separate route with a JSON body and a list). set_firewall_config takes {"enable","enable_v6","whitelist":{<iface>:[...]}} and hard-requires a wwan0 key — the cellular interface the RM1PE does not have — with no flat allow list and no eth0 key.

**Evidence:** api/system.py:1585 (sole query param), :1635-1649 (regex ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$, max 63, dots rejected); :526-540 (query params), :585-588 (connmanctl config --ipv4 manual <ip> <mask> <gw>), :676-688; :2499-2536 (separate NTP route); :1510-1524 (firewall body keys and the wwan0/wwan0_v6 requirement), :1533-1542.

### CLAIM: Design section 1: 'api/system.py (2,568 lines) stays but loses its GUI param routes and any cloud-config keys; audit it route by route.' Design section 4: 'web/ — login page: security-key button; drop the TOTP step', implying web/ carries the cloud UI.

**Reality:** Both audits are unnecessary and one of them is misleading. system.py has no cloud-config keys and no reference to any of the eleven modules; its only external-daemon coupling is gl_mdns. And web/ contains ZERO references to any doomed module or route — the GL.iNet cloud UI lives in the separate gl_kvm_gui binary, not this repo. The only web/ change the strip forces is the 2FA field, and it must be made in the .pug source AND the generated .html, because `make pug` reverts a lone .html edit and PKGBUILD:171 strips .pug from the package so the .html is what ships.

**Evidence:** grep -niE 'cloud|astrowarp|tailscale|zerotier|netbird|ddns|coturn' api/system.py → only gl_mdns at 1607-1622. grep over web/ excluding .min.js for tailscale|zerotier|netbird|cloudflare|astrowarp|custom_screen|2fa|two_step|totp → exactly two hits, web/login/index.html:76 and web/login/index.pug:39. Makefile:225-234; PKGBUILD:170-171.

### CLAIM: Design sections 4 and 7 assume testenv is a working baseline to regress against, and section 7 asks for a container end-to-end test where 'sshd accepts a cert and refuses a password'.

**Reality:** make tox E=pytest is RED before any change, for a reason the design itself schedules as tidying: kvmd/utils.py:39 calls get_logger in get_model_name's except branch but the module never imports it, so every test that imports anything under kvmd.apps.kvmd dies at collection with NameError. Reproduced verbatim. A second, independent break follows: test_auth.py:42-44 builds HttpExposed with 4 of its 6 fields. And the section 7 integration test cannot be written as described: the container is not booted with systemd, openssh is NOT in the image so there is no sshd or ssh-keygen at all, /etc/init.d and /etc/glinet do not exist, and the only full-stack target (make run) is interactive, --privileged and blocked on a host modprobe, so it cannot run in CI.

**Evidence:** Reproduced: PYTHONPATH=... python3 -m pytest testenv/tests → 'kvmd/utils.py:39: in get_model_name / get_logger(0).warning(...) / E NameError: name get_logger is not defined'. kvmd/utils.py:23-24 imports only sys and types. kvmd/htserver.py:94-100 (6 fields) vs testenv/tests/apps/kvmd/test_auth.py:42-44. testenv/Dockerfile:10-79 (no openssh), :112 (CMD /bin/bash), :3-4; Makefile:97-100,103,105,114,122.

### CLAIM: web-login recon: 'SwitchApi is already commented out of the registration list in the fork, so no /switch routes are served at 1.10.0. A regression test written from the design's keep list will fail.'

**Reality:** Half right, and the reason matters. The inline entry at server.py:255 is commented out, but SwitchApi IS registered conditionally two lines later, and the same pattern applies to the Switch subsystem. The real gate is hardware: Switch is constructed only when get_hw_model() == 'rm4pe'. So on an RM1PE there are no /switch routes (the conclusion holds), but on an rm4pe or in a testenv whose MODEL_PATH says rm4pe there are — a regression test must key on the model, not assume the routes are absent.

**Evidence:** kvmd/apps/kvmd/server.py:255 '# SwitchApi(switch),' but :261-262 'if self.__switch is not None: self.__apis.append(SwitchApi(self.__switch))' and :282-283 the matching subsystem append. kvmd/apps/kvmd/__init__.py:94-101: 'hw_model = get_hw_model(); if hw_model == "rm4pe": switch = Switch(...) else: switch = None'.

### CLAIM: Findings: 'python-cryptography is NOT in the PKGBUILD. openssl IS (PKGBUILD:86,106).' Design section 4 reasons about device dependencies from the PKGBUILD.

**Reality:** The conclusion (use openssl) is right but the reasoning is unsound and should not be reused. PKGBUILD is upstream PiKVM's Arch package for Raspberry Pi — source=pikvm/kvmd/archive/v4.16.tar.gz, raspberrypi-utils in depends, systemd units installed — and is not what builds the RM1PE image. Proof that it cannot even build this tree: setup.py's explicit packages list omits kvmd.apps.kvmd.switch, kvmd.apps.localhid, kvmd.apps.media and kvmd.apps.swctl, all of which exist on disk, and kvmd.apps.kvmd.switch is imported unconditionally — so `pip install .` yields a kvmd that cannot import its own server. openssl's real proof is GL.iNet's own runtime code shelling out to it.

**Evidence:** PKGBUILD:45,142 (pikvm source), :95 raspberrypi-utils, :165 systemd units. setup.py:67-108 vs the on-disk directories kvmd/apps/kvmd/switch, kvmd/apps/localhid, kvmd/apps/media, kvmd/apps/swctl (all present, none listed); kvmd/apps/kvmd/__init__.py:41 'from .switch import Switch'. openssl at api/system.py:1744,1753,1903,1934,1943,1979,1987,2024,2033.

### CLAIM: Design 3.4 and R4.3 assume the beacon can drive the system routes as a local process, and 3.4 has the launcher set the admin password over the API.

**Reality:** Every one of those routes is auth_required=True, and the only password-free local path is inert as shipped: usc uid auth defaults to the group kvmd-selfauth, and no such user or group is created anywhere in the tree. So an API-driven beacon would have to hold the admin password at exactly the moment enrolment replaces it. Separately, POST /init/change_password — the route design 3.4 names for setting the OpenBao password — takes user, old_password and new_password as QUERY parameters, so both passwords land in the access log (kvmd's access_log_format includes %r).

**Evidence:** kvmd/apps/__init__.py:434-437 (usc defaults, groups=["kvmd-selfauth"]); configs/os/sysusers.conf has kvmd, kvmd-pst, kvmd-ipmi, kvmd-vnc, kvmd-nginx, kvmd-janus, kvmd-certbot and no kvmd-selfauth; api/auth.py:134-140 and auth.py:587-589. api/init.py:97-99 req.query.get for all three, with the is_inited guard commented out at 94-95; apps/__init__.py:425 access_log_format.

## Test commands

```sh
make testenv            # build the kvmd-testenv Docker image (needs network: pacman mirror + a git clone of pikvm/ustreamer built WITH_PYTHON=1); also groupadds and generates testenv/.ssl, which `make tox` copies in — a missing testenv/.ssl aborts tox
make tox                # the full gate: builds the image, copies configs into /etc/kvmd, then runs `tox -q -c testenv/tox.ini -p auto` over flake8, pylint, mypy, vulture, pytest, eslint, htmlhint, shellcheck
make tox E=pytest       # pytest only — use this for the step-1 baseline before any strip commit
make tox E=mypy
make tox E=pylint
make tox E=flake8
make tox E=vulture
make tox E=eslint       # web/share/js only; enforces tab indent, double quotes and quote-props:always
make tox E=htmlhint     # covers web/*.html and web/*/*.html, including the hand-edited web/login/index.html and web/kvm/index.html
make tox E=shellcheck   # runs over `kvmd.install scripts/*` ONLY — apply_to_glkvm.sh at the repo root is NOT covered; moving it into scripts/ will surface its `&> /dev/null` bashism (line 14) and SC2181 (line 22)
make tox CMD="testenv/.tox/pytest/bin/py.test -vv testenv/tests/apps/beacon"   # run a subset: tox.ini has no {posargs}, so this is the only way; requires one full `make tox E=pytest` first to build the venv
make pug                # regenerate web/*/index.html from the .pug sources (Makefile:225-234, login at :230); depends on the testenv image. Commit the generated HTML in the same commit as the pug change (R5.15)
make regen              # keymap + pug
PYTHONPATH=/home/user/glkvm-lean:/tmp/claude-0/-home-user-provision/24a544c1-8a4c-5b10-add7-0bdeb822ea7c/scratchpad/stub python3 -m pytest testenv/tests -q   # sandbox fallback when Docker is unavailable; test_http.py will still fail on a missing aiohttp_basicauth, which is a sandbox gap, not a code fault
PYTHONPATH=/home/user/glkvm-lean:/tmp/claude-0/-home-user-provision/24a544c1-8a4c-5b10-add7-0bdeb822ea7c/scratchpad/stub python3 -c 'import kvmd.utils as u; u.MODEL_PATH="/etc/hostname"; import kvmd.apps.kvmd.server; print("server import OK")'   # the fastest possible check that the strip left no dangling import or NameError; run after every step that edits server.py
grep -rn 'gl_kvm_gui' kvmd/ --include=*.py                    # must reduce to the single comment at kvmd/htserver.py:302
grep -rn 'allowed_exe_paths' kvmd/ --include=*.py             # must reduce to exactly one hit: server.py:580 (/usr/bin/gl-pion)
grep -rn 'authorized_keys' . --include=*.py --include=*.js --include=*.pug --include=*.html   # must be empty after R4.2
grep -rn 'ttyd\|webterm' . --include=*.py --include=*.pug --include=*.js | grep -v .min.js   # must be empty after R4.1
grep -rniE 'totp|pyotp|two_step|2fa|code-input' kvmd/ web/ configs/ setup.py PKGBUILD kvmd.install   # must be empty after steps 4 and 5 (modulo a kept configs/kvmd/totp.secret if you take that decision)
grep -rn 'fw.gl-inet.com\|reset_default' kvmd/                # must be empty after R5.14
git diff --stat 3e8dd23 HEAD   # confirm what is actually in the tree before trusting any line number in the reconnaissance
CI equivalent (.github/workflows/tox.yml:16-20): make testenv && make tox CMD="tox -c testenv/tox.ini"
```
