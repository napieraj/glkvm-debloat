# The plugin contract — orientation

The plugin foundation spans two repositories in two languages and meets at
exactly one seam. This document orients a reader in that seam: what is shared,
what each half owns, which decisions are deliberate, and where the two are not
yet symmetric. It is an index with reasons, not a specification — the
specification is `contract/plugins/`, and where this document and that
directory disagree, that directory wins.

Measured against `claude/repo-status-report-6vi5r1` at `030b52b` in
`glkvm-debloat` and at `8853e50` in `kazbek` (a local branch of the same name,
ahead of `origin/claude/new-session-2w6w30`). The branch was moving while this
was written; re-derive before acting on any figure here. Environment for every count:
Python **3.11.15**, `pytest 9.1.1`, reconstructed virtualenv rather than the
staged `testenv`, invoked as
`PYTHONPATH=/home/user/glkvm-debloat <venv>/bin/python -m pytest <path> -q -p no:cacheprovider`;
Go **1.24.7**, `go test -count=1 ./internal/plugins/`. Named because a missing
test dependency presents here as a failure and not as a skip.

---

## 1. Two implementations, one contract, no dependency

| Repo | Role | Language | Implementation |
|---|---|---|---|
| `glkvm-debloat` | device | Python | `kvmd/pluginmgr/` |
| `kazbek` | server | Go | `internal/plugins/` |

Neither repository depends on the other. They meet only at
`contract/plugins/`, which is vendored **byte-identically** into both. At the
refs above the two copies are byte-identical — verified with a recursive diff of
the two trees — and `CONTRACT-SHA256` recomputes in both to
`d14ad81fadd7862449bf24e8fdf69c82f6f242e098162ebb9f34299faa5d5d72`.

That value moves with any change to the spec files or the vectors -- it moved
twice on 2026-09-10 alone. Do not trust a hash quoted in prose; recompute with
`python contract/plugins/tools/contracthash.py contract/plugins` and compare
against `contract/plugins/CONTRACT-SHA256`, which is what the suite asserts.

The device half lives in `kvmd/pluginmgr/` and not in `kvmd/plugins/` on
purpose. `kvmd/plugins/` is the plugin *tree* that `get_plugin_class()` imports
from; a manager placed under it would look like a plugin type to the loader.

The device half currently has **no production caller**: a repo-wide grep for
`read_bundle`, `admit_offer`, `gate_named`, `readback_for` and
`read_placed_tree` returns hits only inside `kvmd/pluginmgr/` and its tests, and
there is no placement, rollback or install driver in the tree. It is a
foundation waiting for its placement layer, and `kvmd.pluginmgr` is also absent
from `setup.py`'s `packages` list, which whoever wires it will have to fix.

---

## 2. `CONTRACT-SHA256` — what it covers and what it deliberately excludes

`CONTRACT-SHA256` is the canonical tree hash of the *normative* contract. Each
repo has a test that recomputes it over its own vendored copy, so a one-sided
edit fails that repo's own suite instead of surfacing at integration time
months later. On the Python side that test is `test_contract_sha256` in
`testenv/tests/pluginmgr/test_contract.py`.

Two paths are excluded:

- **`CONTRACT-SHA256` itself**, which cannot contain its own hash.
- **`tools/`**, which is machinery rather than contract. Editing a comment in
  the vector generator would otherwise move the hash without the contract
  meaning anything different, and every repo that had not yet pulled the
  cosmetic edit would report a spurious mismatch. A generator change that
  *actually* changes the vectors still moves the hash, because `vectors/` is
  inside the hashed set.

The algorithm is deliberately the same one as the readback tree hash defined in
`wire.md`: one hashing algorithm in this contract, not two, so each repo
verifies contract sync with the function it already had to implement and test.

Two properties of this arrangement were checked rather than assumed. The
vectors regenerate reproducibly: copying `contract/plugins` to scratch, running
`python3 tools/genvectors.py vectors`, and diffing against the committed
`vectors/` produces no difference, and the recomputed hash matches the recorded
one. And the sync alarm fires as designed — commit `12ec53c` records that
`test_contract_sha256` went red the moment the vectors changed and before the
recorded hash was updated, which is exactly the one-sided-edit alarm it exists
to be.

