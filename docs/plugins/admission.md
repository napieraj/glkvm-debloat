# Plugin admission — what a bundle must be before anything reaches the disk

Admission is the set of checks a plugin passes before the device is allowed to
write. This document describes what those checks are today, what each refusal
code means, and — for the newest rule, which refuses entries that CPython would
import in preference to the declared source — why the rule exists and what
would justify changing it.

Every line number and every count below was re-derived against
`claude/repo-status-report-6vi5r1` at `1355993` in `glkvm-debloat` and at
`450ca39` in `kazbek`. Both are the pushed tip of that branch in their repo.
The branch has moved several times a day while this was written; re-derive
before acting on any figure here, and prefer the recompute commands given
over the values quoted beside them.

Environment, named because a missing test dependency presents here as a failure
and not as a skip: Python **3.11.15**, `pytest 9.1.1`, `pytest-asyncio 1.4.0`,
`pytest-aiohttp 1.1.1`, `pytest-mock 3.15.1`, `aiohttp 3.14.3`,
`aiohttp-basicauth 1.2.0`, `bcrypt 4.0.1`, `passlib 1.7.4`. This is the
reconstructed virtualenv, **not** the staged `testenv` image — see
[`../testing.md`](../testing.md) for what that difference costs. It is invoked
as

```sh
PYTHONPATH=/home/user/glkvm-debloat \
  <venv>/bin/python -m pytest testenv/tests/pluginmgr -q -p no:cacheprovider
```

Go measurements are `go1.24.7`, `go test -count=1 ./internal/plugins/`.

Claims are marked **[verified here]** when they were read out of the tree or
produced by a command run while writing this document, and **[reported]** when
they come from a commit message or another document and have not been
independently reproduced.

---

## 1. Three checks, three different moments

"Admission" is not one function. Three separate checks run at three separate
points, and the distinction is load-bearing because each can only see part of
the picture.

| Check | Function | Sees | Runs |
|---|---|---|---|
| Offer admission | `gate.admit_offer(manifest, installed_revision)` | the manifest only | before `fetch`, before any byte moves |
| The verify gate | `gate.gate(verifier, manifest, payload)` | manifest + assembled payload | after the transfer completes |
| Bundle read | `bundle.read_bundle(data)` | the archive's entries | after the gate, before placement |

`admit_offer` takes no payload argument at all
(`kvmd/pluginmgr/gate.py`), which is what makes "before the first chunk"
structural rather than a convention: the oversized case cannot be checked late
because the function could not be handed the bytes even by mistake.
**[verified here]** `test_admission_needs_no_payload` in
`testenv/tests/pluginmgr/test_admission.py` states the same thing as an
assertion.

The gate's step 2 — assembled length against `manifest.payload.size` — is a
different claim from admission's, not a duplicate of it. Admission compares a
*declaration* against the protocol ceiling; step 2 compares *reality* against
the declaration. Neither substitutes for the other. Without admission an
oversized bundle is transferred in full and only then refused, and because v1
has no resume, a dropped transfer restarts at chunk 0 and size multiplies with
link unreliability. Without step 2 a truthful declaration is never checked
against what actually arrived.

`read_bundle` is not called by the gate. `kvmd/pluginmgr/gate.py` imports from
`errors`, `manifest` and `verifier` and never from `bundle`. **[verified here]**
`contract/plugins/errors.md` files the bundle codes under "Bundle unpacking
(device side, after the gate)", which is the accurate ordering. The bundle
checks are nevertheless independent of *which* verifier is configured — they are
not skipped by `noop` — and that independence, not an ordering relative to the
gate, is what makes `noop` survivable at all.

### 1.1 There is no production caller yet

`kvmd/pluginmgr` has no caller outside its own package and its own tests.
`grep -rn "readback_for\|read_placed_tree\|admit_offer\|gate_named\|read_bundle"
--include="*.py" .` returns hits only in `kvmd/pluginmgr/` and
`testenv/tests/pluginmgr/`. **[verified here]** There is no placement function,
no rollback function and no install driver in the tree.

