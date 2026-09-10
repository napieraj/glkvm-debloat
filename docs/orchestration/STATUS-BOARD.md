# Orchestration status board

Owner: orchestrator session. Engineering state only — licence position and
disclosure drafts stay out of the repos deliberately (repo history is public).

Measured 2026-09-10. Every figure names the ref it came from. Re-derive before
acting; this file goes stale like any other.

## Branch inventory

Both repos: `main` is untouched and carries no `docs/` and no `AGENTS.md`. All
work lives on branches.

### glkvm-debloat

| Branch | Ahead of main | Tip | State |
|---|---|---|---|
| `claude/glkvm-status-hutk39` | 64 | `436b348` | steps line; idle |
| `claude/glkvm-webauthn` | 54 | `13d6eb6` | **hold — sole copy, see below** |
| `claude/new-session-2w6w30` | 6 | `70c35f8` | plugin/auth line; idle |
| `mcp` | 3 | `7b1cdbb` | parked, clean against everything |

### kazbek

| Branch | Ahead of main | Tip | State |
|---|---|---|---|
| `claude/glkvm-stock-debloat-migration-0pibl7` | 30 | `556f9a7` | authz Phase 1; idle |
| `claude/new-session-2w6w30` | 7 | `6df5471` | plugin contract; idle |

## Integration conflicts — four, not three

Measured with `git merge-tree --write-tree` against the pushed refs.

| # | File | Between | Kind |
|---|---|---|---|
| 1 | `testenv/tests/apps/kvmd/test_auth.py` | `hutk39` + `new-session-2w6w30`; also `webauthn` + `new-session-2w6w30` | content |
| 2 | `kvmd/utils.py` | `hutk39` + `new-session-2w6w30` | auto-merges today |
| 3 | `docs/modules/signing.md` (kazbek) | `0pibl7` + `new-session-2w6w30` | add/add |
| 4 | `docs/lean-plan.md` | `hutk39` + `webauthn` | content |

`mcp` is clean against every other branch.

### Conflict 1 — the handoff's recommendation is wrong, do not follow it

`07-INTEGRATION-CONFLICTS.md` says Worker B's version "is almost certainly a
superset" and to take it. That was true when `hutk39` sat at `1ab2083` with four
tests. It has moved: **`hutk39` now carries ten tests, `new-session-2w6w30` six,
and neither is a superset.**

Only on `new-session-2w6w30` — lost if `hutk39` wins:
- `test_ok__session_expires`
- `test_ok__zero_expire_never_expires`

Only on `hutk39` — lost if the handoff's advice is followed:
- `test_fail__totp_secret_path_is_no_longer_accepted`
- `test_ok__password_is_not_truncated`
- `test_ok__sysprep_reaches_the_auth_services`
- `test_ok__ws_session_counts_nested_sockets`
- `test_ok__ws_session_extends_while_open`
- `test_ok__ws_session_is_a_noop_without_extend`

**Resolution is a union of twelve, not a pick.** The two unique to
`new-session-2w6w30` are exactly the session-expiry hole the corrections register
credits as the mutation find, so both halves carry real coverage. Re-run the
seven mutations after merging — they are not assumed to survive it.

### Conflict 4 — needs judgement, not a merge tool

`docs/lean-plan.md` is the document both branches were executing against, and it
already contained one self-contradiction a worker had to resolve against the
done-when grep. Two divergent copies of the plan that says what to delete is
worse than a code conflict. Resolve deliberately; establish which branch's
understanding is current before taking either side.

## Row 1 — the `webauthn.json` guard/branch split

`testenv/tests/test_attestation.py:259`,
`test_attest__the_reference_credential_store_is_empty`, guards a real hazard:
if `configs/kvmd/webauthn.json` ever ships with a credential in it, every
flashed device trusts that key. It `pytest.skip`s when the file is absent.

The file exists **only on `claude/glkvm-webauthn`**, where it ships
`{"version": 1, "credentials": []}`. The guard is on `hutk39`. So on `hutk39`
the test skips and certifies nothing; the assertion and the thing it asserts are
on different branches.

This is the same vacuity class as `_ROOT` one level short and the uncovered
session expiry, reached a third way — but the first instance that is a property
of **branch topology** rather than of one tree. Nothing currently checks for it.

**Open decision — report, do not pick.** Three ways to close it:
1. Move the guard to the branch that has the file.
2. Give `hutk39` a reference `webauthn.json`.
3. Convert the skip to a hard failure when the file is absent.

Owner leans 3: a missing reference store is itself a fact worth failing on.
Shipping `hutk39` standalone without choosing leaves the skip in place.

## Row 2 — `provision`: RESOLVED, and it was a phantom

Owner supplied the repo as an archive on 2026-09-10. Measured:

- **One commit** — `5750183`, "Initial commit", 2026-09-09, Oskar Napieraj.
- **One tracked file** — `README.md`, **11 bytes**, contents `# provision`.
- Nothing else. No migration module. No attestation doc. No tunnel client.