---

## 3. Protocol v2

`PROTOCOL_VERSION = 2`, carried as `"v"` in every JSON body.
`encode_json_body` stamps it so no caller can forget, and `decode_json_body`
refuses any other value with `manifest.unsupported_version` rather than
guessing: a message from a future protocol is not a message with unknown fields
to ignore, it is a message whose meaning is unknown.

v2 differs from v1 by three manifest changes. Because unknown manifest fields
are **refused** rather than ignored, none of the three could be added
compatibly — which is the version bump working as designed rather than a cost
of it. Strictness here buys the property that a device and a server can never
disagree about what a manifest said, and gives back forward compatibility,
which is bought back deliberately by bumping `v`.

### 3.1 `revision` — monotonic, and equal is refused

A mandatory integer `>= 1`. The device refuses any offer whose `revision` is
less than **or equal to** the revision already installed for that `name`, with
`policy.rollback_refused`.

Equal is refused as well as lower because the attack class has two halves.
Lower is the downgrade — re-serving a genuinely authored older plugin with a
known flaw. Equal is the freeze — re-serving the current one forever to prevent
an upgrade. Idempotent re-push is not what `revision` handles; that is handled
by the payload-hash `noop` path, which compares what is actually installed.

The check runs at **offer admission**, before a `fetch` is sent and before any
byte moves, because the device already knows its installed revision and there
is no reason to transfer a bundle it will reject. The refusal is
`state:"refused"`, not `"failed"`, because nothing touched the disk.

It lands now, ahead of signing, because it needs no trust model: it is an
integer comparison. `check_revision` in `kvmd/pluginmgr/gate.py` and
`CheckRevision` in `internal/plugins/gate.go` are the same two lines in two
languages.

### 3.2 `signature` — required, one accepted model, `entries` enforced empty

The block is `{model, entries, threshold?, expires?}` and is **required**, not
optional. v2 accepts `model: "hash-only"` and nothing else, and requires
`entries` to be empty; both violations are `manifest.malformed`.

Required rather than optional is the load-bearing choice. An optional block
leaves "unsigned" and "signature omitted" indistinguishable, and that ambiguity
is where a downgrade attack lives. Because the block is always present and
always states its model, a later `signed` verifier can refuse
`model: "hash-only"` outright instead of inferring intent from an absent field.

A non-empty `entries` is refused because a v2 implementation cannot check a
signature and must not accept a manifest that claims one. Accepting and
ignoring it would be the worst of the three options: it would let a manifest
assert a property nothing verified.

This shape is also why deferring the signing module costs nothing. Per D-016 no
second signature model lands this cycle; adding a value to the enum later does
not cost a version bump across both implementations, because the field already
exists and is already required.

### 3.3 `sandbox` — reserved, must be empty, and deliberately not `capabilities`

Optional. Absent or empty is accepted; anything else is
`manifest.sandbox_not_allowed`. The field is reserved so a vocabulary can land
without a schema migration, and refused until that vocabulary exists, because a
permission that displays and does not hold at an enforcement point is a hidden
button. D-017 records that the vocabulary stays empty until an entry has a named
enforcement point that exists.

The name matters. `kazbek` already has a capability vocabulary:
`permission.Key` values such as `device.read` and `auth.write`, which
`middleware.Require` calls "capability keys" and which are scoped to
**subjects** — which user may perform which action. What `sandbox` will describe
is a different thing entirely: which resources a plugin **process** may touch.
Two vocabularies under one word, in a system whose whole authorization model
turns on that word, is a bug waiting to be written by someone who reads the
wrong one.

The two vocabularies already touch the same subject once:
`internal/authz/model.go:55` on `claude/glkvm-stock-debloat-migration-0pibl7`
declares `CapPluginInstall Capability = "plugin.install"`, and it is in
`AllCapabilities`. That does not change D-017 — plugin installation being a
named *subject* capability is orthogonal to what a plugin *process* may reach —
but it is worth knowing that the collision the rename avoided is not
hypothetical.

### 3.4 The rest of the schema, briefly