Two consequences follow, and both matter for reading the rest of this document.
First, per the standing rule that a source search proves the absence of a
*caller* and never the absence of a *mechanism*: the absence here is genuinely
the absence of code, because the functions that would do the writing do not
exist to be found, not merely the absence of a call to them. Second, everything
below describes what admission refuses, not what a running device does — the
device half is a foundation waiting for its placement layer.

A packaging gap found while writing the first version of this document has since
been closed: `kvmd.pluginmgr` was absent from `setup.py`'s `packages`, so the
module was present in git and would not have shipped. `setup.py:72` now lists it.
**[verified here]** Four other directories still have an `__init__.py` on disk and
no entry there — `kvmd.apps.kvmd.switch`, `kvmd.apps.localhid`, `kvmd.apps.media`,
`kvmd.apps.swctl` — and the first of those is imported unconditionally at
`kvmd/apps/kvmd/__init__.py:41`, so the same class of bug is still live
elsewhere.

---

## 2. What `read_bundle` accepts

A v1 bundle is an uncompressed POSIX ustar archive of regular files only, at
most `BUNDLE_MAX_ENTRIES` = 256 of them. Both languages already have a tar
reader in the standard library, so the format costs the device no new
dependency — that was the choice, not an accident of convenience.

`read_bundle` validates every member before returning anything. It appends to a
local list and raises on the first offending entry, so a caller can never act on
a partially validated tree. On success it returns `list[TreeFile]`, each a
`(path, data)` pair with the path exactly as the archive spelled it.

The 256-entry bound is checked before each append, so a bundle of exactly 256
entries is accepted and a bundle of 257 is refused. **[verified here]** The bound
exists so that a well-formed archive cannot become a resource-exhaustion path
*after* the size check in the manifest has passed: 8 MiB of one-byte files is
within the payload cap and is not within this one.

`require_entry` is a separate call. It asserts that the path named by
`manifest.entry` is present among the files. It does **not** assert that it is
the only file, and section 6 is about what that leaves open.

---

## 3. Every refusal, and what triggers it

The table below was produced by exercising `read_bundle` directly against a
synthesised archive for each case, not by reading the source. **[verified here]**

| Entry | Code | Detail |
|---|---|---|
| `plugins/ugpio/a.py` | *accepted* | |
| `plugins/ugpio/table.json` | *accepted* | non-Python data files are fine |
| `plugins/ugpio/lib.python.helper.py` | *accepted* | dots in the stem are not a suffix |
| `/abs.py` | `bundle.unsafe_path` | absolute path |
| `../escape.py` | `bundle.unsafe_path` | unsafe segment |
| `plugins/./a.py` | `bundle.unsafe_path` | unsafe segment |
| `plugins//a.py` | `bundle.unsafe_path` | unsafe segment (empty) |
| `plugins\ugpio\a.py` | `bundle.unsafe_path` | backslash |
| `plugins/ugpio/` | `bundle.unsafe_entry` | directory entry (trailing slash) |
| `plugins/ugpio/a\tb.py` | `bundle.unsafe_path` | non-printable ASCII |
| `plugins/ugpio/é.py` | `bundle.unsafe_path` | non-printable ASCII |
| `plugins/ugpio/a\x7f.py` | `bundle.unsafe_path` | non-printable ASCII (DEL) |
| any symlink member | `bundle.unsafe_entry` | not a regular file |
| any directory member | `bundle.unsafe_entry` | not a regular file |
| any FIFO member | `bundle.unsafe_entry` | not a regular file |
| `plugins/ugpio/__pycache__/a.cpython-311.pyc` | `bundle.unsafe_entry` | bytecode cache directory |
| `plugins/ugpio/__pycache__/note.txt` | `bundle.unsafe_entry` | bytecode cache directory |
| `plugins/ugpio/sub/__pycache__/a.pyc` | `bundle.unsafe_entry` | bytecode cache directory, at any depth |
| `plugins/ugpio/a.pyc` / `.pyo` / `.pyd` | `bundle.unsafe_entry` | would be imported ahead of source |
| `plugins/ugpio/a.so` | `bundle.unsafe_entry` | would be imported ahead of source |
| `plugins/ugpio/a.abi3.so` | `bundle.unsafe_entry` | ditto — `.so` covers it |
| `plugins/ugpio/a.cpython-311-x86_64-linux-gnu.so` | `bundle.unsafe_entry` | ditto |
| `plugins/ugpio/A.SO`, `A.PYC` | `bundle.unsafe_entry` | the suffix match is case-insensitive |
| 257 entries | `bundle.malformed` | more than 256 entries |
| empty archive | `bundle.malformed` | no entries |
| not a ustar archive | `bundle.malformed` | `tarfile.TarError` wrapped |
| a member with no readable content | `bundle.malformed` | `extractfile()` returned `None` |

