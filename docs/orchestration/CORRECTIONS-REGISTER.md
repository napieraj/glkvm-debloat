# Corrections register

Every claim below was believed, then measured, then found wrong -- or was
checked and held, which is recorded too, because "nobody has verified this" and
"this was verified" look identical in a document that only lists problems.

Organised by STATUS, not by which pass found it. Three separate files were doing
this job (`CORRECTIONS-REGISTER`, `CORRECTIONS-FOUND`, `CORRECTIONS-FOUND-2`,
852 lines, 30 items); they are merged here with every body preserved.

Rule 1 applies to this file as much as to any other: figures go stale, and
several below already did once. Re-derive before acting.

## Contents

| Status | Meaning |
|---|---|
| **Fixed** | measured, wrong, corrected in the tree |
| **Open** | measured, wrong, not yet corrected |
| **Corrections to claims made in this session** | this orchestrator or an agent said something wrong |
| **Settled — no action** | checked and held, or deliberately decided against |


---

# Fixed


## `contract/plugins/wire.md:95, 110, 174, 197` — every message-body example still says `"v":1`

**Claims.** The four worked examples of the JSON message bodies are:

```
:95   {"manifest":{...},"v":1}
:110  {"sha256":"<64 lowercase hex>","v":1}
:174  {"reason":"","sha256":"<64 hex>","state":"installed","v":1}
:197  {"entries":[{"path":"...","sha256":"..."}],"sha256":"<64 hex>","tree_sha256":"<64 hex>","v":1}
```