`name` matches `^[a-z][a-z0-9_]{0,31}$` because it becomes
`kvmd.plugins.<type>.<name>` at import time, and leading underscores are
excluded because `get_plugin_class` already treats a leading `_` as unknown.
`type` is one of `atx`, `msd`, `hid`, `ugpio`, `auth` — the sub-directories that
exist under `kvmd/plugins/`. `runtime` is `device` or `management` and is never
defaulted, because defaulting a security tier is how tiers stop meaning
anything. `entry` must match `plugins/<type>/<name>.py` **and** agree with the
`type` and `name` fields, reported as `manifest.entry_type_mismatch` and
`manifest.entry_name_mismatch`.

`entry` is a description of the bundle's shape, never an instruction about where
to write. The loader derives the on-disk location from `type` and `name` and
cross-checks `entry` against that derivation; a disagreement is a refusal, never
a redirection. That is invariant 1, and it is why no input in the manifest can
move the write.

---

## 4. The `Verifier` seam

```
Verify(manifest, payload) -> ok | reason
```

Success is silent; refusal carries a code from `errors.md`. In Python the
refusal is a raised `VerifyError`; in Go it is a returned `*RefusalError`. The
two shapes are idiomatic in their own languages and semantically identical.

| Name | Status | Behaviour |
|---|---|---|
| `noop` | dev only | accepts any payload |
| `hash-only` | the v1 floor | refuses unless `sha256(payload)` equals `manifest.payload.sha256` |
| `signed` | later | not in this cycle |
| `always-fail` | test only | refuses everything; not resolvable by name |

Signing is deferred; the place signing will go is not. Everything downstream of
this interface — transport, placement, rollback, readback — is identical
whichever crypto eventually lands, so the crypto is a hook, and the hook is
specified now and filled later.

`resolve()` fails closed. An absent name, an unrecognised name and `"signed"`
all raise `verify.unconfigured` rather than falling back to `noop`; a config
typo must not become an open door. `always-fail` is deliberately not resolvable
either, so a test-only refuser cannot be named in a config —
`test_always_fail_is_not_resolvable` asserts that.

**`noop` disables authenticity checking, not path safety.** That distinction is
the entire reason `noop` is tolerable in a tree at all. The structural checks —
manifest validation, the payload length check, and every bundle path rule — run
for every verifier including `noop`. A `noop` verifier still cannot be used to
write outside the loader-owned root, install a mismatched module name, or ship
an oversized bundle.

One caveat, recorded rather than closed, and worth understanding because the
obvious fix is wrong. `resolve("noop")` / `Resolve("noop")` succeeds in both
halves, so a config naming `noop` would silently disable authenticity, and
`verifier.md`'s "never a default in any real config" is prose that nothing
enforces.

It cannot be enforced at `resolve()`. The shared vectors in `verify.json`
exercise `noop`, so removing it there would break the conformance suite that
proves the two halves agree. And it is not live today: `resolve()`'s only
caller is `gate_named()`, whose only caller is the vector suite, so nothing
reaches it from configuration. The constraint therefore belongs at the boundary
where a verifier name first arrives from a config file — a boundary that does
not exist yet. It is recorded at both language definitions
(`kvmd/pluginmgr/verifier.py` and `internal/plugins/verifier.go`, commits
`e79cf88` and `8853e50`) naming whoever wires that boundary as its owner.
**[reported]** for the reachability measurement, from
`docs/orchestration/FINDINGS-plugin-contract.md` §5 and its resolution
section; not re-derived here.

---

## 5. The gate, and admission as a separate check

Both halves call **the gate** and never a `Verifier` directly. That is what
makes invariant 3 a single testable claim rather than a property scattered
across two codebases and two languages.

```
Gate(verifier, manifest, payload):
    1. validate the manifest            -> a manifest.* code
    2. len(payload) == payload.size     -> payload.size_mismatch
    3. verifier.Verify(manifest, payload)
```

The step order is contract, not implementation detail: the vectors assert which
code comes back when a manifest is invalid *and* the payload is corrupt, so the
two implementations cannot diverge on precedence. Steps 1 and 2 run before the
verifier and for every verifier. Step 2 is not redundant with `hash-only` — it
bounds the work done before hashing, and it still holds when the configured
verifier does not hash at all.

