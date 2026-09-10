# Dispatch — one brief per worker session

The orchestrator cannot message sessions (no `send_message` in its toolset) and
cannot push to a branch other than its own or add `napieraj/provision` (both
blocked by the auto-mode classifier). So these briefs are paste-in text. Each is
self-contained; paste the whole block into that session.

Common to all three: **do not touch `testenv/tests/apps/kvmd/test_auth.py`.** It
is resolved on `claude/repo-status-report-6vi5r1` as a union of twelve. Anyone
editing it again re-creates the conflict.

---

## Session "glkvm status" — branch `claude/glkvm-status-hutk39`

You own the steps line. Three things, in order.

1. `git fetch origin && git am` the AGENTS.md patch at
   `docs/orchestration/queued/glkvm-debloat-AGENTS-guard-branch-rule.patch` on
   `claude/repo-status-report-6vi5r1`. It adds one bullet to *Verification
   conventions*: a guard and the thing it guards must live on the same branch.
   It is doc-only.
2. **Resolve conflict 4** — `docs/lean-plan.md` diverges between your branch and
   `claude/glkvm-webauthn`. You own the plan, so you own this. It is not a
   mechanical merge: the file is the source of truth for what gets deleted, and
   it already contained one self-contradiction resolved against the done-when
   grep. Establish which branch's understanding is current before taking either
   side.
3. `configs/os/services/*.service` cleanup. Inherited PiKVM units that cannot run
   on BusyBox init. Check for a launcher reference before deleting each — a
   source search proves the absence of a caller, never of a mechanism.

**Steps 13–15: the provision blocker is gone, but do not start them yet.**
`napieraj/provision` has been measured — one commit, one 11-byte `README.md`,
nothing else — and it is being deprecated. Step 13 was never gated on it; there is
nothing there. The real and only constraint is unchanged: `InitManager.init()` has
no caller, is kept deliberately, and wiring it back up re-exposes CRITICAL R5.4
unless gated behind pinned-cert provisioning, never behind the old unauth path.
That gating is a design step and needs the owner, not a worker.

While you are in `AGENTS.md`, delete lines 35–36 — "The same shape applies to the
provisioning repo: its device-side tunnel client is missing for exactly this
reason." The repo is empty and going away, so it is a bad instance of rule 12; the
rtty client, `updateEngine`, `swupdate_start.sh` and the flash trigger carry the
point without it.

Also fix `docs/lean-plan.md:741-742`. The documented "sandbox fallback when Docker
is unavailable" command cannot run: `/home/user/glkvm-lean` does not exist and the
stub `PYTHONPATH` points into a dead container's scratch directory. Replace it with
the dependency set in `docs/orchestration/CORRECTIONS-REGISTER.md`, which is
measured and works.

---

## Session "GLKVM stock-to-debloat migration" — branch `claude/glkvm-stock-debloat-migration-0pibl7`

You own kazbek authz Phase 1. Continue; nothing here is blocked.

1. `git am` the AGENTS.md patch at
   `docs/orchestration/queued/kazbek-AGENTS-guard-branch-rule.patch` (adds rule
   12). Doc-only.
2. **Resolve conflict 3** — `docs/modules/signing.md` is an add/add against
   `claude/new-session-2w6w30`. Two different documents at one path: the
   `Signer`/`TrustStore` module spec, and the plugin-research survey stub.
   **Merge, do not overwrite** — either as two sections or two files with
   distinct names. This is the conflict most likely to lose content silently.
3. Phase 1 proper. Three things to hold at the milestone:
   - mutation-check **deny precedence** hardest — neither surveyed engine had
     it, so there is no prior art and the failure is silent;
   - add an **order-shuffling test**, so resolution is order-independent in
     implementation and not only in specification;
   - do not let the grant model land complete against a tunnel path that still
     has no `Subject`. `/connect/:devid`, `/cmd/:devid` and
     `/web/:devid/:proto/:addr/*path` have zero permission checks today.
4. Put `go list -deps ./internal/authz/...` in CI (D-014, verified not asserted).
   Record D-015 and the shrinks-monotonically claim.

---

## Session "New session" — branch `claude/new-session-2w6w30`

**Stand down from the `kvmd-pst` question. It cannot be answered from either
tree.** The mechanism survives the fork intact — `kvmd/apps/pst`,
`kvmd/apps/pstrun`, `kvmd-helper-pst-remount`, `fstab.find_pst()`, sudoers
entries, console scripts — but its only launcher is a systemd unit and this
hardware is BusyBox init throughout. The real test is `find_pst()`'s: scan
`/etc/fstab` for `X-kvmd.pst-*` mount options, which needs a device. It is bench
item 1 and it is waiting on hardware, not on you. Do not estimate the plugin
device half before it is answered — adopt-a-discipline and write-a-launcher-plus-
provision-storage are different sizes.

Take this instead, which is bounded and ready:

1. `git am` the patch at `docs/orchestration/queued/webauthn-origin-pin-tests.patch`
   onto **`claude/glkvm-webauthn`**. It adds two tests that close a real gap: two
   mutations of the WebAuthn origin pin passed the suite green — relaxing exact
   membership to a prefix match, and neutering the `get_default_origins()`
   fallback that a shipped device actually takes, since `origins` defaults to `[]`
   and no config sets it. Verified: baseline 84 passed, 86 with the patch, and
   each mutation now reddens exactly one test. Environment named: Python 3.11.15,
   pytest 9.1.1, pytest-asyncio 1.4.0, pytest-aiohttp 1.1.1, pytest-mock 3.15.1,
   aiohttp-basicauth 1.2.0, bcrypt 4.0.1 (bcrypt 5.x breaks passlib at import).
2. Then, on that same branch, close the guard/branch split once the owner picks
   an option — see the status board, Row 1. Owner leans toward hard-failing when
   `configs/kvmd/webauthn.json` is absent.

Do not merge `claude/glkvm-webauthn` into anything. Merging auth is a design step.