### 3.1 Check order is observable

The order in `read_bundle` and `_check_path` determines which code a caller sees
when an entry breaks more than one rule, and the shared vectors pin exactly that
for the cases they carry. Two orderings are worth knowing:

**The regular-file check runs before the path check.** A symlink whose target
escapes the root reports `bundle.unsafe_entry`, not `bundle.unsafe_path`.

**The trailing-slash check runs before the segment loop.** `plugins/ugpio/` has
an empty final segment and would otherwise report `bundle.unsafe_path`; it
reports `bundle.unsafe_entry` instead, because a directory entry is refused as
an entry kind rather than as a path shape. Both are consistent with the code
table in `contract/plugins/errors.md`, but only if you read that table as a list
of what each code is used for, not as a definition of when it fires.

Within `_check_path` the order is: empty, leading `/`, backslash anywhere,
trailing `/`, unsafe segment, non-printable ASCII, and then the
import-precedence rule last.

---

## 4. The newest rule: entries that would be imported ahead of the source

Landed in `622c6d3` on the device half and `91b93fc` on the server half; the
shared conformance vectors followed in `12ec53c` (`glkvm-debloat`) and `201f9f1`
(`kazbek`). An independent audit pass later confirmed the rule and found no
further importable-suffix gap in either half.

The rule is two clauses, in `_check_not_importable_ahead_of_source`
(`kvmd/pluginmgr/bundle.py`):

1. any path segment equal to `__pycache__`, at any depth, is refused;
2. any path whose lowercased form ends in `.pyc`, `.pyo`, `.pyd` or `.so` is
   refused.

Both raise `bundle.unsafe_entry`.

### 4.1 Why: the correspondence the whole design rests on

Everything downstream of admission — readback, drift detection, and any later
migration attestation — assumes one thing: **the source a reader can audit is
the code the device runs.** A bundle that can break that correspondence defeats
readback without tripping it, and the two ways to break it are both properties
of CPython's import machinery rather than of anything in this codebase.

#### Fact one — an extension module resolves before source

`importlib`'s `FileFinder` tries suffix groups in a fixed order:
`EXTENSION_SUFFIXES`, then `SOURCE_SUFFIXES`, then `BYTECODE_SUFFIXES`. On this
runtime those are `['.cpython-311-x86_64-linux-gnu.so', '.abi3.so', '.so']`,
`['.py']` and `['.pyc']` respectively. **[verified here]**

Measured directly: a package containing a valid `probe.py` and a 16-byte
non-ELF `probe.so`, imported in a fresh interpreter after
`importlib.invalidate_caches()`, resolves to

```
find_spec origin  : .../shadowpkg/probe.so
find_spec loader  : ExtensionFileLoader
import raised     : ImportError .../probe.so: file too short
```

**[verified here]** The `.so` wins outright. It does not fall through to the
source when it fails to load; the import raises. A well-formed `.so` would
simply have run instead of the `.py`, and nothing about the `.py` would have
been consulted.

