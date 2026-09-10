# Continuous integration — what runs, where, and what never did

**The test suite in this repository had never run in CI.** Not once, on any push
or any pull request, for the whole life of the fork. That is the first thing to
know before reading any older document in `docs/`, because every "this is
covered" and "the suite asserts it" claim written before 2026-09-10 was written
against a CI that did not execute.

Measured against `claude/repo-status-report-6vi5r1` at `1355993` in
`glkvm-debloat` and `450ca39` in `kazbek`. Counts from the reconstructed
virtualenv described in [`testing.md`](testing.md): Python **3.11.15**,
`pytest 9.1.1` — not the staged `testenv` image, so treat them as provisional.
Go measurements are `go1.24.7` locally, against a workflow that pins `1.24.4`.

---

## 1. The two topology traps

Both were the same shape: a configuration that named something which did not
exist, failing in the direction that reads as health.

### Trap 1 — a branch filter naming a branch that has never existed

`.github/workflows/tox.yml` was gated on:

```yaml
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]
```

There is no `master` branch in this repository and there never has been. The
default branch is `main`. `git ls-remote --heads origin` returns exactly six
refs — `main`, `mcp`, and four `claude/*` branches — and none of them is
`master`. **[verified here]**

A branch filter that matches nothing produces no runs, no warnings and no failed
checks. A repository whose CI never fires looks exactly like a repository whose
CI always passes: the Actions tab is empty either way, and no pull request shows
a red check. Nothing in GitHub's interface distinguishes the two.

Now:

```yaml
on:
  push:
    branches: [main, "claude/**", mcp]
  pull_request:
    branches: [main]
```

**Do not narrow this filter without checking the names against
`git ls-remote --heads origin`.** That instruction is also in a comment above the
block, which is where someone would undo it.

### Trap 2 — a testpath that excluded what four other environments included

`testenv/tox.ini` runs five environments over the Python tree. Four of them
passed `kvmd` as well as `testenv/tests`:

| Environment | Paths |
|---|---|
| `flake8` | `kvmd testenv/tests *.py` |
| `pylint` | `kvmd testenv/tests *.py` |
| `mypy` | `kvmd testenv/tests *.py` |
| `vulture` | `kvmd testenv/tests *.py testenv/linters/vulture-wl.py` |
| `pytest` | `testenv/tests` — **only** |

That asymmetry makes an orphan test file look maintained. A test living under
`kvmd/` is linted by four environments, type-checked, and scanned for dead code,
so every signal a contributor sees is green — and it is never executed, because
the one environment that could run it was not looking there.

`kvmd/apps/kvmd/api/mcp_test.py` on the `mcp` branch is exactly that file: **55
tests**, covering route authentication, the request body-size cap, batch
rejection and four redaction properties including URL credentials in logs.
Measured by collection delta on the `mcp` branch: `testenv/tests` alone collects
656, `testenv/tests kvmd` collects 711. **[verified here]**

The `pytest` environment now passes `kvmd` too, and on branches without such a
file this collects nothing extra: `testenv/tests` alone is 1129 on this branch,
and `testenv/tests kvmd` is also 1129. **[verified here]**

---

## 2. What runs now, in this repository

One workflow runs the suite: `.github/workflows/tox.yml`. It builds the testenv
container (`make testenv`) and runs every tox environment
(`make tox CMD="tox -c testenv/tox.ini"`). Three other workflows —
`arduino-hid.yml`, `pico-hid.yml`, `pico-hid-release.yml` — build firmware for
the HID microcontrollers and have nothing to do with the Python tree.

| Environment | What it checks | Config |
|---|---|---|
| `flake8` | style, unused imports | `testenv/linters/flake8.ini` |
| `pylint` | broader static analysis | `testenv/linters/pylint.ini` |
| `mypy` | type checking | `testenv/linters/mypy.ini` |
| `vulture` | dead code, with a whitelist | `testenv/linters/vulture-wl.py` |
| `pytest` | the suite, with coverage | `testenv/linters/coverage.ini` |
| `eslint` | `web/share/js` | `testenv/linters/eslintrc.js` |
| `htmlhint` | `web/*.html`, `web/*/*.html` | `testenv/linters/htmlhint.json` |
| `shellcheck` | `kvmd.install scripts/*` — **not** `apply_to_glkvm.sh` at the repo root | — |

`basepython` in `testenv/tox.ini` is `python3.12`. The suite also passes on
3.11.15 in the reconstructed virtualenv; say which one a count came from.

**Suite size at `1355993`: 1127 passed, 2 skipped.** **[verified here]** Both
skips are in `testenv/tests/test_attestation.py`:

- `:304` — *requires physical hardware; see the docstring*. Honest and correct.
- `:265` — *no reference credential store in this tree*. This is the
  guard/branch split: the test's subject, `configs/kvmd/webauthn.json`, exists
  only on `claude/glkvm-webauthn`, so here the guard skips and certifies nothing,
  in the direction that reads as a pass. **This is an open decision** — three
  options are on the status board and the owner has not picked one. Do not read
  the skip as a finding that has been handled.

`vulture` is the only dead-code check. A flake8-style run is not a substitute:
it finds unused *imports*, not unused *functions*.

---

## 3. `kazbek`, the counterpart

`kazbek` had **no automated test execution of any kind**. `build.yml` runs on
every branch and compiles and packages; it never invokes `go test` or `go vet`,
and neither did anything else in `.github`, the `Makefile`, or any script, on any
branch. **[verified here]** — `git grep -lnE "go (test|vet)"` over `.github`,
`Makefile`, `*.sh` and `scripts` at `origin/main` returns nothing.

`.github/workflows/test.yml` now adds, on every branch and every pull request:

| Step | Scope |
|---|---|
| materialise `ui/dist` | a placeholder `index.html` |
| `gofmt -l` | `internal/authz internal/plugins log` |
| `go vet` | `./internal/authz/... ./internal/plugins/... ./log/...` |
| `go list -deps ./internal/authz/...` | D-014: the only `rttys/` package in the transitive set must be `internal/authz` itself |
| `go test` | `./internal/authz/... ./internal/plugins/... ./log/...` |
| `go test ./internal/server/ -run '…'` | the security tests, selected by name |

All six verified by hand at `450ca39`: `gofmt -l` is empty, `go vet` is clean,
`go list -deps` returns only `rttys/internal/authz` and
`rttys/internal/authz/fixtures`, all four packages report `ok`, and the six named
server tests pass. **[verified here]**

### 3.1 The `ui/dist` placeholder is load-bearing, not cosmetic

`internal/server/api.go` imports `rttys/ui`, whose `embed.go` carries
`//go:embed all:dist`. `ui/dist` is Vite output and is never committed, so
without it **nothing in the module compiles** — including packages that have no
relationship to the frontend. The placeholder keeps the test job independent of
`npm install`, which the workflow comment records as 403ing against the
npmmirror URLs seeded in `ui/yarn.lock`. **[reported]** for the 403; not
reproduced here, and the build workflow does run `npm install` successfully, so
whatever the condition is, it is not unconditional.

### 3.2 Why `./internal/server/...` is excluded, and why the stated reason is not the whole one

The package is deliberately not in the `go test` package list. The workflow
comment gives the reason as `TestRttysStress` being "a ten-minute stress test
that binds :5913, unsuitable for per-push CI", and says the package can be folded
in whole "once the stress test is behind a build tag or a `-short` guard".

Measured, the package does not take ten minutes. It fails in **0.015 s**:

```
panic: xconfig: global config not initialized; call xconfig.InitGlobal(cfg) at startup
	rttys/internal/server.InitAppContainer  internal/server/api.go:71
	rttys/internal/server.(*RttyServer).ListenAPI  internal/server/api.go:267
	rttys/internal/server.(*RttyServer).Run  internal/server/server.go:72
	rttys/internal/server.TestRttysStress.func1  internal/server/rttys_stress_test.go:61
FAIL	rttys/internal/server	0.015s
```

**[verified here]** `TestRttysStress` builds an `xconfig.Config` locally but never
calls `xconfig.InitGlobal`, the package has no `TestMain` that would, and
`InitGlobal`'s only caller in the tree is `internal/server/boot.go:82`, which the
test bypasses. The panic is deterministic, not an artefact of this environment.

The *remedy* named in the comment is still right — a build tag removes the test
and the package folds in. The *mechanism* is not, and the difference matters: a
maintainer who believes the problem is duration will reach for a longer CI
timeout or `-timeout`, and neither helps. The test is broken, not slow, and
"ten minutes" has never been observed here. Folding the package in needs
`TestRttysStress` either tagged out or given an initialised global config and a
usable database path.

### 3.3 The reason the exclusion existed at all

Before `450ca39`, `go test ./internal/server/` did not reach the panic. It died
earlier:

```
FATA open : no such file or directory
FAIL	rttys/internal/server	0.012s
```

`logFileHook.Run` called `log.Fatal()` — `os.Exit(1)` — when it could not open
`h.path`, and `h.path` is empty unless `SetPath` has been called. The hook
attaches whenever stdout is not a terminal, which is true under `go test`, under
systemd, in a container with redirected output, and behind any supervisor. So a
non-TTY run with no log file configured terminated on its first log line.

Measured both ways in a scratch copy: with the pre-fix `log/log.go`, the whole
package fails at 0.012 s with `FATA open :`; with the fix, it fails at 0.015 s
with the `xconfig` panic. **[verified here]** The fix moved the failure from one
cause to the next; the package still does not pass as a whole.

