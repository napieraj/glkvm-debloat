# `docs/orchestration/`

Six files. Read them in this order; each says what it is for and nothing else.

| # | File | What it is |
|---|---|---|
| 1 | `STATUS-BOARD.md` | **What is true now.** Branches, test and CI state, the open decisions, what is blocked on hardware. Start here. |
| 2 | `WORKING-AGREEMENT.md` | **The rules, and the incidents that produced them.** How friction between owner and agents is expected to work, and the build hazards that have actually bitten — including the one where the mutation harness ran mutated bytecode against a restored source. |
| 3 | `CORRECTIONS-REGISTER.md` | **Every claim measured wrong**, organised by status: fixed, open, corrections to this session's own claims, and settled-no-action. Read before trusting a figure anywhere. |
| 4 | `FINDINGS-plugin-contract.md` | The plugin-contract findings and how each was resolved. |
| 5 | `queued/` | Patches that could not be pushed, because pushes to worker branches are blocked from this session. `queued/README.md` says how to apply them and what to measure first. |
| 6 | `DISPATCH.md` | **Historical.** Briefs for worker sessions that were never delivered. Kept for the file-ownership reasoning only. |

Product documentation lives outside this directory and is the thing to keep:
`../ci.md`, `../testing.md`, `../plugins/admission.md`,
`../plugins/contract-overview.md`, and the inherited `../audit.md`,
`../lean-plan.md`, `../bench-measurements.md`, `../bench-checks.md`.

## The one habit worth carrying out of here

Every figure in every file below goes stale, and several already did within
hours of being written. Three separate documents recorded a mutation as "still
silent" that had been closed the same day. **Re-derive before acting** — rule 1
applies to these files exactly as it applies to a plan.