#### Fact two — a stale `.pyc` whose header matches its `.py` runs instead of it

The timestamp-invalidation `.pyc` header records the source's mtime and size.
If both still match, CPython uses the cached bytecode and never reads the
source. Nothing in the header covers the source's *content*.

Measured directly: write `probe.py` containing `VERSION = 1`, import it to
produce `__pycache__/probe.cpython-311.pyc`, then rewrite the source to
`VERSION = 2` — the same twelve bytes, and `os.utime` restores the original
mtime. In a **fresh interpreter**, after `importlib.invalidate_caches()`:

```
fresh interpreter VERSION: 1
__file__                 : .../stalepkg/probe.py
source bytes on disk     : VERSION = 2
```

Deleting `__pycache__` and repeating returns `2`. **[verified here]**

Note `__file__`. It names the `.py`. Every ordinary way of asking the running
process where its code came from answers with the file whose contents were not
executed.

`docs/orchestration/FINDINGS-plugin-contract.md` §2 originally recorded this
as *agent-measured, not reproduced here*. It has since been reproduced twice
independently — by the orchestrator, recorded in that file's resolution
section, and again here on Python 3.11.15 for this document. Provenance on it
is now first-hand.

### 4.2 Why readback structurally cannot catch either

Readback exists to answer one question: does the device's disk match what the
server sent? `readback_for(manifest_sha256, root)` re-reads the placed tree from
disk and hashes those bytes; the server independently recomputes the expected
tree hash from the bundle it still holds. The comparison means something
precisely because the two sides are derived from different sources — that is
invariant 4, and `readback_for` takes a root rather than a file list so that
hashing the received bundle is not expressible.

Neither shadowing case is a disagreement between those two sources. **The
shadowing file is in the bundle.** The server's expectation includes it. The
device's disk contains it. Both sides compute the same tree hash and agree, and
the install is reported clean.

That is not readback being weak at this; it is readback being asked a question
that cannot reach the failure. Readback compares two derivations of the *file
set*. The attack does not change the file set — it changes which member of the
file set the interpreter executes. No amount of hashing on either side
distinguishes "these files are what was sent" from "one of these files shadows
another".

So the refusal has to be at admission, before anything reaches disk. There is no
later checkpoint that could hold it. That is the entire argument for the rule,
and it is the argument to re-examine before weakening it.

### 4.3 Why the suffix list is fixed rather than derived

The obvious implementation is
`importlib.machinery.EXTENSION_SUFFIXES + BYTECODE_SUFFIXES`. It was
deliberately not used.

The server half must refuse the same set as the device half, and the server half
is Go. A list that moves with the *device's* CPython version and platform cannot
be mirrored in a language that has no CPython to ask — `EXTENSION_SUFFIXES`
already differs between Linux and Windows builds, and a device that grew a
suffix the server had never heard of would produce an asymmetry that shows up as
one side pushing what the other refuses.

The four-element list is therefore contract, spelled identically in
`kvmd/pluginmgr/bundle.py` and `kazbek`'s `internal/plugins/bundle.go`:
`.pyc`, `.pyo`, `.pyd`, `.so`. **[verified here]** `.so` was chosen as a plain
suffix because `.abi3.so` and `.cpython-<ver>-<plat>.so` both end with it, so
one entry covers the whole extension family without enumerating platforms.

The cost of freezing the list is that CPython could grow an importable suffix
the list does not cover. That cost is paid down by
`test_the_import_precedence_this_refusal_rests_on`, which asserts that every
suffix the *runtime* reports as importable is covered:

```python
shadowing = set(machinery.EXTENSION_SUFFIXES) | set(machinery.BYTECODE_SUFFIXES)
for suffix in shadowing:
    assert suffix.lower().endswith((".pyc", ".pyo", ".pyd", ".so"))
```

That is the important direction. A CPython change that widens the hole reddens
the *reason* the rule exists rather than silently widening the rule's blind
spot. It is one-directional on purpose: the list may cover suffixes the runtime
does not report, and that is fine.