The contract on every caller is the load-bearing part:

> If the gate refuses, the caller MUST NOT unpack, place, or load. Nothing may
> touch the disk.

`admit_offer` / `AdmitOffer` is a separate check running earlier, on the offer
alone, and it takes no payload argument at all — which makes "before the first
chunk" structural rather than a convention. It validates the manifest (catching
`manifest.payload_too_large` for an oversized *declaration*) and compares
`revision`. Gate step 2 compares the *assembled* length against the declared
size and cannot run until the bytes have arrived. Neither substitutes for the
other.

The gate deliberately does **not** decide compatibility (`model_compat`,
`firmware_compat`) and does not enforce the runtime tier. Those are policy
decisions belonging to the side doing the loading. Keeping policy out of the
gate keeps the gate's single claim — "unverified plugins do not reach the disk"
— small enough to be obviously true.

For what happens after the gate, at bundle read, see
[`admission.md`](admission.md).

### 5.1 The uint16 envelope, and a bound that was only enforced on one layer

The rtty envelope's length field is a uint16, so a frame body is at most 65535
bytes. This is the single hardest constraint on the design and the reason
payloads are chunked at all — a plugin bundle does not fit in a frame and never
will. `PAYLOAD_CHUNK_MAX` is 32768, which leaves clear headroom under the
65502-byte ceiling and is a size an embedded device can buffer without thought.

`encode_frame` and `EncodeFrame` both refuse a body that exceeds the envelope.
The transport underneath them did not: `Device.WriteMsg` in `kazbek`'s
`internal/server/device.go` wrote `uint16(len(sid)+len(data))` unbounded, so a
70000-byte body declared 4464 and wrote all 70000 bytes with a nil error. That
is frame desynchronisation rather than truncation — the peer reads 4464 bytes
as the message and parses the remaining ~65k as further frames. Fixed in
`98250c3`; the plugin layer had been correct and the layer beneath it had not.
**[reported]**, from that commit and from
`docs/orchestration/FINDINGS-plugin-contract.md` §4 and its resolution; the
reproduction was over `net.Pipe` and is not re-derived here.

---

## 6. `refused` versus `failed`

`install_result.state` is one of `installed`, `noop`, `refused`, `failed`. The
last two are deliberately distinct and must not be collapsed.

| State | Meaning |
|---|---|
| `refused` | the gate said no. **Nothing was unpacked, placed or loaded.** |
| `failed` | verification passed, then place-or-load failed. The install was rolled back. |

`refused` is the observable signature of invariant 3. It is the only way the
*server* can tell that the device's disk was never touched, and collapsing the
two states would make invariant 3 untestable from the server's side. `reason` is
a code from `errors.md` and never prose, so the server can act on it; the
human-readable detail carried alongside a `RefusalError` is for operators and is
deliberately never parsed.

---

## 7. Readback: the device derives from disk, the server from the bundle

An `installed` result is not terminal. The server holds the install open until a
`readback` arrives.

> The device MUST re-read the placed files from the loader-owned location and
> hash those bytes. It MUST NOT hash the bundle it received.

`readback_for(manifest_sha256, root)` takes a **root**, not a file list, so
hashing the received bundle is not expressible in the API. That is the design
being enforced by shape rather than by discipline.

The reason is the whole point of the message. Hashing the received bundle
restates what chunk sequencing already proved and says nothing about the disk.
The two values agree only in the happy path and differ in exactly the cases
readback exists for: a partial write, a failed rename, an overlay that did not
survive the read-only remount, or a later local edit. The device derives its
side from the disk, the server derives its side from the bundle it still holds,
and **the comparison is meaningful precisely because the two sources are
different**. Compute both from the same bytes and it proves nothing.

Per-file `entries` are capped at 64; a larger tree reports `tree_sha256` only,
and the tree hash still tells the server that drift happened. Paths are sorted
on their UTF-8 bytes rather than as `str`, because Python's `str` ordering is by
code point and diverges from bytewise ordering above U+007F — the two agree
today because paths are restricted to printable ASCII, and sorting on bytes
keeps them agreeing if that restriction is ever relaxed.