**Measured.** The protocol version is 2. The same file says so in prose at
`:77` ("Every JSON body carries `"v": 2`") and at `:80` ("Version 2 is the
current protocol"). `kvmd/pluginmgr/wire.py` sets `PROTOCOL_VERSION = 2`,
`encode_json_body` stamps it, and `decode_json_body` **refuses** any other
value with `manifest.unsupported_version` rather than ignoring it. Every one of
the four examples as written would be refused by the implementation the same
document specifies.

This is the highest-value item in this list: it is the normative contract, it
is the part a reader copies, and it is wrong in the direction that produces a
refusal at integration time rather than at review time. It is v1 text that
survived the v2 bump in `6749a89`.

```sh
grep -n '"v":1' contract/plugins/wire.md
grep -n 'PROTOCOL_VERSION' kvmd/pluginmgr/wire.py
```


## `contract/plugins/manifest.md:198-199` — names a field that no longer exists, and calls a required field optional

**Claims.** "`signature` and `capabilities` are omitted entirely when absent
rather than encoded as `null`."

**Measured.** Neither half of that sentence holds under v2.

`signature` is **required**, not optional. `_REQUIRED` in
`kvmd/pluginmgr/manifest.py` includes it, `_check_keys` raises
`manifest.malformed` on a missing required field, and `Manifest.to_dict()`
emits `signature` unconditionally. It is never absent, so there is no
absent-case to describe. The same document argues four sections earlier that
this is deliberate — an optional block would leave "unsigned" and "signature
omitted" indistinguishable.

`capabilities` does not exist. It was renamed to `sandbox` in the v2 bump
(`6749a89`), and `manifest.md:179` explains at length why the rename was
necessary. `_check_keys` refuses `capabilities` as an unknown top-level field.
The field that *is* omitted when absent is `sandbox`, and `to_dict()` omits it
exactly as described.

```sh
sed -n '195,200p' contract/plugins/manifest.md
grep -n '_REQUIRED\|_OPTIONAL' kvmd/pluginmgr/manifest.py
```


## `contract/plugins/errors.md:46` — `bundle.unsafe_entry` is described as one trigger and has four

**Claims.** "`bundle.unsafe_entry` | An entry is not a regular file."

**Measured.** The code raises `CODE_BUNDLE_UNSAFE_ENTRY` for four distinct
conditions, only one of which the table names:

| Trigger | Where |
|---|---|
| a member that is not a regular file | `read_bundle` |
| a path with a trailing `/` (directory entry) | `_check_path` |
| a `__pycache__` segment at any depth | `_check_not_importable_ahead_of_source` |
| a `.pyc` / `.pyo` / `.pyd` / `.so` suffix, case-insensitive | same |

`read_placed_tree` raises it a fifth time, for a non-regular file found under
the placement root after placement.

This matters more than a normal doc gap, because `errors.md` is the table both
implementations are held to and the table a server author reads to decide what
a code means. A server that reads "not a regular file" and acts on
`bundle.unsafe_entry` accordingly will mis-report three of the four cases,
including both cases of the newest refusal rule.

The adjacent row has a smaller version of the same problem:
`bundle.unsafe_path` at `:45` omits the empty-path case, and `bundle.malformed`
at `:44` says only "Not a readable ustar archive" while the code also raises it
for more than 256 entries, for an empty archive, and for a member whose content
cannot be read.

Measured by exercising every path through `read_bundle` against a synthesised
ustar per case and recording the code returned:

```sh
PYTHONPATH=/home/user/glkvm-debloat <venv>/bin/python <script that calls read_bundle per case>
```

(the full measured table is reproduced in `docs/plugins/admission.md` §3).


## `setup.py:67-106` — `kvmd.pluginmgr` is not in `packages`

**Claims.** Nothing claims otherwise in the tree; this is an omission rather
than a false statement. It is included because `docs/webauthn.md` (on
`origin/claude/glkvm-webauthn`) states the figure as **four**, and on this
branch it is five.

**Measured.** Five directories under `kvmd/` have an `__init__.py` and no entry
in `setup.py`'s `packages` list: `kvmd.apps.kvmd.switch`, `kvmd.apps.localhid`,
`kvmd.apps.media`, `kvmd.apps.swctl`, and **`kvmd.pluginmgr`**. Nothing is
declared that does not exist.

`kvmd.pluginmgr` was added by `9da389a` without a `setup.py` entry, so the
device half of the plugin foundation is present in git and would be absent from
an install. It is not currently imported by anything outside its own tests, so
nothing breaks today; it will break the moment the placement layer imports it
from `kvmd/apps/`. `kvmd.apps.kvmd.switch` is the pre-existing instance of the
same problem that already *is* imported unconditionally, at
`kvmd/apps/kvmd/__init__.py:41`.

`docs/webauthn.md`'s "four" is correct on its own branch — `kvmd/pluginmgr`
does not exist there (`git ls-tree -d origin/claude/glkvm-webauthn
kvmd/pluginmgr` returns nothing). The figure is stale only once the two
branches meet.

```sh
python3 - <<'EOF'
import os, re
declared = set(re.findall(r'"([^"]+)"', re.search(r"packages=\[(.*?)\]", open("setup.py").read(), re.S).group(1)))
ondisk = {d.replace(os.sep,".") for d,_,n in os.walk("kvmd") if "__init__.py" in n and "__pycache__" not in d}
print(sorted(ondisk - declared))
EOF
```


## The hash-comparison test closes one truncation length out of five

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


## `require_entry`'s new test does not close `startswith`

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


## `internal/server/device.go` is gofmt-unformatted, and the new gofmt step cannot see it

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


## The stated reason for excluding `./internal/server/...` is not the real one

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


## Four packages are still missing from `setup.py`

`kvmd.pluginmgr` was added (`setup.py:72`). Four directories still have an
`__init__.py` on disk and no entry in `packages`: `kvmd.apps.kvmd.switch`,
`kvmd.apps.localhid`, `kvmd.apps.media`, `kvmd.apps.swctl`. The first is imported
unconditionally at `kvmd/apps/kvmd/__init__.py:41` (`from .switch import Switch`),
so it is the instance of this bug that is already live rather than latent.
**[verified here]**

---

## Not corrections — verified, and recorded because nothing said they had been


---

# Open

## The mypy gate in CI has been blocked, not passing — it checked nothing

`testenv/tests/test_attestation.py:342` did
`from testenv.tests.test_routes import collect_routes`. That gives mypy a
second module name (`testenv.tests.test_routes`) for a file it already has as
`tests.test_routes`, and mypy treats that as a BLOCKING error rather than a type
error:

```
error: Source file found twice under different module names
Found 1 error in 1 file (errors prevented further checking)
```

Exit code 2. The tox summary line reads `mypy: FAIL code 2`, which looks like
"two errors" and is in fact mypy's exit status for "could not run". Nothing in
the tree was type-checked, on any run, since that import was written.

Fixed by making the import relative (`from .test_routes import ...`), which is
what the rest of the suite does. mypy then completes. Measured in the
reconstructed venv, cache cleared between runs:

| tree | mypy |
|---|---|
| before the unblock (`f96c0eb^`) | exit 2, **nothing checked** |
| the unblock alone (`f96c0eb`) | exit 1, **118 errors in 39 files**, 286 checked |
| with the `kvmd/tools.py` narrowing (`4fa7cac`) | exit 1, **116 errors in 38 files** |

Both of those figures are environment-dependent: `ignore_missing_imports = true`
silences whatever is not installed, and the same command in this venv reported 91
before the runtime dependencies went in. CI's number is the one to act on.

Two of the errors were in `kvmd/tools.py`, on `run_command`'s return, which is the
value `kvmd/plugins/auth/webauthn.py` reads as the openssl signature verdict.
Fixed in the same series.

**Correction to the two commit messages in that series, both already pushed.**
`f96c0eb` states "116 errors in 38 files" and `4fa7cac` states "116 -> 114". Both
are wrong by the same 2, and in the same way: I measured the count once, after
applying the `tools.py` fix, then attributed it to the commit before it as well.
The table above is the measured set. The figures are not load-bearing for either
change, but a number stated without being measured at the tree it describes is
exactly what rule 1 is about, and this register is where that gets said rather
than quietly rebased away.

**Still open:** the other 114. And the reading habit that hid this — `FAIL code N`
in a tox summary is an exit status, not a count. `pylint: FAIL code 30` is
pylint's bitmask (convention+refactor+warning+error), not 30 findings;
`vulture: FAIL code 3` is an exit status too. Every one of those needs its own
output read before anyone states a number.



## `contract/plugins/wire.md:253-257` — the bundle rejection list does not mention the rule both halves now enforce

**Claims.** "A bundle is rejected before unpacking if any entry: is not a
regular file …; has an absolute path, a `..` component, a drive letter or a
backslash; has a path that is not NFC-safe printable ASCII; would place a file
outside the plugin root."

**Measured.** Both implementations additionally refuse `__pycache__` segments
and `.pyc` / `.pyo` / `.pyd` / `.so` suffixes, and three shared conformance
vectors now assert it (`unsafe-bytecode-cache`, `unsafe-native-extension`,
`unsafe-sourceless-bytecode` in `contract/plugins/vectors/bundles.json`).

This is a gap between the contract's prose and the contract's vectors rather
than between the contract and the code — the vectors are normative too, so the
rule *is* in the contract. But a reader of `wire.md` alone would implement a
third-party bundle producer that generates bundles both halves refuse, and
would have no way to know why from that document. `invariants.md` §4 has the
same gap: its mutation note and vector reference predate the rule.

Not an error introduced by anyone; the code fix (`622c6d3`, `91b93fc`) and the
vectors (`12ec53c`, `201f9f1`) landed on the same day and the prose was not
carried along.

```sh
sed -n '250,260p' contract/plugins/wire.md
python3 -c "import json;print([c['id'] for c in json.load(open('contract/plugins/vectors/bundles.json'))['cases']])"
```


## `contract/plugins/wire.md:257` — "NFC-safe printable ASCII" describes a property nothing checks

**Claims.** An entry is rejected if it "has a path that is not NFC-safe
printable ASCII".

**Measured.** Both implementations check printable ASCII only —
`0x20 <= ord(char) <= 0x7E` in Python, `name[i] < 0x20 || name[i] > 0x7e` in Go.
Nothing anywhere normalises, and no Unicode normalisation library is imported
in either half.

Low severity, because ASCII is NFC-stable by construction, so the check
delivers the stated property by accident. It is listed because it reads as a
Unicode-normalisation guarantee, and a future relaxation of the ASCII
restriction — which `treehash.py`'s sorting comment explicitly anticipates —
would silently drop a property the contract promises. Deleting "NFC-safe"
costs nothing and removes the trap.

```sh
grep -n "NFC" contract/plugins/wire.md
grep -rn "unicodedata\|normalize\|NFC" kvmd/pluginmgr/ ; # no hits
```


## `wire.md`'s bundle-rejection list is now contradicted by `errors.md`

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


## Both CI fixes exist on one branch. `main` still names a branch that does not exist.

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


## On `mcp`, the widened testpath produces a red collection error, not 55 more tests

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


## `evdev` is imported unconditionally and appears in no image package list — split, unsettled

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


---

# Corrections to claims made in this session

## I told the documentation agent `cryptography` was absent, and it pushed back with the same wrong reasoning

The agent's brief listed `cryptography` in the working dependency set. I told it
to take it out; it came back with a measured case for leaving it out, I accepted
the reasoning, and it was written into `docs/testing.md` §4.1, the register, a
code docstring, `softauthn.py`'s module docstring and `docs/webauthn.md` §1 —
five places, one error. Neither of us was careless: `PKGBUILD`, the pacman list,
`requirements.txt` and a `grep` over `*.py` were all checked and all came back
empty, and all four were accurate.

The error is that none of those four can see a package installed because another
package asked for it. `pyghmi` was sitting in `requirements.txt:2` the whole time,
and `cryptography==50.0.1` and `pyghmi==1.6.19` were eight lines apart in the
freeze that `docs/testing.md` §3 prints. Agreement between two agents who ran the
same kind of search is not a second measurement.

Standing rule 11 already names this shape one level up — a source search proves
the absence of a *caller*, never of a *mechanism*. The same gap holds between a
package list and an installed environment. The general form, worth adding to how
this is read: **an absence established by searching for a name is an absence of
the name.** To claim the thing is absent you have to ask the thing that would
know — here, `importlib.metadata.requires` on what IS declared, or an import in
the interpreter under test.

Also mine, found while fixing it: the first mutation run on the fast path
reported two of five mutations as caught when they were not. The throwaway copy
of the tree was missing `configs/`, so one unrelated test failed in every run and
"grep for failed" read that as the mutation biting. Establish the copy is green
BEFORE mutating it — the harness now does, and the two survivors turned out to be
the two that needed tests written specially, because neither changes the
function's return value.



## Corrected entry — WebAuthn

**Superseded claim:** "WebAuthn integrated, origin pin, five non-negotiables" →
"**Absent from both working trees.** … no WebAuthn anywhere in either repo."

**The correction is to the correction.** The rebuttal was generalised from a
worker's report about the auth core into a claim about the whole tree. Accurate
version:

> The **implementation** is absent from both working trees and lives only on
> `claude/glkvm-webauthn`. `claude/glkvm-status-hutk39` retains documentation and
> one guard that reference it: `docs/lean-plan.md` (12 hits, steps 11/12),
> `docs/audit.md:768`, and `testenv/tests/test_attestation.py:259`.

Measured: `webauthn` matches 0 files on `main`, `claude/new-session-2w6w30` and
`mcp`; 3 files on `hutk39`; 17 files on `claude/glkvm-webauthn`.

**"Five non-negotiables" was never a code invariant.** The phrase appears exactly
once in the tree, in `docs/webauthn.md`. That is why a review bar set from it
could not be met. Relatedly, commit `13d6eb6` says "five guard tests";
`testenv/tests/apps/kvmd/test_login_verified.py` has **six**.


## New — the origin pin is defended against deletion, not against weakening

Directed mutation pass on `claude/glkvm-webauthn` @ `13d6eb6`.

Environment, named per rule 2: Python **3.11.15**, `pytest 9.1.1`,
`pytest-asyncio 1.4.0`, `pytest-aiohttp 1.1.1`, `pytest-mock 3.15.1`,
`aiohttp-basicauth 1.2.0`, `aiohttp 3.14.3`. Reconstructed venv, not the staged
testenv. Baseline `testenv/tests/plugins/auth/test_webauthn.py`: **84 passed**
(46 test functions with parametrisation).

The first run reported *26 failed*. That was the recorded hazard, not a real
failure — absent `pytest-asyncio` presents async tests as failures, not skips.

| Mutation to `kvmd/plugins/auth/webauthn.py` | Result |
|---|---|
| **A.** Delete the `if origin not in accepted` membership check | **3 failed** — bites |
| **B.** Weaken exact membership to `any(origin.startswith(a) for a in accepted)` | **84 passed — silent** |
| **C.** Drop the `crossOrigin` guard | **1 failed** — bites |
| **D.** `accepted = self.__origins or get_default_origins() + (origin,)` | **84 passed — silent** |

**B** ships a cross-origin relay hole green: with `https://kvm-pve1.oskar.co`
pinned, `https://kvm-pve1.oskar.co.attacker.test` prefix-matches and is accepted.
The suite's three negative origin cases (`https://evil.oskar.co`,
`http://kvm-pve1.oskar.co`, `""`) are all rejected by prefix matching too, so
none of them distinguishes exact match from prefix match.

