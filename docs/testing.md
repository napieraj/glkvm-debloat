# Running the tests without the container

The supported way to run this suite is the Arch container that
`.github/workflows/tox.yml` builds — `make testenv && make tox`. This document
is about the other way, because sessions keep having to reconstruct it: a plain
virtualenv, no Docker, and a dependency set assembled by hand.

It records what works, what it costs, and why every count produced this way is
**provisional**. For what CI runs and on which branches, see [`ci.md`](ci.md).

Measured against `claude/repo-status-report-6vi5r1` at `1355993`.

---

## 1. The measured working set

Python **3.11.15** (`3.11.15 (main, Mar 3 2026, 09:26:23) [GCC 13.3.0]`). With
this set the whole suite runs: **1127 passed, 2 skipped** for
`pytest testenv/tests kvmd -q -p no:cacheprovider` with
`PYTHONPATH=/home/user/glkvm-debloat`. **[verified here]**

Test machinery:

```
pytest==9.1.1  pytest-asyncio==1.4.0  pytest-aiohttp==1.1.1  pytest-mock==3.15.1
aiohttp-basicauth==1.2.0
```

Runtime dependencies the tree imports:

```
aiofiles  aiohttp  async-lru  bcrypt==4.0.1  cbor2  dbus-next  evdev  luma.oled
Mako  netaddr  passlib==1.7.4  pillow  psutil  pyghmi  Pygments  PyOTP  pyrad
pyserial  pyserial-asyncio  python-dateutil  python-pam  python-periphery
python-xlib  PyYAML  qrcode  setproctitle  six  smbus2  spidev  zstandard
ustreamer  (see §3 — not from PyPI)
```

The exact freeze of the environment every count in the current documents came
from:

```
aiofiles==25.1.0        aiohappyeyeballs==2.7.1   aiohttp==3.14.3
aiohttp-basicauth==1.2.0 aiosignal==1.4.0         async-lru==2.3.0
attrs==26.1.0           bcrypt==4.0.1             cbor2==6.1.4
cffi==2.1.1             cryptography==50.0.1      dbus-next==0.2.3
evdev==2.0.0            frozenlist==1.8.0         idna==3.19
iniconfig==2.3.0        luma.core==2.6.0          luma.oled==3.15.0
Mako==1.4.1             MarkupSafe==3.0.3         multidict==6.8.0
netaddr==1.3.0          packaging==26.3           passlib==1.7.4
pillow==12.3.0          pluggy==1.6.0             propcache==0.5.2
psutil==7.2.2           pycparser==3.0            pyghmi==1.6.19
Pygments==2.21.0        PyOTP==2.10.0             pyrad==2.5.4
pyserial==3.5           pyserial-asyncio==0.6     pytest==9.1.1
pytest-aiohttp==1.1.1   pytest-asyncio==1.4.0     pytest-mock==3.15.1
python-dateutil==2.9.0.post0                      python-pam==2.0.2
python-periphery==2.4.1 python-xlib==0.33         PyYAML==6.0.3
qrcode==8.2             setproctitle==1.3.7       six==1.17.0
smbus2==0.6.1           spidev==3.8               types-aiofiles==25.1.0.20260518
types-PyYAML==6.0.12.20260906                     typing_extensions==4.16.0
ustreamer==6.65 (local wheel)                     yarl==1.24.5
zstandard==0.25.0
```

Invoke as:

```sh
PYTHONPATH=/home/user/glkvm-debloat \
  <venv>/bin/python -m pytest testenv/tests kvmd -q -p no:cacheprovider
```

`-p no:cacheprovider` keeps pytest from writing `.pytest_cache` into a tree
someone else may be committing from.

---

## 2. `bcrypt` must stay at 4.x

`bcrypt 5.x` breaks `passlib` at import — passlib reads `bcrypt.__about__`,
which 5.x removed. The pin is deliberate; do not let a routine upgrade take it.
**[reported]**, carried from the corrections register and not re-derived here,
because verifying it means installing a version that breaks the environment
every other measurement in this session depends on. If it is ever checked, check
it in a throwaway virtualenv.

`passlib 1.7.4` is the version the tree is measured against.

---

## 3. `ustreamer` is a locally built wheel, and the whole suite depends on it

`kvmd/clients/streamer.py:35` does `import ustreamer`, and that module is
**not on PyPI**: `pip download ustreamer --no-deps` returns *"Could not find a
version that satisfies the requirement ustreamer (from versions: none)"*.
**[verified here]**