Two of the four are exactly that case today. On this runtime
`BYTECODE_SUFFIXES` is `['.pyc']` and `EXTENSION_SUFFIXES` contains no `.pyd`.
**[verified here]** `.pyo` has not been importable since PEP 488 (Python 3.5) and
`.pyd` is a Windows extension suffix. They are in the list defensively: they
cost nothing, they guard other platforms and older runtimes, and a bundle author
has no legitimate reason to ship either.

### 4.4 What the rule deliberately does not refuse

Two near-misses were measured rather than assumed, because a rule that
over-refuses gets relaxed by whoever hits it, and a relaxation is where the
weakening happens.

**A directory whose name ends in `.so` does not shadow.** A bundle carrying
`plugins/ugpio/a.so/x.py` is accepted. Measured: with a real directory named
`probe.so` beside `probe.py`, `find_spec` resolves to `probe.py` with
`SourceFileLoader` and the import returns the source's value. **[verified here]**
`FileFinder` checks the file cache for extension suffixes, not the directory
cache, so a directory cannot occupy an extension slot. Refusing it would be
over-refusal.

**A source file named `__pycache__.py` is accepted.** The segment check compares
whole path segments, so `plugins/ugpio/__pycache__.py` is a `.py` named
`__pycache__`, not a cache directory. **[verified here]** It could not be a
plugin entry in any case: `_NAME_RE` in `kvmd/pluginmgr/manifest.py` forbids a
leading underscore, mirroring `get_plugin_class`, which already treats a leading
`_` as unknown.

**Ordinary files with dots in the stem are accepted.**
`plugins/ugpio/lib.python.helper.py` passes; the check is on the suffix, not on
the presence of a dot. `test_bundle_accepts_ordinary_entries` exists as the
guard against over-refusal and carries exactly that case.

### 4.5 Mutation results

The rule is mutation-checked. Each mutation below was applied to a scratch copy
of the tree — never to the repository — and the full `pluginmgr` suite re-run.
**[verified here]**

| Mutation to `kvmd/pluginmgr/bundle.py` | Result |
|---|---|
| baseline | 143 passed |
| drop the `_check_not_importable_ahead_of_source(name)` call | **9 failed** |
| drop the `__pycache__` segment clause | **1 failed** |
| drop `.so` from `_SHADOWING_SUFFIXES` | **4 failed** |
| make the suffix match case-sensitive (`lowered = name`) | **1 failed** |

The counts are informative, not just non-zero. Dropping the `__pycache__` clause
reddens exactly one case — `plugins/ugpio/__pycache__/anything.txt` — because
every other `__pycache__` case in the suite also ends in `.pyc` and is caught by
the suffix clause. That is the clause earning its place: without it, a
`__pycache__` directory could still be delivered as long as nothing in it looked
like bytecode, and the directory is the thing the interpreter consults.

These were run at `622c6d3`, where the baseline is 143. Re-run at `1355993`,
where the baseline is **150**, all four still bite and the failure counts are
unchanged: 9, 1, 4, 1. The suite grew by three shared vectors (`12ec53c`) and
four mutation-closing tests (`252c488`) in between. **[verified here]**

### 4.6 The two halves refuse the same set

The device half refuses at `_check_not_importable_ahead_of_source`; the server
half refuses at `checkNotImportableAheadOfSource`
(`kazbek`, `internal/plugins/bundle.go`), with the identical four-element list
and the identical `__pycache__` segment clause. **[verified here]**

The server refusing is not redundant with the device refusing. Invariant 5's
second half is that each side verifies independently and neither defers to the
other's verdict; a server that pushed one of these would be pushing a bundle it
could not itself verify.

