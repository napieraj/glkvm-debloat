# Working agreement — friction is a deliverable

The owner asked that friction between the owner and the agents be encouraged.
This records what that means operationally, because "push back more" is an
exhortation and exhortations do not change behaviour.

## The rule

**An instruction is a claim until it is measured, whoever it came from.** Rule 1
already says re-derive before trusting, and that it extends to relayed reports and
handoff documents. It extends to the owner as well. The owner is a source of
*intent*, which is authoritative, and a source of *fact*, which is not.

**Report the objection before doing the work, not after.** An agent that spots a
wrong premise and builds anyway has converted a cheap correction into an expensive
one. Two of the three most costly incidents in the corrections register were of
exactly this shape.

**Compliance is not evidence of correctness.** A plan nobody argued with has not
been reviewed; it has been received. Silence from four agents is not four
confirmations.

## The bar

Friction without measurement is noise, and noise makes real objections cheaper to
ignore. So:

- Push back with a **measurement, a named constraint, or a decision record** —
  never a preference. "I would have done it differently" is not an objection.
- Say what would change your mind, and what you would measure to settle it.
- **Once the owner has heard the objection and reaffirmed, that is the decision.**
  Proceed, and record it. Friction is a check, not a veto. Re-litigating a settled
  call is the failure mode on the other side, and D-015 exists precisely to close
  one of those.

## Evidence that this works — this session

Every one of these was an agent contradicting the record, and every one was right:

- The corrections register said WebAuthn was "absent from both working trees".
  Measured: the *implementation* is absent, but `hutk39` carries three references
  including a guard. Owner accepted and the entry was rewritten.
- `07-INTEGRATION-CONFLICTS.md` recommended taking one branch's `test_auth.py` as
  "almost certainly a superset". Measured: ten tests versus six, neither a superset.
  Following the recommendation would have dropped six tests.
- The `webauthn` origin pin was believed defended. Measured: defended against
  deletion, silent under two weakenings, and the fallback that a shipped device
  actually takes was never exercised through `verify_assertion`.
- The "plugin is a GitHub repo" proposal was argued against on five measured
  constraints; the owner steered to the simpler answer and D-016 recorded it.

## The counter-example, which is why this rule is here

`napieraj/provision` was carried as a blocker on step 13 for a week. This
orchestrator **relayed it as a blocker twice without measuring it**, including once
in a status report that named it a hard blocker. When the owner supplied the repo it
was one commit and an 11-byte `README.md`, gating nothing.

Nobody lied. The claim was inherited, sounded reasonable, and was never checked. That
is the ordinary way a project acquires a false blocker, and it is why the bar above
is on the *agent*, not on the owner.

## Queued for `AGENTS.md`, both repos

Ride this along with the rule-13 patch already in `queued/`. House style of the
*Verification conventions* / *Standing rules* section:

> - **An instruction is a claim until measured, whoever sent it.** The owner is
>   authoritative about intent and not about fact. Report a wrong premise before
>   building on it — a correction costs less before the work than after. Object with
>   a measurement or a named constraint, never a preference, and say what would
>   settle it. Once an objection has been heard and the call reaffirmed, that is the
>   decision: proceed and record it. Friction is a check, not a veto.

## Build hazards found while orchestrating

**A mutation run that outlives its timeout keeps mutating.** A mutation loop was
backgrounded when it exceeded its 120s limit. It carried on applying mutations to
`internal/server/device.go` — in the live working tree — for another ten minutes
while commits were being made from the same tree. Nothing was corrupted, but only
because the loop's restore step happened to write the same content the commits
expected. That is luck, not design.

Two rules follow. Run mutation loops in a throwaway worktree, never in the tree
you are committing from. And when a long command is backgrounded, treat the files
it touches as contended until it reports, rather than assuming it died with its
timeout.

**A mutation that hangs is not a mutation that bit.** The same loop's first
mutation took 600 seconds and reported `FAIL` only on timeout. The test was
writing 70000 bytes into an unbuffered `net.Pipe` that nothing was reading, so
removing the bound made the test *block* rather than fail. A hung test reads as
neither red nor green, and in CI it reads as an infrastructure problem rather
than a caught regression.

So: when mutation-checking anything that writes to a pipe, socket or queue, race
the operation against a deadline and fail on the deadline. Check the symmetric
case too — a bound that is too STRICT writes nothing, so an undeadlined read on
the other side hangs just as silently.

## The mutation harness must disable bytecode — measured the hard way

A mutation loop in this session silently ran **mutated code against a restored
source file**, and the restore check said it was clean.

The mechanism is the same one this project shipped a fix for hours earlier. The
loop mutated `kvmd/pluginmgr/bundle.py`, ran pytest (which compiled the mutated
source to `__pycache__/bundle.cpython-311.pyc`), then restored the original with
`cp`. CPython decides whether a `.pyc` is stale by comparing the source's
**mtime and size** against the values recorded in the `.pyc`. The final mutation
in that loop was:

```
f.path == manifest.entry      ->      manifest.entry in f.path
```

Both are **exactly 24 characters**. The restored file therefore had the same
size as the mutated one, and `cp` landed it inside the same mtime second, so the
mutated `.pyc` was considered valid. Python went on executing
`manifest.entry in f.path` from bytecode while the source on disk read `==`.

Three separate things failed to notice:

- `cmp -s snapshot file` reported "restored: yes". It compares **source**, and
  cannot see bytecode.
- `git status` was clean, for the same reason.
- The test that should have caught it *did* eventually fail — but a full turn
  later, on a run that looked like an unexplained regression on a clean tree
  rather than like contamination.

**Rules, and they are not optional in a project whose whole method is mutation
testing:**

1. Run every mutation pass with bytecode off — `python -B` **and**
   `PYTHONDONTWRITEBYTECODE=1`; the flag alone does not cover subprocesses.
2. Delete `__pycache__` between mutation and restore, not only at the end.
3. Never treat a source-level `cmp` or a clean `git status` as proof that a
   revert took effect. Re-run the baseline and require the expected count.
4. Prefer a throwaway worktree, per the earlier hazard about backgrounded loops.
5. **Require the throwaway tree to be green BEFORE the mutation goes in, and
   require the mutation's red to name a test you expected.** Added 2026-09-10,
   after a harness that copied `kvmd/` and `testenv/` but not `configs/` ran one
   test that failed in every single run: a verdict of "red, so the check is
   covered" credited two surviving fail-open mutations as caught. A count of
   failures is not a verdict; the *identity* of the failing test is. Both
   survivors turned out to be mutations that do not change the mutated function's
   return value at all, so they needed tests written to observe the log instead —
   exactly the case the harness was there to find, and the one it hid.

**Everything claimed in this session was re-verified with bytecode disabled and
a cleared cache.** Baseline `pluginmgr` 155, whole suite 1132 passed / 2 skipped.
The hash ladder reddens at `[:2] [:8] [:32] [:63]`; `require_entry` reddens under
`endswith`, `startswith` and `in`; dropping the import-precedence call reddens
12, dropping `.so` reddens 5; the symlink guard and the entry anchor redden 1
each. The conclusions stand — but they stood on a method that had a hole in it,
and the hole was found by the code failing, not by the harness.

There is a pointed lesson in which hazard this was. The refusal added today
exists because a `.pyc` whose header matches its `.py` executes instead of the
source. That is not only an attack on a plugin bundle; it is an attack on any
process that edits a file and re-runs it — including the harness written to
prove the refusal works.