It is not optional and it is not confined to streamer tests. With the module
blocked, `pytest testenv/tests kvmd` aborts at collection with **three errors
and zero tests executed** — including `test_server_smoke.py` and
`test_switch_sysfs.py`, which have nothing to do with video. **[verified here]**

The environment used for this session's measurements satisfies it from a wheel
built earlier in the session and left at
`/tmp/claude-0/wheels/ustreamer-6.65-cp311-cp311-linux_x86_64.whl`. **Do not
record that path as the answer.** It is a session scratch directory and it will
not survive the container — which is precisely the failure mode §5 is about.

The durable form of the instruction is how the container does it
(`testenv/Dockerfile`):

```sh
git clone https://github.com/pikvm/ustreamer
cd ustreamer && make WITH_PYTHON=1 PREFIX=/usr DESTDIR=/ install
```

Building it needs `libjpeg`, `libevent`, `libbsd` and `libutil-linux`, which the
Dockerfile installs for the same reason.

---

## 4. This is not the staged testenv, and the difference is measurable

The container is an Arch image: `python-*` packages from pacman, plus
`testenv/requirements.txt` via pip, plus the tox environments' own deps, plus a
locally built `ustreamer`. The reconstructed virtualenv is pip-only. The two
differ in both directions, and at least one difference changes which code path a
test exercises.

### 4.1 `cryptography` is present in BOTH — this section had it backwards

**Superseded 2026-09-10 by the first CI run of this suite.** The original text is
below the correction, because the reasoning error in it is the interesting part.

`cryptography` is installed in the container. Nothing names it: not the
`python-*` pacman list, not `testenv/requirements.txt`. It arrives because
`pyghmi` (`testenv/requirements.txt:2`) declares `cryptography>=2.1`, so
`pip install -r requirements.txt` installs it transitively — in the container and
in the reconstructed venv alike. **[verified: `importlib.metadata.requires("pyghmi")`
→ `['cryptography>=2.1', 'python-dateutil>=2.8.1']`; and CI, where the canary
below failed]**

The evidence was already in this document. The freeze in §3 lists
`cryptography==50.0.1` *and* `pyghmi==1.6.19`, eight lines apart. The venv was
built from `requirements.txt` by pip, so every line in that freeze that nothing
names is there by transitive resolution — which is the same mechanism that puts
it in the container.

So this is not a divergence between the venv and the container at all. It was
recorded as one because four independent searches for the *name* came back empty
and were read as the package being absent. A dependency list proves the absence
of a declaration; only the interpreter proves the absence of the module. See
`docs/webauthn.md` §1.1.

**What actually followed from it** is still true and is the part worth keeping:
with `cryptography` importable, every ES256 verification in that suite takes the
fast path, and `verify_es256_openssl` — which `docs/webauthn.md` called the
primary and *tested* path — is reached only where a test patches the fast path
away. That was a real coverage hole in the live branch, and it is now closed:
`webauthn.py:199` documents the reversal, the fast path's three fail-closed exits
are mutation-checked, and `test_ok__assertion_verifies_through_openssl` forces the
openssl path at plugin level so its wiring keeps integration coverage.

The **recommendation has been withdrawn.** It said `cryptography` should be kept
out of the working dependency set because "the suite passes without it" and
installing it "silently swaps the code path under an authentication test". Both
halves are wrong in the same way: it cannot be kept out while `pyghmi` is in, and
the swap was not a local artefact to avoid — it is what CI does. Uninstalling it
from the venv made the reconstruction *diverge* from the container while appearing
to fix a divergence.

<details>
<summary>Original §4.1, superseded</summary>

> `testenv/Dockerfile` does not install `python-cryptography` and
> `testenv/requirements.txt` does not list it. **[verified here]** The
> reconstructed venv has `cryptography 50.0.1`.
>
> On `claude/glkvm-webauthn` there is a canary for exactly this:
> `test_ok__cryptography_absent_here` asserts the module is not importable. Run in
> this virtualenv it **fails**, and the whole file goes **83 passed, 1 failed**
> against the 84 recorded in the corrections register. **[verified here]**
>
> **Recommendation.** `cryptography` should *not* be listed as part of the working
> dependency set. It is not needed — the suite passes without it, and the tree
> imports it only opportunistically — and installing it silently swaps the code
> path under an authentication test.

The canary did its job: it was the only assertion in the tree capable of
detecting this, and it is what detected it. It has been replaced by its inverse,
`test_ok__cryptography_is_in_the_dependency_closure`, which checks the
`pyghmi` declaration as code so the next change to the closure is loud.