**D** is the sharper one. `origins` defaults to `[]`
(`webauthn.py:473`) and **nothing in `configs/` sets it**, so a shipped device
takes the `get_default_origins()` fallback — the per-device half of the pin, and
per its own docstring the defence against exactly this relay. Every test
constructs the plugin with `origins=[_ORIGIN]` explicitly
(`test_webauthn.py:75`, `kwargs.setdefault`). `test_ok__default_origins_is_the_device_fqdn`
exercises `get_default_origins()` in isolation but never through
`verify_assertion`.

**So the code path that ships is the one path the suite never verifies.** Not
"the sole relay defence is undefended" — narrower and more awkward: it is
defended only on a configuration no shipped device uses.

Two cases would close it, and neither is a merge blocker in itself: an assertion
against an origin that is a superstring of a pinned one, and one verification run
with `origins` unset.


## New — `test_auth.py`: neither version is a superset

`07-INTEGRATION-CONFLICTS.md` recommends taking Worker B's file on the grounds it
"is almost certainly a superset". True against `1ab2083` (4 tests). Not true now:
`hutk39` carries **10**, `claude/new-session-2w6w30` carries **6**, and each has
tests the other lacks. Following the recommendation drops six tests, including
the WS-session lifecycle trio and the TOTP-removal guard. Resolution is a union
of twelve. See the status board for the two name lists.