Three shared vectors now hold both halves to it — `unsafe-bytecode-cache`,
`unsafe-native-extension` and `unsafe-sourceless-bytecode` in
`contract/plugins/vectors/bundles.json`. Before those landed, the two
implementations agreed by construction and not by contract. I ran both suites at
the current state: `testenv/tests/pluginmgr` is **150 passed** at `1355993`,
and the whole Python suite is **1127 passed, 2 skipped**; Go reports
`ok rttys/internal/plugins` at `450ca39`, with all three new subtests passing
under `TestBundleVectors`. **[verified here]**

The `contract/plugins` tree is byte-identical between the two repositories at
these refs. **[verified here]**

The tree hash is deliberately not quoted here. It moves with any change to a
spec file or a vector, and it moved three times on 2026-09-10 alone
(`c2dc4976…` → `4888f9ea…` → `d14ad81f…`); an earlier draft of this document
pinned a value that was stale before it was committed. Recompute instead:

```sh
python3 contract/plugins/tools/contracthash.py contract/plugins
cat contract/plugins/CONTRACT-SHA256          # must be identical
diff -r contract/plugins ../kazbek/contract/plugins   # must be empty
```

The first two agreeing is what `test_contract_sha256` asserts; the third is
what nothing asserts, because neither repo can see the other.

---

## 5. What would justify changing the refusal list

This is the section to read before editing `_SHADOWING_SUFFIXES` or the
`__pycache__` clause.

**A request to ship compiled extensions is not sufficient.** The rule is not
about compiled code being distasteful. It is about the loader resolving a
compiled file ahead of the source that the manifest declares and that a reviewer
would read. Shipping a `.so` is a coherent thing to want; shipping it under a
name that shadows a declared `.py` is not. If native extensions ever need to be
supported, the change is not to remove the suffix — it is to give them a
placement location the plugin loader does not search by dotted name, and to make
`entry` unable to name one. Removing `.so` from the list without doing that
re-opens fact one exactly as it was.

**A change in CPython's resolution order would justify a change, and the suite
will tell you.** `test_the_import_precedence_this_refusal_rests_on` asserts
`.so` is still in `EXTENSION_SUFFIXES`, `SOURCE_SUFFIXES == ['.py']`, `.pyc` is
still in `BYTECODE_SUFFIXES`, and every importable suffix the runtime reports is
covered by the list. If that test goes red, read the failure before touching the
rule: the failure is the reason moving, not the rule breaking.

**A readback change never justifies relaxing this.** The recurring temptation is
"readback will catch it". Section 4.2 is the answer, and it is structural rather
than a matter of readback's current strength. Any proposal to relax admission on
the strength of a downstream check has to explain how a check comparing two
derivations of the same file set distinguishes shadowing, and there is no such
explanation.

**A source-level review step never justifies relaxing this either.** Fact two's
whole content is that the source and the executed code differ while `__file__`
names the source. A reviewer reading the `.py` is reading the file that did not
run.

**What would justify a narrowing** is a measured demonstration that a specific
suffix cannot shadow on any platform the contract targets — the way a directory
named `a.so` was measured not to shadow in section 4.4. Measure it; do not
reason about it. `.pyo` and `.pyd` are the plausible candidates and they are also
the two whose removal buys nothing.

**What would justify a widening** is any new evidence that some other entry
shape reaches the interpreter ahead of the declared source. The class to watch
is not "file extensions" but "anything a loader consults before opening the
`.py`": `.pth` files, a `sitecustomize` or `usercustomize` module, a
`__init__.py` that replaces the family's own, and namespace-package shadowing are
all in that class and none of them is covered by a suffix list. Section 6 is
about the closest live instance.

---

## 6. What admission still does not close

`require_entry` asserts the declared entry is *present*. It has never asserted
that it is *alone*, and `622c6d3` closed only the import-precedence half of
that. **This is an open design decision, not a defect awaiting a patch** — an
audit pass confirmed the import-precedence half and left this half open
deliberately, because the three candidate constraints below differ in what
they forbid and the choice belongs with placement. The following bundles all pass `read_bundle` and `require_entry` today
against a manifest declaring `plugins/ugpio/acme_relay.py`. **[verified here]**