</details>

### 4.2 `evdev` is imported unconditionally and is in no image package list

`kvmd/mouse.py:23`, `kvmd/keyboard/mappings.py:25` and eight other modules do
`from evdev import ecodes` at module scope. `python-evdev` appears nowhere in
`testenv/Dockerfile`'s pacman list, nowhere in `testenv/requirements.txt`, and
nowhere in `PKGBUILD`'s `depends=`. **[verified here]**

What that means is **not** settled, and rule 11 applies: a search proves the
absence of an entry in a package list, not the absence of the package from the
built image, which could still arrive as a transitive dependency of something
pacman pulls. Settling it needs the image built, and **Docker is not available
in this environment** — the client is installed, the daemon socket is not
present, so `make testenv` cannot run and `docker run` fails immediately.
**[verified here]** Someone with a working Docker should run
`docker run --rm <testenv image> python -c 'import evdev; print(evdev.__file__)'`
and record the answer. If it is absent, the container has been unable to import
half of `kvmd/` for as long as the fork has existed — which, given that the
suite had never run in CI, nobody would have noticed.

---

## 5. `docs/lean-plan.md`'s documented fallback cannot run

`docs/lean-plan.md:741-742` gives two commands for exactly this situation,
labelled *"sandbox fallback when Docker is unavailable"*. **Both halves of their
`PYTHONPATH` point at directories that do not exist.** **[verified here]**

```
PYTHONPATH=/home/user/glkvm-lean:/tmp/claude-0/-home-user-provision/24a544c1-.../scratchpad/stub
```

- `/home/user/glkvm-lean` — no such directory. `/home/user` contains exactly
  `glkvm-debloat` and `kazbek`. The repository was renamed and the plan was not.
- `/tmp/claude-0/-home-user-provision/24a544c1-…/scratchpad/stub` — a scratch
  directory belonging to a container that no longer exists.

The trailing comment on `:741` is also stale: it warns that *"test_http.py will
still fail on a missing aiohttp_basicauth, which is a sandbox gap, not a code
fault"*. `aiohttp-basicauth 1.2.0` is in the set above and `test_http.py` passes.

The second command, the fast dangling-import check, works once the path is
corrected:

```sh
PYTHONPATH=/home/user/glkvm-debloat <venv>/bin/python -c \
  'import kvmd.utils as u; u.MODEL_PATH="/etc/hostname"; import kvmd.apps.kvmd.server; print("server import OK")'
```

That prints `server import OK`. **[verified here]** It is worth keeping: it is
the cheapest possible check that a strip left no dangling import or `NameError`,
and it should be run after every step that edits `server.py`.

This is the same class of rot as the `ustreamer` wheel path in §3 and the CI
branch filter in [`ci.md`](ci.md): a recorded value that names something which
has ceased to exist, failing in a way that looks like the reader's mistake.
**Prefer a command that derives a path over a command that hard-codes one.**

---

## 6. Why counts from here are provisional

Say which environment a count came from, every time. A count from this
virtualenv is evidence, and it is weaker evidence than a count from the
container, for four measured reasons:

1. **The package sets differ**, in both directions — §4. At least one difference
   silently changes which branch of an authentication path executes.
2. **The interpreter differs.** `testenv/tox.ini` declares
   `basepython = python3.12`; this is 3.11.15.
3. **The container supplies fixtures this does not.** `make tox` mounts
   `configs/`, `contrib/keymaps` and `extras/`, copies platform YAML into
   `/etc/kvmd`, and stages generated TLS material — and `testenv/fakes/`
   provides a fake `/sys`, `/proc` and `/etc`. A bare `pytest` run gets none of
   that.
4. **A missing dependency presents as a failure, not a skip.** This is the
   recurring trap: an early pass in this project reported *26 failed* on the
   WebAuthn suite where the real answer was "`pytest-asyncio` is not installed".
   A red suite in a hand-built environment is a claim about the environment until
   proven otherwise.

The honest form is *"1127 passed, 2 skipped — reconstructed venv, Python
3.11.15, not the staged testenv"*, and the dishonest form is *"1127 passed"*.

## 7. What would remove the need for this document

A working Docker daemon, and `make testenv` run once. Everything above is
scaffolding around its absence. If a future session has Docker, use the
container and treat this file as a description of a workaround rather than a
recommended path — starting by settling the `evdev` question in §4.2, which only
the container can answer.