## "three security guards had never been observed to execute" is overstated

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


## Commit `9da389a` message — "the bundle path checks run before the verifier"

**Claims.** "Structural validation and the bundle path checks run before the
verifier and for every verifier, noop included, which is the only reason noop is
survivable at all."

**Measured.** The second half is right and the first is not.
`kvmd/pluginmgr/gate.py` imports from `errors`, `manifest` and `verifier` and
never from `bundle`; `gate()` cannot run a bundle path check because it never
sees the bundle. `contract/plugins/errors.md` files the bundle codes under
"Bundle unpacking (device side, **after** the gate)", which is the accurate
ordering.

What is true — and is the load-bearing claim — is that the bundle checks are
independent of *which* verifier is configured and are not skipped by `noop`.
That independence is what makes `noop` survivable, not any ordering relative to
the gate. Commit-message-only; the code and `errors.md` are both correct.

```sh
grep -n "^from\|^import" kvmd/pluginmgr/gate.py
grep -n "after the gate" contract/plugins/errors.md
```


## `docs/orchestration/FINDINGS-plugin-contract.md:78` — the stated build blocker does not reproduce

**Claims.** "Not reproduced here — kazbek Go does not build in this environment
without the frontend workaround. Reproduce before acting."

**Measured.** At `8853e50`, `go build ./...` exits 0 and
`go test -count=1 ./internal/plugins/` reports `ok rttys/internal/plugins`.
`ui/dist/index.html` is present, which satisfies the `//go:embed all:dist` in
`ui/embed.go`, so whatever workaround was needed is in place.