| Extra entry alongside the declared one | Result |
|---|---|
| `plugins/ugpio/__init__.py` | accepted |
| `plugins/atx/__init__.py` | accepted |
| `plugins/auth/pam.py` | accepted |
| `plugins/ugpio/os.py` | accepted |
| `plugins/msd/otg/drive.py` | accepted |
| `unrelated/top.py` | accepted |
| `plugins/../../../etc/passwd.py` | refused, `bundle.unsafe_path` |

Traversal is closed. Everything else is a question for the placement layer that
does not exist yet, and it should be settled there rather than discovered.
`kvmd/plugins/ugpio/__init__.py` is a real 3,545-byte file in this tree
containing the `ugpio` family's base classes; a bundle can name that path today.
Whether naming it means anything depends entirely on how placement resolves a
bundle path against the loader-owned root — which is exactly the decision the
placement layer will make.

Note that this residual has the same shape as the one section 4 closed, and it
is invisible to readback for the same reason: the extra file is in the bundle,
so both sides hash it and agree. Three candidate constraints, in increasing
strictness, are (a) refuse any entry outside `plugins/<type>/<name>/` and the
declared entry itself, (b) refuse any entry whose `plugins/<type>` prefix
disagrees with the manifest's `type`, or (c) refuse any entry that would
overwrite a file the base image already ships. This document does not pick one;
it records that the choice is open and that placement is where it belongs.

### 6.1 What pins `require_entry`

`require_entry` is mutation-covered. An audit found that relaxing `==` to
`endswith` left the whole suite green; a first test closed that and nothing
else, because one decoy can only defeat one relation. The assertion now carries
three decoys, the set of all three together, and the honest member so a check
refusing everything also fails.

Re-measured at `f22e718` with bytecode disabled (`python -B`,
`PYTHONDONTWRITEBYTECODE=1`, cache cleared) against a baseline of 155:

| Mutation to `require_entry` | Suite | Decoy that catches it |
|---|---|---|
| `f.path == entry` → `f.path.endswith(entry)` | **1 failed** | `evil/plugins/ugpio/acme_relay.py` |
| `f.path == entry` → `f.path.startswith(entry)` | **1 failed** | `plugins/ugpio/acme_relay.pyzzz` |
| `f.path == entry` → `entry in f.path` | **1 failed** | `xx/plugins/ugpio/acme_relay.pyzz` |

An earlier draft of this document recorded `startswith` as still silent, which
was true when it was written and was closed in `9e8f636`.

**Read the bytecode warning in `docs/orchestration/WORKING-AGREEMENT.md` before
reproducing any of this.** These exact two variants are the same length, and a
mutation harness that restores by `cp` without clearing `__pycache__` will keep
executing the mutation while the source reads `==`. That happened here.

What `require_entry` still does NOT assert is that the declared entry is
**alone** — see the open question at the end of §6.

### 6.2 `read_placed_tree`'s symlink guard is now pinned too

The same audit found that deleting `os.path.islink(full) or` from
`read_placed_tree` left the suite green, so a symlink planted under the
placement root after placement was followed, its target hashed, and reported as
an ordinary regular entry. Noticing exactly that is why readback exists, so the
guard was load-bearing and unobserved. `252c488` pins it; the mutation now
reddens one test, and so does replacing the call with a constant `False`.
**[verified here]**

---

## 7. Readback must run before load, and the new rule makes that sharper

Importing a placed plugin writes `__pycache__` into the placed tree, which
changes the tree hash. Measured against `readback_for` directly:

```
readback BEFORE load : 7d72f438...
  entries: plugins/__init__.py, plugins/ugpio/__init__.py, plugins/ugpio/probe3.py
readback AFTER load  : a374f864...
  entries: ... plus plugins/__pycache__/__init__.cpython-311.pyc,
                    plugins/ugpio/__pycache__/__init__.cpython-311.pyc,
                    plugins/ugpio/__pycache__/probe3.cpython-311.pyc
```

