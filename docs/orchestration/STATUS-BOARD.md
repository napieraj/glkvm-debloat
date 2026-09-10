# Orchestration status board

**What is true now.** History lives in `git log`; this file is state. If a
statement here disagrees with the tree, the tree is right.

Engineering only — the licence position and the disclosure drafts stay out of
both repos deliberately, because repo history is public.

## Branches

Two integration branches carry essentially everything. The work is not spread
across many branches; the documentation was, and that is now merged.

| Repo | Branch | Ahead of main | Contains |
|---|---|---|---|
| glkvm-debloat | `claude/repo-status-report-6vi5r1` | 97 | `glkvm-status-hutk39` + `new-session-2w6w30`, merged; `test_auth.py` resolved as a union of twelve |
| kazbek | `claude/repo-status-report-6vi5r1` | 45 | `new-session-2w6w30` + `glkvm-stock-debloat-migration-0pibl7`, merged; `signing.md` resolved |

Outside them, deliberately:

- **`claude/glkvm-webauthn`** — 6 unique commits, the sole copy of the WebAuthn
  implementation. Merge-ready mechanically (see below) and not merged, because
  merging auth is a design step.
- **`mcp`** — 3 commits, parked. Additive: 2 lines in `server.py`, everything
  else new.

## Test and CI state

Measured with `python -B`, `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared.
That is not optional — see the bytecode hazard in `WORKING-AGREEMENT.md`.

| | Result |
|---|---|
| glkvm-debloat suite | 1150 passed, 2 skipped |
| kazbek | `internal/plugins`, `internal/authz`, `internal/authz/fixtures`, `log` green; `internal/server` green filtered |
| kazbek CI | `test.yml` **passing** — first automated test run in the repo's history |
| kazbek `build.yml` | **failing, pre-existing**: calls `./build.sh`, which is absent from every branch |
| glkvm-debloat CI | Actions now enabled, 4 workflows registered; first run pending |

The two skips are both in `test_attestation.py`: one needs hardware and says
so, the other is the `webauthn.json` guard below.

## Open decisions — owner only

1. **The `webauthn.json` guard.** `test_attest__the_reference_credential_store_is_empty`
   skips wherever `configs/kvmd/webauthn.json` is absent, which is every branch
   but one, so it certifies nothing where it lives. Move the guard, ship a
   reference store, or hard-fail on absence. Owner leans to the third.
2. **The unauthenticated-surface bound.** Merging WebAuthn takes it from 4 to 6
   — a challenge must be obtainable pre-auth. Raising the bound is a security
   decision. The feature registry now makes this a per-feature declaration
   rather than a global count, so the right shape is to declare the two routes,
   not to raise a number.
3. **Merging `claude/glkvm-webauthn`.** Sole copy; auth; design step.
4. **`require_entry` "present but not alone."** A bundle may carry files it
   never declared. Three candidate constraints in `docs/plugins/admission.md` §6.
5. **The rebrand**, which `build.sh` is blocked on: the script it references is
   gone along with `rttys.conf`, `rttys.service` and `main.go`. Rewriting it
   means naming the binary.

## Blocked on hardware — one unit, one trip

`docs/bench-measurements.md` is the list. Five items now:

1. `kvmd-pst` partition — forks the plugin device-half plan.
2. `ss -ltnp` — the closed-userland half of the `/web` port finding.
3. U-Boot env and `/etc/init.d/S*` — does anything pick up `/userdata/update.img`?
4. Device-gated attestation residuals.
5. Does anything start `localhid`, `media` or `swctl`? ~1,061 lines of strip
   candidate if not.

## Queued patches

`queued/` holds three, unapplied because pushes to those branches are blocked
from this session. `webauthn-tests.patch` is the substantial one: 84 → 96
passing, closing eight mutations including a fail-open signature gate.

## Where things are written down

| File | For |
|---|---|
| `WORKING-AGREEMENT.md` | the rules, and the hazards that produced them |
| `CORRECTIONS-REGISTER.md` | every claim measured wrong, by status |
| `FINDINGS-plugin-contract.md` | the plugin findings and their resolution |
| `../ci.md`, `../testing.md` | what runs, where, and in what environment |
| `../plugins/admission.md`, `../plugins/contract-overview.md` | the plugin contract |
