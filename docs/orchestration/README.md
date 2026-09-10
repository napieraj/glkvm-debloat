# `docs/orchestration/` — what is here and what order to read it in

These files are the state of a multi-session effort across two repositories,
`glkvm-debloat` (device, Python) and `kazbek` (server, Go). They are engineering
state only: the licence position and the disclosure drafts are deliberately kept
out of both repos, because repo history is public.

Everything here goes stale like any other document. Each file names the ref its
figures came from; re-derive before acting on any of them.

## Read in this order

**1. [`WORKING-AGREEMENT.md`](WORKING-AGREEMENT.md)** — how disagreement works
here, and the bar an objection has to clear. Read it first because it governs
how to read everything else: an instruction is a claim until it is measured,
whoever it came from, and a relayed measurement is a claim with a source rather
than a fact. It also carries the counter-example that produced the rule, and a
closing section of build hazards found the hard way — run mutation loops in a
throwaway worktree, and remember that a mutation which hangs is not a mutation
that bit.

**2. [`CORRECTIONS-REGISTER.md`](CORRECTIONS-REGISTER.md)** — claims that were
believed, then measured, then found wrong. This is the delta produced by the
2026-09-10 orchestration pass and supplements the register in the handoff
package; where the two disagree, this one is later. Read it before trusting a
statement inherited from an older document — several of the entries here are
corrections *to* corrections.

**3. [`STATUS-BOARD.md`](STATUS-BOARD.md)** — the branch inventory, the four
integration conflicts and how each should be resolved, the three open rows
(the guard/branch split, the `provision` deprecation, the bench measurements
that need hardware), and the owner decisions taken so far. This is the file to
open when the question is "what is the state of the work".

**4. [`FINDINGS-plugin-contract.md`](FINDINGS-plugin-contract.md)** — the six
findings from the plugin-contract scoping pass, each with its provenance marked,
followed by a resolution section recording what was reproduced, what was fixed
in both halves, and what was recorded as a constraint on code that does not
exist yet. Read the status banner at the top before the body: the body is the
original report and several items in it are superseded by the resolution.

**5. [`DISPATCH.md`](DISPATCH.md)** — one self-contained brief per worker
session, as paste-in text, because the orchestrator cannot message sessions
directly. Read the brief for the branch you are on; the common instruction at
the top applies to everyone.

**6. [`queued/`](queued/)** — patches that are prepared and deliberately not
applied, because they land on branches outside the orchestrator's push scope.
`queued/README.md` says which patch goes onto which branch. Applying one needs
sign-off, not just an `git am`.

## Where the engineering documents are

The orchestration files describe the effort. The documents describing the
*system* live elsewhere in `docs/`:

- `docs/audit.md` — the fork security audit, twenty-one findings.
- `docs/lean-plan.md` — the strip plan the worker branches execute against.
- `docs/bench-checks.md`, `docs/bench-measurements.md` — the measurements that
  need a physical device.
- `docs/plugins/contract-overview.md` — orientation for the plugin contract that
  spans both repos.
- `docs/plugins/admission.md` — what a plugin bundle must be before anything
  reaches the disk.