**[verified here]** This reproduces
`docs/orchestration/FINDINGS-plugin-contract.md` §3, which originally recorded
it as agent-measured and unreproduced; it has since been reproduced by the
orchestrator as well. A naive `place → load → readback` ordering reports
`install.readback_mismatch` on **every** successful install.

The fix is free — read back before loading — and there is nothing to fix yet,
because the install driver is not in the tree. What exists instead is the
constraint recorded where someone would undo it: `readback_for`'s docstring in
`kvmd/pluginmgr/bundle.py` carries the ordering rule, the measured before and
after hashes, and the warning below (commit `fd1036d`).

The new admission rule makes the constraint sharper rather than redundant. The
`__pycache__` entries the loader writes are precisely the entries admission now
refuses, so after a load the placed tree can never equal the bundle: it contains
paths that could not have come from a bundle at all. Whoever writes the install
driver should pin the ordering with a test, because the bug only appears once
something imports, and should assert "nothing touched disk" by before-and-after
tree hashing of the store root rather than by permissions — an attempt to model
a read-only remount with `chmod 0555` failed, because the import wrote through
the 0555 directory as root anyway. **[reported]**, from
`FINDINGS-plugin-contract.md` §3 and now also from `readback_for`'s docstring;
the tree-hash assertion is strictly stronger than the permissions one and needs
no device.

---

## 8. How each claim here was checked

| Claim | Method |
|---|---|
| The refusal table in section 3 | `read_bundle` invoked against a synthesised ustar per row |
| Check ordering | read from `kvmd/pluginmgr/bundle.py` and confirmed by the codes the table returns |
| `.so` resolves before `.py` | fresh-interpreter `find_spec` + `import_module` with a 16-byte non-ELF `.so` |
| A matching-header `.pyc` runs instead of its `.py` | rewrite source at identical size, restore mtime, import in a fresh interpreter |
| Suffix coverage | `importlib.machinery` suffix lists read from the runtime |
| Directory named `a.so` does not shadow | `find_spec` against a real directory of that name |
| Four mutations bite | applied to a scratch copy of the tree, full `pluginmgr` suite re-run; re-run at `1355993` with unchanged counts |
| `require_entry` reddens under `endswith`, `startswith` and `in` | three decoys, one per relation; re-run at `f22e718` with bytecode disabled |
| The proposed four-member vector closes all three | drafted in scratch, run against each mutation |
| `read_placed_tree` symlink guard is pinned | mutation applied two ways, one test reddens each |
| Python suite 132 → 143 → 146 → 150 → 155 | `git archive` of `622c6d3^` and `622c6d3` into scratch, plus the current tree |
| Whole Python suite 1127 passed, 2 skipped | `pytest testenv/tests kvmd` at `1355993` |
| Go half refuses the same set | `internal/plugins/bundle.go` read; `go test -count=1 ./internal/plugins/` |
| Contract byte-identity | `diff -r` between the two repos; `tools/contracthash.py` recomputed in both, compared against the recorded file |
| No production caller | repo-wide grep, plus the absence of any placement or install function |
| `kvmd.pluginmgr` now in `setup.py`, four packages still missing | on-disk `__init__.py` walk compared against the declared `packages` list |
| Load poisons readback | `readback_for` before and after importing from the placed root |
| `chmod 0555` does not model a ro remount | **[reported]**, not reproduced here |

---

## 9. Where this is enforced

None of the above was enforced by CI until 2026-09-10. `.github/workflows/tox.yml`
was gated on a branch that does not exist, so the suite had never run on any push
or pull request in the life of the fork, and `kazbek` had no test job at all. Both
are fixed on this branch only — five of six refs in `glkvm-debloat`, `main`
included, still carry the old filter. See [`../ci.md`](../ci.md) for what runs
where and what remains to be propagated; the short version is that a green local
run is currently the only enforcement these refusals have.