Largely superseded: the same file's resolution section (added in `030b52b`)
records finding 4 as reproduced over `net.Pipe` and fixed in `98250c3`. The
original sentence is still in the body above that section, and the body is what
a reader hits first. Worth noting for a different reason too: the resolution
section records that `go test ./internal/server/` is red on the base with and
without the change, identically, from a log-file hook that attaches whenever
stdout is not a TTY — which is exactly the "name the environment, a missing
dependency presents as a failure" hazard in a second guise, and is worth
carrying into `AGENTS.md` alongside the Python instance.

```sh
cd /home/user/kazbek && go build ./... ; echo "exit=$?"
cd /home/user/kazbek && go test -count=1 ./internal/plugins/
```

---


---

# Settled by disagreement or measurement — no action


## ~~`cryptography` should not be in the documented dependency set~~ — OVERTURNED BY CI

**This item was wrong, and so was the agreement that settled it.** It is kept
under "settled" rather than moved, so that the next reader of this section sees
that an item can be settled by measurement and still be wrong — the measurements
below are all accurate; the inference from them is not.

`cryptography` IS in the staged environment. `pyghmi` (`testenv/requirements.txt:2`)
declares `cryptography>=2.1`, so pip installs it transitively in the container
exactly as it did in this venv. Every search that backed "absent" searched for the
NAME in a hand-written list, and a dependency list cannot see a transitive pull.
The canary is what caught it, on the first CI run: `test_ok__cryptography_absent_here`
FAILED with `assert True is None`.