Readback has one structural blind spot, and it is the reason the newest
admission rule exists: it cannot detect anything that is *in the bundle*, because
then both sides hash it and agree. That is the argument in
[`admission.md`](admission.md) §4.2, and it is why entries that shadow the
declared source have to be refused at admission rather than caught later.

Two ordering facts for whoever writes the install driver: readback must run
**before** load, because importing writes `__pycache__` into the placed tree and
changes the hash (reproduced — see `admission.md` §7); and "nothing touched
disk" must be asserted by before-and-after tree hashing of the store root, never
by directory permissions.

---

## 8. Invariants 1–6, and where each is asserted

`contract/plugins/invariants.md` writes the six invariants as a test contract.
**now** means assertable in this cycle against the stub verifiers; **half**
means asserted by whichever repo owns the behaviour.

| # | Claim | Status |
|---|---|---|
| 1 | A plugin loads only from a loader-owned location | now (validation) + half (placement) |
| 2 | Push is idempotent | half — the device owns the truth about its own disk |
| 3 | A failed verify refuses install | now (the gate refuses) + half (nothing reaches disk) |
| 4 | Read-back is mandatory | now (tree-hash agreement) + half (the state machine) |
| 5 | Identical verify path for local and pushed | half (device) |
| 6 | Runtime tiers are not crossed | now (parse) + half (each side refuses the other's tier) |

Invariant 3 is the load-bearing one and is mutation-checked: removing the
refuse-on-fail branch, skipping manifest validation, skipping the size check,
letting `resolve()` fall back to `noop`, accepting traversal segments, or
accepting non-regular tar entries each turn the suite red. It had to have teeth
before `noop` existed anywhere in a tree, because `noop` accepting everything is
precisely the thing invariant 3 proves is contained.

Invariant 5's second half is easy to lose and worth stating separately: the
server refuses to push a plugin it cannot itself verify, **and** the device
independently re-verifies on receipt. The server verifying is not sufficient. A
device that trusts the server's verdict has made the delivery channel the trust
anchor again, which is exactly what invariant 5 exists to prevent.

---

## 9. Current state, measured

| | |
|---|---|
| Python `pluginmgr` suite | **146 passed** at `030b52b` |
| Go `internal/plugins` | `ok rttys/internal/plugins` at `8853e50`; `go build ./...` exits 0 |
| Contract byte-identity | verified by recursive diff between the two vendored trees |
| `CONTRACT-SHA256` | `d14ad81f…`, recomputes correctly in both repos |
| Vector regeneration | reproducible — `genvectors.py` reproduces `vectors/` exactly |

What is built: the manifest schema and its validation, canonical JSON, the wire
framing and chunk reassembly, the canonical tree hash, the `Verifier` seam with
`noop` and `hash-only`, the gate, offer admission, bundle reading with the full
path-safety rule set, and readback body construction. Both halves, held to the
same vectors.

What is not built, and should not be assumed: placement, rollback, the load
step, the server's open-until-readback state machine, the catalog, the sidecar,
and every part of signing. There is no install driver on either side, so nothing
in this foundation currently runs against a real plugin.

One item is deliberately deferred rather than missing. `sandbox` has no
vocabulary and `signature.model` has one accepted value, both by decision
(D-017 and D-016), and both are shaped so that filling them later is an
implementation behind an existing seam rather than a schema migration across a
fleet.

---

## 10. Where to read next

- `contract/plugins/README.md` — how the directory is kept in sync, and how to
  regenerate the hash and the vectors.
- `contract/plugins/manifest.md` — the schema, field by field, with the reason
  for each rule.
- `contract/plugins/wire.md` — the five typed messages, the envelope, the chunk
  format, and the canonical tree hash.
- `contract/plugins/verifier.md` — the seam, the gate, and the swap plan.
- `contract/plugins/invariants.md` — the six invariants as assertions, mapped to
  vectors.
- `contract/plugins/errors.md` — the refusal codes.
- [`admission.md`](admission.md) — what a bundle must be before anything reaches
  the disk, and why the import-precedence rule exists.
- `docs/modules/plugins.md` in `kazbek` — the module spec and what was
  deliberately deferred to the signing module.
