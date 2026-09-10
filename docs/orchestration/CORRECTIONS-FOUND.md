# Corrections found while documenting the plugin work — 2026-09-10

Each entry names the document and line, what it claims, what was measured, and
the command that measured it. **Nothing here has been edited in place** — this
is a report, per the staging instruction. Where an item is superseded by work
that landed while this was being written, that is said.

Measured against `claude/repo-status-report-6vi5r1` at `030b52b`
(`glkvm-debloat`) and `8853e50` (`kazbek`, local branch of the same name).
Python environment for every count: **3.11.15**, `pytest 9.1.1`,
`pytest-asyncio 1.4.0`, `pytest-aiohttp 1.1.1`, `pytest-mock 3.15.1`,
`aiohttp 3.14.3`, `aiohttp-basicauth 1.2.0`, `bcrypt 4.0.1`, `passlib 1.7.4` —
the reconstructed virtualenv, not the staged `testenv`. Go: **1.24.7**. Named
because a missing test dependency presents here as a failure and not as a skip.

Items 1–6 are in the **normative contract**, which is vendored byte-identically
into both repositories. Correcting any of them moves `CONTRACT-SHA256` and must
be done in both repos in the same cycle.

---

## 1. `contract/plugins/wire.md:95, 110, 174, 197` — every message-body example still says `"v":1`

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

## 2. `contract/plugins/manifest.md:198-199` — names a field that no longer exists, and calls a required field optional

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

## 3. `contract/plugins/errors.md:46` — `bundle.unsafe_entry` is described as one trigger and has four

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

## 4. `contract/plugins/wire.md:253-257` — the bundle rejection list does not mention the rule both halves now enforce

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

## 5. `contract/plugins/wire.md:257` — "NFC-safe printable ASCII" describes a property nothing checks

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

## 6. `setup.py:67-106` — `kvmd.pluginmgr` is not in `packages`

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

## 7. Commit `9da389a` message — "the bundle path checks run before the verifier"

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

## 8. `docs/orchestration/FINDINGS-plugin-contract.md:78` — the stated build blocker does not reproduce

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

## Suite counts at the refs above

| Suite | Count | Ref |
|---|---|---|
| `testenv/tests/pluginmgr` | 132 passed | `622c6d3^` (via `git archive` to scratch) |
| `testenv/tests/pluginmgr` | 143 passed | `622c6d3` |
| `testenv/tests/pluginmgr` | **146 passed** | `030b52b` |
| `go test ./internal/plugins/` | `ok` | `8853e50` |

The 132 → 143 and 143 → 146 transitions match what commits `622c6d3` and
`12ec53c` claim.