Acted on, 2026-09-10: the canary was replaced by its inverse, the live fast path's
three fail-closed exits were mutation-checked (all three previously survived), a
plugin-level test now forces the openssl path so it keeps integration coverage,
and `docs/webauthn.md` §1 / `docs/testing.md` §4.1 were rewritten. See
`docs/webauthn.md` §1.1 for the shape of the error.

The original item, as settled:


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


## `ustreamer` is a local wheel in a scratch directory, and without it the suite collects nothing

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


## The D-014 CI step is mutation-verified

`go list -deps ./internal/authz/...` was added to CI per D-014. Nothing said it
had been mutation-checked, so: adding `import _ "rttys/log"` to
`internal/authz/model.go` makes the step fire with `rttys/log`, and the
unmutated tree passes with only `rttys/internal/authz` and
`rttys/internal/authz/fixtures` in the transitive set. **[verified here]** The
check is live, not decorative.


## `_ENTRY_RE`'s anchoring is doubly held, and the redundancy is load-bearing

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


## Not corrections — provenance upgrades

Three items in `FINDINGS-plugin-contract.md` were marked *agent-measured, not
reproduced here*. All three were reproduced independently for this
documentation pass, on Python 3.11.15, and the orchestrator reproduced two of
them in parallel (recorded in that file's resolution section, `030b52b`).

| Finding | Reproduced here | Result |
|---|---|---|
| §2 — a matching-header `.pyc` executes instead of its `.py` | yes | `VERSION = 2` on disk imported as `1` in a fresh interpreter after `invalidate_caches()`; `__file__` still named the `.py`; deleting `__pycache__` returned `2` |
| §2 (the `.so` half) | yes | `find_spec` resolved to `probe.so` with `ExtensionFileLoader` and the import raised `ImportError`, rather than falling through to `probe.py` |
| §3 — load poisons readback | yes | `readback_for` gave `7d72f438…` before an import from the placed root and `a374f864…` after, with three `__pycache__` `.pyc` entries added |

The hashes differ from the ones in `FINDINGS` §3 because the placed trees
differ; the effect is the same and the direction is the same.

Two further things were verified rather than taken on trust, and both held:

- The `contract/plugins` tree is byte-identical between the two repositories at
  the refs above (`diff -r`), and `CONTRACT-SHA256` recomputes in both to
  `4888f9ea44c85bf852d2c12a2555ae3bc2fd06d0cadf5eefdfaf11197b73e788`.
- The vectors regenerate reproducibly. Copying `contract/plugins` to a scratch
  directory and running `python3 tools/genvectors.py vectors` reproduces the
  committed `vectors/` with no difference, so `README.md`'s claim that the
  generator is checked in "so the vectors are reproducible rather than magic
  constants" is true and not merely intended.


## Everything else I checked today held

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


## Deliberately not documented as settled

Per instruction, and because both are open decisions rather than defects:

- **The `webauthn.json` guard.** Three options on the status board; owner has not
  picked. `docs/ci.md` as staged says the skip is an open decision and warns
  against reading it as handled.
- **`require_entry` "present but not alone".** Three candidate constraints in
  `docs/plugins/admission.md` §6; the document now says explicitly that this is a
  design decision and not a patch awaiting an author.


## Standing consequence

Add to the vacuity class: **a guard and the thing it guards must live on the same
branch.** Every prior instance — `_ROOT` one level short, the uncovered session
expiry, the five tests passing against a nonexistent directory — was inside a
single tree. This one is a property of the branch topology, and nothing checks
it.


## Suite counts at the refs above

| Suite | Count | Ref |
|---|---|---|
| `testenv/tests/pluginmgr` | 132 passed | `622c6d3^` (via `git archive` to scratch) |
| `testenv/tests/pluginmgr` | 143 passed | `622c6d3` |
| `testenv/tests/pluginmgr` | **146 passed** | `030b52b` |
| `go test ./internal/plugins/` | `ok` | `8853e50` |

The 132 → 143 and 143 → 146 transitions match what commits `622c6d3` and
`12ec53c` claim.