**The worker who reported it as an empty repo with an 11-byte README was exactly
right, and that report should stop being carried as an unresolved mismatch.** The
belief that it hosted the migration module and the attestation doc came from
conflating two different things that share a word:

| | What it is | State |
|---|---|---|
| `napieraj/provision` | a GitHub repo | empty, 11 bytes, **to be deprecated** |
| "the provisioning module" | kazbek roadmap item 3 — cert issuance and the pairing ceremony | unbuilt, referenced from four kazbek docs |

Every kazbek hit (`HANDOFF-first-pr.md:55`, `docker-compose/certificate/README.md:47`,
`docs/modules/migration.md:68`, `docs/modules/signing.md:27`,
`docs/modules/plugins.md:104`, `docs/modules/tunnel-client.md:85`) refers to the
**module**, not the repo. None of them is affected by deprecating the repo.

### Consequences of deprecation

**Step 13 was never gated on provision.** The handoff argued provision mattered
because "it is also where step 13 (beacon enrolment) lands". There is nothing there
for it to land on or beside. Step 13's real and only constraint is unchanged and
lives entirely in glkvm-debloat: `InitManager.init()` has no caller, is kept
deliberately, and wiring it back up re-exposes CRITICAL R5.4 unless gated behind
pinned-cert provisioning — never behind the old unauth path. Deprecating the repo
removes a phantom dependency; it unblocks nothing and blocks nothing.

**One claim in `AGENTS.md` should go with it.** `AGENTS.md:35-36` on `hutk39` reads:
"The same shape applies to the provisioning repo: its device-side tunnel client is
missing for exactly this reason." Cited as an instance of rule 12 — a source search
proves the absence of a caller, never of a mechanism. It is a poor instance: the
repo does not have one component missing for a subtle reason, it has nothing at all.
The genuine instances of rule 12 (the rtty client, `updateEngine`,
`swupdate_start.sh`, the flash trigger) carry the point without it. Delete the
sentence when the repo is deprecated.

**The tunnel client is unowned and unwritten.** `kazbek/docs/modules/tunnel-client.md`
files it with owner `glkvm-debloat`. It is not in provision, not in either tree, and
not started — an unbudgeted core deliverable under roadmap item 0.

### Separate rot found while checking this

`docs/lean-plan.md:741-742` (`hutk39`) and `:611-612` (`webauthn`) document a
"sandbox fallback when Docker is unavailable" command. **Both halves of its
`PYTHONPATH` are dead:** `/home/user/glkvm-lean` does not exist (the repo is
`glkvm-debloat`), and
`/tmp/claude-0/-home-user-provision/24a544c1-.../scratchpad/stub` is a scratch
directory belonging to a container that no longer exists. The one documented
procedure for the exact situation everyone keeps hitting cannot run. It is why this
session had to reconstruct a virtualenv from scratch. Replace it with the dependency
set that actually works, recorded in `CORRECTIONS-REGISTER.md`.

## Row 3 — four bench measurements, one unit, one trip

These are the only things gating the plugin device half. They need one person
with a device, not four separate visits. Consolidated list lives at
`docs/bench-measurements.md` on `hutk39`.

| # | Measurement | Unblocks |
|---|---|---|
| 1 | `kvmd-pst` partition: does `find_pst()` find `X-kvmd.pst-*` in `/etc/fstab`? | **plugin device half** — forks the plan |
| 2 | `ss -ltnp` (BusyBox `netstat` fallback) | closed-userland half of the `/web` port finding |
| 3 | U-Boot env + boot script dump, then `/etc/init.d/S*` | staged-image question: is `/userdata/update.img` picked up without a trigger? |
| 4 | Device-gated attestation items: residual `authorized_keys`, inherited cron, ttyd from GL's image, `$apr1$` password, `/etc/shadow`, staged image absent, misc partition clean | closes the device-verifiable half of the audit |

Measurement 1 is the live blocker: a worker session is currently parked waiting
for the `kvmd-pst` answer. It cannot be answered from either tree — the
mechanism survives the fork intact but its only launcher is a systemd unit and
this hardware is BusyBox init throughout. **Do not estimate the device half
before it is answered**; adopt-a-discipline and write-a-launcher-plus-provision-
storage are different sizes.

## Queued for `AGENTS.md` in both repos

`AGENTS.md` exists only on the worker branches, not on `main` and not here, so
this rule cannot land where it belongs without writing to a worker branch. Text
is staged below in the house style of the *Verification conventions* section.

> - **A guard and the thing it guards must live on the same branch.** Otherwise
>   the guard is vacuous, and it is vacuous in the direction that reads as a
>   pass. `test_attest__the_reference_credential_store_is_empty` skips on every
>   branch that lacks `configs/kvmd/webauthn.json` — which is every branch but
>   one. Every other vacuity found so far was inside a single tree; this class is
>   a property of the branch topology, and nothing checks it.

Also queued, same section, from rule 12 of the standing rules: *a source search
proves the absence of a caller, never the absence of a mechanism* — confirm
whether it is already present before adding.

