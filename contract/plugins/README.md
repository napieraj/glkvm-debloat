# Plugin foundation — the shared contract

This directory is the **single source of truth** for the plugin wire protocol,
the manifest schema, the canonical tree hash, and the `Verifier` seam. It is
consumed by two independent implementations in two independent repositories:

| Repo             | Role   | Implementation lives in |
|------------------|--------|-------------------------|
| `kazbek`         | server | `internal/plugins/`     |
| `glkvm-debloat`  | device | `kvmd/pluginmgr/`       |

Neither repo depends on the other. They meet only here.

## How this directory is kept in sync

The tree is **vendored byte-identically into both repos**. `CONTRACT-SHA256`
records the hash of the tree; each repo has a test that recomputes it and fails
on drift, so a one-sided edit is caught by that repo's own suite rather than at
integration time.

To change the contract: edit here, regenerate `CONTRACT-SHA256` (see below),
copy the whole directory into both repos in the same cycle, and update both
implementations. A contract change that lands in only one repo is a bug that
both suites will report.

`CONTRACT-SHA256` is the **canonical tree hash** of this directory, excluding
`CONTRACT-SHA256` itself — deliberately the same algorithm as the readback tree
hash defined in `wire.md`. There is one hashing algorithm in this contract, not
two, so each repo verifies contract sync with the function it already had to
implement and test.

```
for each file under contract/plugins/ except CONTRACT-SHA256:
    p = path relative to contract/plugins/, POSIX separators
lines = sorted(p bytewise ascending) mapped to:
    sha256_hex(file_bytes) + "  " + p + "\n"
CONTRACT-SHA256 = sha256_hex(concat(lines))
```

## Contents

- `wire.md` — the five typed messages and their framing.
- `manifest.md` — the manifest schema and its validation rules.
- `verifier.md` — the `Verifier` seam, the verify gate, and the swap plan.
- `invariants.md` — invariants 1–6 as a test contract, mapped to vectors.
- `errors.md` — the shared refusal-reason codes.
- `vectors/` — language-neutral conformance vectors both suites execute.

## Scope

This contract is **signing-independent**. It defines a `signature` block and
never populates it, and it defines a `Verifier` seam whose strongest v1
implementation is `hash-only`. Key custody, trust-anchor distribution and the
trust-tier model are a separate module; see `docs/modules/plugins.md` in
`kazbek` for what was deliberately deferred and why.

## Regenerating

```sh
cd contract/plugins
python3 tools/genvectors.py vectors
python3 tools/contracthash.py . > CONTRACT-SHA256
```

The generator is checked in so the vectors are reproducible rather than magic
constants. Both scripts are plain stdlib Python 3 and are not part of either
repo's linted source tree.
