# Corrections found — second documentation pass, 2026-09-10

A review of everything that landed on `claude/repo-status-report-6vi5r1` today,
on the explicit instruction to assume the fast work contains mistakes. It does,
and two of them are in the audit fixes themselves — the same shape as the four
mutation gaps that audit found in code shipped hours earlier.

**Nothing here has been edited in place.** This is a report.

Measured at `1355993` in `glkvm-debloat` and `450ca39` in `kazbek` — the pushed
tip of that branch in each repo. Python environment: **3.11.15**, `pytest 9.1.1`,
`pytest-asyncio 1.4.0`, `pytest-aiohttp 1.1.1`, `pytest-mock 3.15.1`,
`aiohttp-basicauth 1.2.0`, `bcrypt 4.0.1`, `passlib 1.7.4` — the reconstructed
virtualenv, **not** the staged `testenv`, which matters for item 8. Go: **1.24.7**
locally against a workflow pinning **1.24.4**. Named because a missing dependency
presents here as a failure and not as a skip.

Every mutation below was applied to a `git archive` copy in the scratchpad, never
to a live working tree.

---

## The two that are in today's own fixes

### 1. The hash-comparison test closes one truncation length out of five

`252c488` says: *"An audit pass mutated every silent-if-missed check in this
module and found four that leave the suite green… each is now pinned by a test
that goes red under exactly its own mutation."* For three of the four that holds.
For `HashOnlyVerifier.verify` it holds only at the exact length the test searched
for.

Measured — mutate `verifier.py` to `if got[:n] != manifest.payload.sha256[:n]:`
and run `testenv/tests/pluginmgr`:

| n | Result |
|---|---|
| 2 | **1 failed** |
| 4 | 150 passed — silent |
| 8 | 150 passed — silent |
| 16 | 150 passed — silent |
| 32 | 150 passed — silent |

**`n = 8` is named in `252c488`'s own commit message** as a mutation that left
the suite green — *"survives truncation to two hex characters (and to eight)"* —
and it still does. The new test searches for a payload sharing a one-**byte**
digest prefix with the honest one, which pins `[:2]` and nothing longer. That is
not a flaw in the search: four shared hex characters is ~65,000 candidates and
eight is ~4 billion, so a longer search is not available.

`hash-only` is the entire authenticity story at the v1 floor. A comparison that
need only agree on the first four hex characters accepts roughly one forged
payload in 65,000 by chance, and any number of them by construction.

**The fix is to stop searching for payloads and mutate the declared digest
instead.** Take the honest payload; for each of several positions `k` in its hex
digest, build a manifest whose `payload.sha256` differs from the truth only at
`k`, and assert each is refused. A truncated comparison cannot see a difference
past its cut, so high positions redden every truncation length. Drafted and
measured — 10 cases, green unmutated, and red under `n` = 2 (7 failed), 8 (4),
32 (2) and 63 (1). Not landed.

```sh
# reproduce
cd <scratch copy>
python3 - <<'EOF'
p='kvmd/pluginmgr/verifier.py'; s=open(p).read()
s=s.replace('if got != manifest.payload.sha256:','if got[:8] != manifest.payload.sha256[:8]:',1)
open(p,'w').write(s)
EOF
PYTHONPATH=. <venv>/bin/python -m pytest testenv/tests/pluginmgr -q -p no:cacheprovider
```

### 2. `require_entry`'s new test does not close `startswith`

Same commit, same claim. The new test's bundle carries a single member
`evil/plugins/ugpio/acme_relay.py` against a manifest declaring
`plugins/ugpio/acme_relay.py`. Measured:

| Mutation to `require_entry` | Suite | Exploitable as |
|---|---|---|
| `==` → `endswith` | **1 failed** | `evil/plugins/ugpio/acme_relay.py` |
| `==` → `entry in f.path` | **1 failed** | the same member |
| `==` → `startswith` | **150 passed — silent** | `plugins/ugpio/acme_relay.pyzzz`, `…/acme_relay.py.bak` |

The shipped vector cannot separate the third: `evil/…` does not *start* with the
declared path, so `startswith` refuses it and the test passes. Under `startswith`
a bundle whose only member is the declared path plus any suffix satisfies the
check while the declared file is absent from the bundle entirely.

One more vector closes it. Parametrising the same assertion over four members —
`evil/<entry>`, `<entry>zzz`, `<entry>.bak`, and an unrelated sibling — reddens
under all three mutations (1, 2 and 3 failures) and passes unmutated. Measured;
not landed.

---

## `kazbek` CI — three things