## Owner decisions taken — 2026-09-10

**Keep everything as simple as possible for now.** Recorded so it is not
re-litigated by the next reader.

### D-016 (proposed) — no second signature model this cycle

Plugins stay at `signature.model: hash-only`. **No v3 contract bump.**

The "a plugin is just a GitHub repo, piggyback its hashing and signing" idea was
evaluated and is sound *in a reshaped form* — GitHub as an authoring and
distribution **source** that the server verifies, never a trust root the device
reaches. It is recorded here and deliberately not built.

Deferring costs nothing, which is the point of the pattern already in the tree:
`signature.model` is a required enum with exactly one accepted value and
`entries` enforced empty. The shape is reserved; adding a value later does not
cost a version bump across both implementations. That is why this is a cheap
"not now" rather than a decision that compounds.

If it is ever picked up, the five constraints that shape it are: D-003 (the
anti-pattern is unpinned trust of a third party, which is what a device
trusting Fulcio would be); zero-new-device-dependency was a deliberate bundle
format choice; the device has no egress to a third party; `revision` is a
monotonic integer and git supplies no such thing, so downgrade protection stays
explicit either way; and a git tree is not a bundle tree — `read_placed_tree`
raises on a symlink, git repos carry symlinks and mode bits, and `.git` must
never ship. A server-only model would also be the first deliberate asymmetry
between the two language halves and would need its own vectors asserting the
device refuses it.

### D-017 (proposed) — `sandbox` vocabulary stays empty

Same pattern, same reason. No entry joins the vocabulary until it has a named
enforcement point that exists. A permission that displays and does not hold at
the enforcement point is a hidden button.

### Consequence for the branch plan

The eight scoped workstreams are a menu, not a queue. Take the smallest genuinely
ungated ones; do not start the speculative ones (plugin store UI, tunnel client,
per-model config) on the strength of the plan alone. Plugin device half is
**local drop-in only**, against the injected placement root.

---

# Audit round — 2026-09-10, closing state

An 79-agent sweep mutated every silent-if-missed check in both repos and
adversarially verified the survivors. **24 confirmed at 3/3. 56 findings were
capped before verification and are NOT cleared.**

## The root cause behind the rest

**glkvm-debloat's test suite had never run in CI.** `.github/workflows/tox.yml`
was gated on `[master]`; there is no master branch and never has been. Fixed —
now `main`, `claude/**`, `mcp`.

**kazbek had no `go test` or `go vet` anywhere in CI.** Fixed — `test.yml` adds
gofmt, vet, the tests, and D-014's `go list -deps ./internal/authz/...`.

**kazbek's logger killed the process on its first line.** `logFileHook.Run`
called `log.Fatal()` (os.Exit) when it could not open an unset path, and the
hook attaches whenever stdout is not a TTY. That is why `internal/server`
failed at 0.010s before any test ran, and why three security guards there had
never been observed to execute. Fixed; they pass.

An unrun suite is what twenty-four green-under-mutation checks decay from.
These three were the cause, not findings beside it.

## Closed this round

| What | Where |
|---|---|
| 4 pluginmgr checks with no mutation coverage | hash comparison truncatable to 2 hex chars; `_ENTRY_RE` end anchor removable; `read_placed_tree` symlink guard deletable; `require_entry` `==` relaxable to `endswith` |
| Bundle entries importable ahead of source | both language halves, 3 shared vectors, 4 mutations each |
| `WriteMsg` uint16 wrap | frame desynchronisation, not truncation |
| `signing.md` add/add | spec keeps the path, survey to `signing-survey.md` |
| 4 contract-doc errors | `wire.md` v1 examples, `errors.md` triggers, `manifest.md` `capabilities`, `setup.py` missing `kvmd.pluginmgr` |
| MCP orphan suite | pytest testpath widened; 55 tests were linted by four envs and run by none |

## Still open, and why

**Six mutations on `claude/glkvm-webauthn` leave 84 tests green**, each proven
exploitable. The worst: `verify_es256_openssl` treats `retcode != 1` as success
while `kvmd/tools.py:131` returns NEGATIVE codes on signal death, so an
OOM-killed openssl authenticates. Also a one-byte `rpIdHash` comparison, a
challenge match relaxed to `startswith`, and both UP and UV masks widenable.
Not fixed here: that branch cannot be pushed to from this session, and merging
auth is a design step.

**56 unverified findings.** Only the top 24 by severity were checked.

**`require_entry` still asserts the declared entry is present, never that it is
alone.** A bundle may carry files it never declared. Closing it is a design
choice among three constraints; `docs/plugins/admission.md` §6 lists them.

**Conflict 4, `docs/lean-plan.md`**, remains the last unresolved merge.

**Row 1 is unchanged.** Of two skips in 1,127 tests, one needs hardware and says
so; the other is `no reference credential store in this tree` — still reading as
a pass, still awaiting the owner's pick among the three options above.