Two mutations of the fix bite: removing the empty-path guard, and restoring
`log.Fatal()` on an open failure. **[verified here]**

One correction to the record. `450ca39` says the logger bug "is why
`TestAuthzSubjectFailsClosed`, `TestSubjectIDIsStableAcrossRename` and
`TestHTTPProxyAddrIsLoopbackOnly` — three security guards — had never been
observed to run." That is right about the whole-package invocation and overstated
about the guards. Measured with the **pre-fix** logger,
`go test ./internal/server/ -run 'TestAuthz|TestSubjectID|TestHTTPProxy|TestWriteMsg'`
reports `ok` in 0.013 s. **[verified here]** The guards were runnable by name
before the fix — the `98250c3` commit message says as much, recording that its own
tests were "run filtered with `-run TestWriteMsg`". What the logger bug destroyed
was the unfiltered package run, and therefore anyone's ability to discover the
guards by running the package. The logger fix is necessary for the package ever
to be folded in; it is not what makes the new CI step work, because that step uses
`-run` and would have passed without it.

---

## 4. The trap that is still open: a fix on one branch is not a fix

Both CI fixes exist on exactly one branch each.

`glkvm-debloat`, `.github/workflows/tox.yml` branch filter:

| Ref | Filter |
|---|---|
| `origin/main` | `[master]` |
| `origin/mcp` | `[master]` |
| `origin/claude/glkvm-webauthn` | `[master]` |
| `origin/claude/glkvm-status-hutk39` | `[master]` |
| `origin/claude/new-session-2w6w30` | `[master]` |
| `origin/claude/repo-status-report-6vi5r1` | `[main, "claude/**", mcp]` |

The `pytest` testpath has the same distribution: `testenv/tests` on five refs,
`testenv/tests kvmd` on one. `kazbek` is the same story — `test.yml` is present on
`claude/repo-status-report-6vi5r1` and absent from `main` and the other two
branches. **[verified here]**

For a `push` event, GitHub runs the workflow file that is on the ref being pushed.
So a push to `main`, to `mcp`, or to any other `claude/*` branch still runs
nothing, because those branches still carry a filter naming a branch that does not
exist. **The repository's default branch still has no working CI.**

This is the same vacuity class as the guard/branch split already on the status
board — a fix and the thing it fixes living on different branches — reached a
second way. The remedy is to land both changes on `main`, after which every branch
that merges from it inherits them. Until then, "CI is fixed" is a statement about
one ref out of six.

---

## 5. What is still not enforced anywhere

- **Mutation testing.** Every mutation result quoted in `docs/` was produced by
  hand, in a throwaway copy of the tree. Nothing re-runs them. The twenty-four
  checks an audit found green-under-mutation were found by a sweep, not by a job,
  and a regression would be silent again.
- **The six mutations on `claude/glkvm-webauthn`.** Recorded on the status board
  as open, on a branch that cannot be pushed from the orchestrating session, and
  behind a design step (merging auth). CI on that branch is also still gated on
  `[master]`, so nothing there runs either.
- **Contract byte-identity between the two repositories.** Each repo's suite
  recomputes its own `CONTRACT-SHA256`, which proves a repo did not edit its copy
  without updating the record. Neither repo can see the other, so nothing asserts
  the two copies are the same tree. Run
  `diff -r contract/plugins ../kazbek/contract/plugins` by hand.
- **`apply_to_glkvm.sh`.** At the repo root, and `shellcheck` covers only
  `kvmd.install scripts/*`.
- **The `mcp` branch's own suite.** Widening the testpath makes
  `kvmd/apps/kvmd/api/mcp_test.py` collectable, but on `mcp` as it stands it
  ERRORS at collection in any environment without `/proc/gl-hw-info/model` —
  `FileNotFoundError`, then `NameError: name 'get_logger' is not defined`.
  **[verified here]** That `NameError` is the bug fixed on this branch by
  `c7b3be9`, which `mcp` does not carry. So once both the filter and the testpath
  reach `mcp`, the job goes **red at collection** rather than green with 55 more
  tests. That is an improvement over silence, and it is not the outcome the
  change's commit message implies.

---

## 6. How to run the suite

In the container, which is what CI does:

```sh
make testenv                                   # build the image (Docker required)
make tox                                       # every environment
make tox E=pytest                              # one environment
make tox CMD="testenv/.tox/pytest/bin/py.test -vv testenv/tests/apps/beacon"
```

`tox.ini` has no `{posargs}`, so the `CMD=` form is the only way to run a subset,
and it needs one full `make tox E=pytest` first to build the venv.

Without Docker, see [`testing.md`](testing.md). Note that `docs/lean-plan.md`'s
documented fallback command for exactly this situation **cannot run** — both
halves of its `PYTHONPATH` point at directories that do not exist. The working
form is in `testing.md`.