### 3. `internal/server/device.go` is gofmt-unformatted, and the new gofmt step cannot see it

`gofmt -l internal/server/device.go` returns the path at HEAD. The diff is struct
field alignment in `type Device struct`.

Bisected:

| Ref | `device.go` |
|---|---|
| `origin/main` | clean |
| `98250c3^` (= `201f9f1`) | clean |
| `98250c3` | clean |
| `8853e50` | clean |
| **`a7b2585`** | **UNFORMATTED** |
| `556f9a7`, `d38f83a`, HEAD | UNFORMATTED |

`a7b2585` ("fix(device): client type is server-side state, not a per-session
device claim") removed `clientInfoMu sync.RWMutex` and `clientInfo []byte` from
the struct, which left the remaining fields padded for a name length that no
longer exists. The merge `d38f83a` brought it onto the integration branch.

The new CI step checks `gofmt -l internal/authz internal/plugins log`. It does
not cover `internal/server`, so a formatting regression introduced inside this
effort is invisible to the check added to catch exactly that.

**The scope is not a careless choice and should not be widened wholesale.**
`gofmt -l internal/server` lists **13** files and `gofmt -l .` lists **49**;
almost all are inherited rtty/GL-original code using four-space indentation, so
a tree-wide step cannot pass. But the three test files this effort added to
`internal/server` — `envelope_test.go`, `authz_subject_test.go`,
`httpproxy_addr_test.go` — are all clean, so `device.go` is the only owned file
that regressed.

Fix is one command plus one path in the workflow:

```sh
gofmt -w internal/server/device.go
# then in .github/workflows/test.yml:
#   gofmt -l internal/authz internal/plugins log internal/server/device.go
```

### 4. The stated reason for excluding `./internal/server/...` is not the real one

`.github/workflows/test.yml` and `450ca39`'s message both give it as:
*"TestRttysStress is a ten-minute stress test that binds :5913, unsuitable for
per-push CI"*, with the remedy *"once the stress test is behind a build tag or a
`-short` guard"*.

Measured, the package does not run for ten minutes. It fails in **0.015 s**:

```
panic: xconfig: global config not initialized; call xconfig.InitGlobal(cfg) at startup
	rttys/internal/server.InitAppContainer       internal/server/api.go:71
	rttys/internal/server.(*RttyServer).ListenAPI internal/server/api.go:267
	rttys/internal/server.(*RttyServer).Run       internal/server/server.go:72
	rttys/internal/server.TestRttysStress.func1   internal/server/rttys_stress_test.go:61
FAIL	rttys/internal/server	0.015s
```

`TestRttysStress` builds an `xconfig.Config` locally, never calls
`xconfig.InitGlobal`, and the package has no `TestMain` that would.
`InitGlobal`'s only caller in the tree is `internal/server/boot.go:82`, which the
test bypasses. Deterministic, not an artefact of this environment.

The remedy named is still right — a build tag removes the test and the package
folds in. The *mechanism* is wrong, and it is wrong in a direction that misleads:
a maintainer who believes the problem is duration reaches for `-timeout` or a
longer CI budget, and neither helps. The stronger and more useful fact is that
the test is **broken**, not slow, and that "ten minutes" has never been observed.

```sh
cd /home/user/kazbek && go test -count=1 ./internal/server/
```

### 5. "three security guards had never been observed to execute" is overstated

`450ca39`: *"it is why TestAuthzSubjectFailsClosed, TestSubjectIDIsStableAcrossRename
and TestHTTPProxyAddrIsLoopbackOnly — three security guards — had never been
observed to run."*

Right about the whole-package invocation, overstated about the guards. Measured
in a scratch copy with `log/log.go` reverted to `450ca39^`:

| Invocation | Pre-fix logger | Post-fix logger |
|---|---|---|
| `go test ./internal/server/` | `FATA open :` — FAIL at 0.012 s | `xconfig` panic — FAIL at 0.015 s |
| `go test ./internal/server/ -run 'TestAuthz\|TestSubjectID\|TestHTTPProxy\|TestWriteMsg'` | **ok, 0.013 s** | ok, 0.019 s |

The guards were runnable by name before the fix. `98250c3`'s own message
corroborates it — it records that its tests were *"run filtered with `-run
TestWriteMsg`"*, which is the same thing. What the logger bug destroyed was the
**unfiltered package run**, and with it anyone's chance of discovering the guards
by running the package.

Two consequences worth stating plainly. The logger fix is necessary for the
package ever to be folded into CI, and it is *not* what makes the new CI step
work — that step uses `-run` and would have passed without it. And the fix moved
the failure from one cause to the next rather than making the package pass: it
still fails, now on item 4.

The logger fix itself is sound and mutation-checked. Both mutations bite:
removing the empty-path guard, and restoring `log.Fatal()` on an open failure
(which prints `FATA` and exits the test binary). **[verified here]**

---

## Branch topology — the big one

### 6. Both CI fixes exist on one branch. `main` still names a branch that does not exist.

`glkvm-debloat`, `.github/workflows/tox.yml`:

| Ref | Filter | `pytest` testpath |
|---|---|---|
| `origin/main` | `[master]` | `testenv/tests` |
| `origin/mcp` | `[master]` | `testenv/tests` |
| `origin/claude/glkvm-webauthn` | `[master]` | `testenv/tests` |
| `origin/claude/glkvm-status-hutk39` | `[master]` | `testenv/tests` |
| `origin/claude/new-session-2w6w30` | `[master]` | `testenv/tests` |
| `origin/claude/repo-status-report-6vi5r1` | `[main, "claude/**", mcp]` | `testenv/tests kvmd` |

`kazbek`: `.github/workflows/test.yml` is present on
`claude/repo-status-report-6vi5r1` and absent from `main`,
`claude/glkvm-stock-debloat-migration-0pibl7` and `claude/new-session-2w6w30`.

For a `push` event GitHub runs the workflow file on the ref being pushed, so a
push to `main`, to `mcp`, or to any other `claude/*` branch still runs nothing.
**The default branch of each repository still has no working test CI.**

This is not a nitpick about propagation. It is the same vacuity class the status
board already carries for the `webauthn.json` guard — a fix and the thing it
fixes on different branches — reached a second way, and it is the class
`AGENTS.md` now has a rule for. "CI is fixed" is currently a statement about one
ref out of six, and about one ref out of four. Say so, or land both changes on
`main`.

```sh
cd /home/user/glkvm-debloat
for b in origin/main origin/mcp origin/claude/glkvm-webauthn \
         origin/claude/glkvm-status-hutk39 origin/claude/new-session-2w6w30 \
         origin/claude/repo-status-report-6vi5r1; do
  echo "### $b"; git show "$b:.github/workflows/tox.yml" | grep -n branches
done
```

### 7. On `mcp`, the widened testpath produces a red collection error, not 55 more tests

The testpath fix is right and I am not arguing against it. But
`3b8109b`'s framing — *"four of the five envs linted it while the only one that
could run it did not"* — implies that with the fix the 55 tests run. Measured on
an `mcp` checkout in this environment, collecting `kvmd` gives:

```
ERROR collecting kvmd/apps/kvmd/api/mcp_test.py
E   FileNotFoundError: [Errno 2] No such file or directory: '/proc/gl-hw-info/model'
E   NameError: name 'get_logger' is not defined
```

That `NameError` is the bug `c7b3be9` fixes on this branch —
`kvmd/utils.py`'s `get_model_name()` calls `get_logger(0)` in its except branch
and the module never imported it — and `mcp` does not carry `c7b3be9`
(`git merge-base --is-ancestor c7b3be9 origin/mcp` → no). `/proc/gl-hw-info/model`
does not exist on any CI runner.

So once the filter and the testpath both reach `mcp`, that branch's job goes
**red at collection** and still runs zero of the 55. That is an improvement over
silence and it is not what the commit message leads a reader to expect. The
prerequisite is that `mcp` picks up `c7b3be9` (two lines) first.

The collection-delta measurement itself is confirmed: `testenv/tests` alone
collects 656 on `mcp`, `testenv/tests kvmd` collects 711, difference **55**.
**[verified here]**

---

## The environment

### 8. `cryptography` should not be in the documented dependency set — a disagreement with the brief

The brief for `docs/testing.md` lists `cryptography` among "the measured working
dependency set". It is installed in this virtualenv (`50.0.1`), and recording it
as part of the recommended set would be a mistake, for three measured reasons.

**It is not in the staged environment.** `testenv/Dockerfile` does not install
`python-cryptography` and `testenv/requirements.txt` does not list it.
**[verified here]**

**Its presence fails a canary that exists to catch exactly this.**
`claude/glkvm-webauthn` carries
`test_ok__cryptography_absent_here` at
`testenv/tests/plugins/auth/test_webauthn.py:210`, asserting the module is not
importable. Run in this virtualenv, that file is **83 passed, 1 failed** against
the **84 passed** recorded as the baseline in
`docs/orchestration/CORRECTIONS-REGISTER.md`. **[verified here]**

**It silently swaps the code path under an authentication test.**
`webauthn.py:274`:

```python
fast = verify_es256_cryptography(spki, message, signature)
if fast is not None:
    return fast
return (await verify_es256_openssl(spki, message, signature, openssl_cmd))
```

With `cryptography` importable, every ES256 verification in that suite takes the
fast path. The openssl path — which `docs/webauthn.md` §1 calls the primary and
tested path, and which a device without `cryptography` actually takes — is
exercised only where a test monkeypatches the fast path away. The other 83 pass
because both paths give the same answer, which is precisely why the canary is the
only test that can tell.

Two knock-on effects. The `84 passed` baseline in the corrections register is
environment-dependent and no longer reproducible in this venv, so the origin-pin
mutation results recorded against it should be re-baselined if they are re-run.
And `1355993`'s note that the canary firing is *"concrete evidence for the
standing caveat that counts from this environment are provisional"* understates
it: it is not only that a count differs, it is that a security-critical branch is
not being exercised.

**Recommendation:** leave `cryptography` out of `docs/testing.md`'s set — the
suite passes without it — and if a future session needs it, install it in a
separate virtualenv. `docs/testing.md` as staged says this.

### 9. `ustreamer` is a local wheel in a scratch directory, and without it the suite collects nothing

`kvmd/clients/streamer.py:35` does `import ustreamer`. The module is **not on
PyPI**: `pip download ustreamer --no-deps` → *"Could not find a version that
satisfies the requirement ustreamer (from versions: none)"*. **[verified here]**

The working virtualenv satisfies it from
`/tmp/claude-0/wheels/ustreamer-6.65-cp311-cp311-linux_x86_64.whl`, built earlier
in this session and sitting in a container-scoped scratch directory.

It is not optional. With the module blocked, `pytest testenv/tests kvmd` aborts
with **three collection errors and zero tests executed**, including
`test_server_smoke.py` and `test_switch_sysfs.py`, which have nothing to do with
video. **[verified here]**

This is the same rot class as `docs/lean-plan.md:741`'s dead `PYTHONPATH`: a
recorded path into a container that will not exist tomorrow. Any record of the
working environment has to carry the *build* instruction, not the wheel path —
`git clone https://github.com/pikvm/ustreamer && make WITH_PYTHON=1 PREFIX=/usr DESTDIR=/ install`,
which is what `testenv/Dockerfile` does.

### 10. `evdev` is imported unconditionally and appears in no image package list — split, unsettled

Ten modules do `from evdev import ecodes` at module scope, including
`kvmd/mouse.py:23` and `kvmd/keyboard/mappings.py:25`. `python-evdev` appears
nowhere in `testenv/Dockerfile`'s pacman list, nowhere in
`testenv/requirements.txt`, and nowhere in `PKGBUILD`'s `depends=`.
**[verified here]**

Per rule 11, that is a statement about package *lists*, not about the built
image: the package could still arrive as a transitive dependency of something
pacman pulls. Settling it needs the image, and **Docker is unavailable here** —
the client is installed, the daemon socket is absent, so `make testenv` cannot
run. **[verified here]**

Split, because the halves have different lifetimes:

- **Verifiable from source, holds now:** no package list in the repository
  declares `evdev`, while the code imports it unconditionally. That is a
  declaration gap regardless of what the image happens to contain.
- **Needs the container:** whether `import evdev` succeeds inside the built
  testenv. Someone with a working Docker should run
  `docker run --rm <testenv image> python -c 'import evdev; print(evdev.__file__)'`.

If it turns out absent, the container has been unable to import half of `kvmd/`
for the life of the fork — which, given that the suite never ran in CI, nobody
would have had occasion to notice.

---

## Still open from the first pass

### 11. `wire.md`'s bundle-rejection list is now contradicted by `errors.md`

Three of the four contract corrections from the first pass landed in `de91cfc`
and `405c42f`: `wire.md`'s four `"v":1` examples are now `"v":2`, `errors.md`'s
`bundle.unsafe_entry` row lists all four triggers, and `manifest.md`'s
canonicalisation note no longer names `capabilities`. All three verified.
**[verified here]**

Two items from that pass are still open, and the first has got worse rather than
merely staying open:

**`wire.md:253-257`** presents its bundle-rejection list as exhaustive — *"A
bundle is rejected before unpacking if any entry: …"* — and it still omits the
`__pycache__` segment and the `.pyc`/`.pyo`/`.pyd`/`.so` suffixes. Now that
`errors.md:46` lists them, the two normative documents **disagree**, where before
both were merely incomplete. A third-party bundle producer implemented from
`wire.md` generates bundles that both halves refuse and that `errors.md` says are
refused.

**`errors.md:44`** still describes `bundle.malformed` as *"Not a readable ustar
archive"*. Measured, it also fires for more than 256 entries, for an empty
archive, and for a member whose content cannot be read.

**`wire.md:257`** still says *"not NFC-safe printable ASCII"*. Both
implementations check printable ASCII only; nothing normalises and no
normalisation library is imported in either half. Low severity — ASCII is
NFC-stable, so the check delivers the property by accident — but it reads as a
Unicode guarantee, and `treehash.py`'s sorting comment explicitly anticipates the
ASCII restriction being relaxed one day.

`invariants.md` §4's mutation note and vector reference also predate the
import-precedence rule.

All four fixes move `CONTRACT-SHA256` and must land in both repos in one cycle.

### 12. Four packages are still missing from `setup.py`

`kvmd.pluginmgr` was added (`setup.py:72`). Four directories still have an
`__init__.py` on disk and no entry in `packages`: `kvmd.apps.kvmd.switch`,
`kvmd.apps.localhid`, `kvmd.apps.media`, `kvmd.apps.swctl`. The first is imported
unconditionally at `kvmd/apps/kvmd/__init__.py:41` (`from .switch import Switch`),
so it is the instance of this bug that is already live rather than latent.
**[verified here]**

---

## Not corrections — verified, and recorded because nothing said they had been

### 13. The D-014 CI step is mutation-verified

`go list -deps ./internal/authz/...` was added to CI per D-014. Nothing said it
had been mutation-checked, so: adding `import _ "rttys/log"` to
`internal/authz/model.go` makes the step fire with `rttys/log`, and the
unmutated tree passes with only `rttys/internal/authz` and
`rttys/internal/authz/fixtures` in the transitive set. **[verified here]** The
check is live, not decorative.

### 14. `_ENTRY_RE`'s anchoring is doubly held, and the redundancy is load-bearing

Two further mutations of `_ENTRY_RE` beyond the end anchor that `252c488` closed:

| Mutation | Suite | Why |
|---|---|---|
| drop the leading `^` | 150 passed | `re.match` anchors at position 0 regardless; a no-op |
| `.match` → `.search` | 150 passed | the pattern still carries `^`, so `search` also anchors |
| **both together** | **150 passed — and `entry='../../plugins/ugpio/acme_relay.py'` validates** | neither anchor remains |

**[verified here]** Each single mutation is harmless because the anchoring is
held twice. That is fine, and it is worth a comment at the definition under rule
7, because the obvious tidy-up — "`^` is redundant with `.match`, drop it" — is
individually safe and removes the redundancy that makes a later switch to
`.search` safe. Two-point mutations are outside normal mutation testing; a
one-line comment costs nothing.

### 15. Everything else I checked today held

| Claim | Result |
|---|---|
| No `master` branch exists | `git ls-remote --heads origin` returns six refs, none `master` |
| Adding `kvmd` to the testpath collects nothing extra here | 1129 both ways |
| Whole Python suite | 1127 passed, 2 skipped |
| `pluginmgr` 146 → 150 | confirmed; the four original import-precedence mutations still bite with unchanged counts (9, 1, 4, 1) |
| `kazbek` had no `go test`/`go vet` | `git grep -lnE "go (test\|vet)"` over `.github`, `Makefile`, `*.sh`, `scripts` at `origin/main` → nothing |
| `gofmt`, `go vet`, `go test` for the three checked packages | all clean/`ok` |
| The six named `internal/server` tests | all pass |
| `signing.md` / `signing-survey.md` split | both present, cross-linked both ways, `plugins.md:161` repointed |
| Contract byte-identity between repos | `diff -r` empty; hash recomputes to the recorded value in both |
| Vectors regenerate reproducibly | `genvectors.py` reproduces `vectors/` exactly |
| The two skips | one needs hardware; one is the `webauthn.json` guard, still an open decision |

### 16. Deliberately not documented as settled

Per instruction, and because both are open decisions rather than defects:

- **The `webauthn.json` guard.** Three options on the status board; owner has not
  picked. `docs/ci.md` as staged says the skip is an open decision and warns
  against reading it as handled.
- **`require_entry` "present but not alone".** Three candidate constraints in
  `docs/plugins/admission.md` §6; the document now says explicitly that this is a
  design decision and not a patch awaiting an author.
