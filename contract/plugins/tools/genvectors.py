"""Generate the shared conformance vectors for the plugin foundation contract.

Vectors are language-neutral: every case carries its own inputs and the exact
expected outcome, so the Go and Python implementations are held to identical
behaviour without either repo depending on the other.
"""

import base64
import hashlib
import io
import json
import os
import struct
import sys
import tarfile

OUT = sys.argv[1]

MSG_TYPE_PLUGIN = 0xF1
SUB_OFFER, SUB_FETCH, SUB_PAYLOAD, SUB_INSTALL_RESULT, SUB_READBACK = range(5)
TID_A = "9f2c41d7e6b8054a3c1f7d90ab2e6538"
TID_B = "0123456789abcdef0123456789abcdef"


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def b64(b):
    return base64.b64encode(b).decode("ascii")


def tree_sha256(files):
    """files: list of (path, bytes). Canonical tree hash per wire.md."""
    lines = b""
    for path, data in sorted(files, key=lambda f: f[0].encode("utf-8")):
        lines += (sha(data) + "  " + path + "\n").encode("utf-8")
    return sha(lines)


def bundle(files):
    """v1 bundle: uncompressed ustar, regular files only, deterministic."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for path, data in sorted(files, key=lambda f: f[0].encode("utf-8")):
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def frame(tid, sub, body):
    """Full wire frame including the rtty envelope."""
    inner = tid.encode("ascii") + bytes([sub]) + body
    assert len(inner) <= 0xFFFF, "body exceeds the uint16 envelope"
    return bytes([MSG_TYPE_PLUGIN]) + struct.pack(">H", len(inner)) + inner


PROTOCOL_VERSION = 2


def manifest(**over):
    m = {
        "name": "acme_relay",
        "revision": 1,
        "type": "ugpio",
        "runtime": "device",
        "model_compat": ">=rm1pe",
        "firmware_compat": ">=1.10.0",
        "entry": "plugins/ugpio/acme_relay.py",
        "payload": {"sha256": "0" * 64, "size": 1},
        "signature": {"model": "hash-only", "entries": []},
    }
    m.update(over)
    return m


def write(name, doc):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    print("wrote", path)


# ===== the reference plugin bundle used across vectors =====
PLUGIN_FILES = [
    ("plugins/ugpio/acme_relay.py", b"# acme relay plugin\nclass Plugin:\n    pass\n"),
    ("plugins/ugpio/acme_relay_util.py", b"# helper\nVERSION = 1\n"),
]
BUNDLE = bundle(PLUGIN_FILES)
BUNDLE_SHA = sha(BUNDLE)
BUNDLE_TREE = tree_sha256(PLUGIN_FILES)
GOOD = manifest(payload={"sha256": BUNDLE_SHA, "size": len(BUNDLE)})

os.makedirs(OUT, exist_ok=True)
BLOBS = os.path.join(OUT, "blobs")
os.makedirs(BLOBS, exist_ok=True)

BUNDLE_CORRUPT = b"\x00" + BUNDLE[1:]


def blob(name, data):
    """Vectors reference bulk bytes by filename so the JSON stays reviewable."""
    with open(os.path.join(BLOBS, name), "wb") as f:
        f.write(data)
    return name


BLOB_BUNDLE = blob("reference-bundle.tar", BUNDLE)
BLOB_CORRUPT = blob("reference-bundle-corrupt.tar", BUNDLE_CORRUPT)

# ===================== manifest vectors =====================
mcases = []


def mcase(cid, desc, m, code=None, raw=None):
    c = {"id": cid, "description": desc, "valid": code is None}
    if raw is not None:
        c["raw"] = raw
    else:
        c["manifest"] = m
        c["canonical"] = canon(m)
    if code:
        c["code"] = code
    mcases.append(c)


mcase("valid-minimal", "The reference device plugin: every required field, no optionals.", GOOD)
mcase("valid-signature-hash-only",
      "Every manifest states its trust model explicitly. hash-only with an "
      "empty entries list is the only shape v2 accepts.", GOOD)
mcase("valid-management-runtime",
      "The management tier parses the same as the device tier; the difference "
      "is which loader refuses it, not what the schema allows.",
      manifest(name="fleet_audit", type="auth", runtime="management",
               entry="plugins/auth/fleet_audit.py", payload=GOOD["payload"]))
mcase("valid-compat-wildcard", "'*' matches any model or firmware.",
      manifest(payload=GOOD["payload"], model_compat="*", firmware_compat="*"))
mcase("valid-compat-exact", "A bare token is an exact-match constraint.",
      manifest(payload=GOOD["payload"], model_compat="rm4pe", firmware_compat="1.10.0"))

mcase("malformed-not-json", "Not JSON at all.", None, "manifest.malformed", raw="{not json")
mcase("malformed-not-object", "Valid JSON, wrong shape.", None, "manifest.malformed", raw="[]")
mcase("malformed-unknown-field",
      "Unknown top-level fields are rejected, not ignored: the device and the "
      "server must never disagree about what a manifest said.",
      dict(GOOD, extra_field="surprise"), "manifest.malformed")
mcase("malformed-missing-name", "A required field is absent.",
      {k: v for k, v in GOOD.items() if k != "name"}, "manifest.malformed")
mcase("malformed-missing-payload", "payload is required.",
      {k: v for k, v in GOOD.items() if k != "payload"}, "manifest.malformed")

mcase("name-leading-underscore",
      "kvmd's existing get_plugin_class treats a leading underscore as unknown, "
      "so a manifest may not mint one.",
      manifest(name="_hidden", entry="plugins/ugpio/_hidden.py", payload=GOOD["payload"]),
      "manifest.bad_name")
mcase("name-uppercase", "Module names are lowercase.",
      manifest(name="Acme", entry="plugins/ugpio/Acme.py", payload=GOOD["payload"]),
      "manifest.bad_name")
mcase("name-dash", "A dash is not valid in a Python module name.",
      manifest(name="acme-relay", entry="plugins/ugpio/acme-relay.py", payload=GOOD["payload"]),
      "manifest.bad_name")
mcase("name-empty", "Empty name.",
      manifest(name="", entry="plugins/ugpio/acme_relay.py", payload=GOOD["payload"]),
      "manifest.bad_name")

mcase("type-unknown", "No loader exists for this type.",
      manifest(type="video", entry="plugins/video/acme_relay.py", payload=GOOD["payload"]),
      "manifest.bad_type")
mcase("runtime-unknown", "A security tier is never defaulted.",
      manifest(runtime="kernel", payload=GOOD["payload"]), "manifest.bad_runtime")
mcase("runtime-missing", "runtime is required.",
      {k: v for k, v in GOOD.items() if k != "runtime"}, "manifest.malformed")

mcase("entry-traversal",
      "Invariant 1: the manifest cannot express a path that escapes the loader root.",
      manifest(entry="plugins/ugpio/../../../etc/passwd", payload=GOOD["payload"]),
      "manifest.bad_entry")
mcase("entry-absolute", "Invariant 1: absolute paths are refused.",
      manifest(entry="/etc/kvmd/evil.py", payload=GOOD["payload"]), "manifest.bad_entry")
mcase("entry-backslash", "Invariant 1: backslash separators are refused.",
      manifest(entry="plugins\\ugpio\\acme_relay.py", payload=GOOD["payload"]),
      "manifest.bad_entry")
mcase("entry-not-py", "Only Python modules are loadable.",
      manifest(entry="plugins/ugpio/acme_relay.so", payload=GOOD["payload"]),
      "manifest.bad_entry")
mcase("entry-no-prefix", "entry must be rooted at plugins/.",
      manifest(entry="ugpio/acme_relay.py", payload=GOOD["payload"]), "manifest.bad_entry")
mcase("entry-type-mismatch",
      "Invariant 1: entry's type segment disagrees with type, so placement and "
      "description disagree. That is a refusal, never a redirection.",
      manifest(entry="plugins/atx/acme_relay.py", payload=GOOD["payload"]),
      "manifest.entry_type_mismatch")
mcase("entry-name-mismatch",
      "Invariant 1: entry's stem disagrees with name, which would let the "
      "manifest name one module and place another.",
      manifest(entry="plugins/ugpio/other_relay.py", payload=GOOD["payload"]),
      "manifest.entry_name_mismatch")

mcase("payload-hash-uppercase",
      "Canonical means one spelling; uppercase hex is a violation, not something to normalise.",
      manifest(payload={"sha256": BUNDLE_SHA.upper(), "size": len(BUNDLE)}),
      "manifest.bad_payload_hash")
mcase("payload-hash-short", "Not 64 hex characters.",
      manifest(payload={"sha256": "abc123", "size": len(BUNDLE)}), "manifest.bad_payload_hash")
mcase("payload-hash-nonhex", "Non-hex characters.",
      manifest(payload={"sha256": "z" * 64, "size": len(BUNDLE)}), "manifest.bad_payload_hash")
mcase("payload-size-zero", "An empty bundle is not a plugin.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": 0}), "manifest.bad_payload_size")
mcase("payload-size-negative", "Negative size.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": -1}), "manifest.bad_payload_size")
mcase("payload-too-large",
      "The receiver must buffer and hash the bundle before it may touch the disk, "
      "so an unbounded payload is a memory-exhaustion path the gate cannot cover.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": 8388609}), "manifest.payload_too_large")
mcase("payload-size-at-cap", "Exactly at the 8 MiB cap is allowed.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": 8388608}))

mcase("sandbox-non-empty-refused",
      "sandbox is reserved until a vocabulary exists. Accepting a declaration "
      "nothing enforces would be worse than having no field at all.",
      manifest(payload=GOOD["payload"], sandbox=["net.outbound"]),
      "manifest.sandbox_not_allowed")
mcase("sandbox-empty-ok", "An explicitly empty sandbox is accepted.",
      manifest(payload=GOOD["payload"], sandbox=[]))
mcase("sandbox-absent-ok", "An absent sandbox is accepted.", GOOD)
mcase("capabilities-is-not-a-field",
      "The old v1 name is now an unknown field. It was renamed because kazbek "
      "already uses 'capability' for subject-scoped permission keys, and two "
      "vocabularies under one word is a bug waiting to be written.",
      dict(GOOD, capabilities=[]), "manifest.malformed")

mcase("revision-missing", "revision is mandatory.",
      {k: v for k, v in GOOD.items() if k != "revision"}, "manifest.malformed")
mcase("revision-zero", "revision starts at 1.",
      manifest(revision=0, payload=GOOD["payload"]), "manifest.bad_revision")
mcase("revision-negative", "Negative revision.",
      manifest(revision=-3, payload=GOOD["payload"]), "manifest.bad_revision")
mcase("revision-non-integer", "A version string is not a revision.",
      manifest(revision="1.2.3", payload=GOOD["payload"]), "manifest.bad_revision")
mcase("revision-bool-rejected",
      "bool is an int subclass in Python; true is not a revision.",
      manifest(revision=True, payload=GOOD["payload"]), "manifest.bad_revision")
mcase("revision-large-ok", "A large monotonic counter is fine.",
      manifest(revision=2147483647, payload=GOOD["payload"]))

mcase("signature-missing",
      "The block is required so every manifest states its trust model "
      "explicitly; an absent block would leave 'unsigned' and 'omitted' "
      "indistinguishable, which is the ambiguity a downgrade lives in.",
      {k: v for k, v in GOOD.items() if k != "signature"}, "manifest.malformed")
mcase("signature-model-unknown",
      "A manifest declaring a trust model this implementation does not have is "
      "uninterpretable, not merely invalid.",
      manifest(payload=GOOD["payload"],
               signature={"model": "single-key", "entries": []}), "manifest.malformed")
mcase("signature-model-missing", "model is required inside the block.",
      manifest(payload=GOOD["payload"], signature={"entries": []}), "manifest.malformed")
mcase("signature-entries-missing", "entries is required inside the block.",
      manifest(payload=GOOD["payload"], signature={"model": "hash-only"}), "manifest.malformed")
mcase("signature-entries-non-empty",
      "A v2 implementation cannot check a signature and must not accept a "
      "manifest that claims one.",
      manifest(payload=GOOD["payload"],
               signature={"model": "hash-only",
                          "entries": [{"alg": "ed25519", "keyid": "k1", "value": "AAAA"}]}),
      "manifest.malformed")
mcase("signature-optional-members-ok",
      "threshold and expires are accepted now so the later models need no "
      "schema migration.",
      manifest(payload=GOOD["payload"],
               signature={"model": "hash-only", "entries": [],
                          "threshold": 2, "expires": "2027-01-01T00:00:00Z"}))
mcase("signature-unknown-member",
      "Unknown members inside the block are refused like any other.",
      manifest(payload=GOOD["payload"],
               signature={"model": "hash-only", "entries": [], "surprise": "x"}),
      "manifest.malformed")
mcase("signature-v1-shape-refused",
      "The v1 stub shape (alg/value/key_id) is no longer the schema.",
      manifest(payload=GOOD["payload"],
               signature={"alg": "ed25519", "key_id": "k", "value": "v"}), "manifest.malformed")

mcase("compat-bad-operator", "Only >=, <=, ==, bare token and * parse.",
      manifest(payload=GOOD["payload"], model_compat="~>rm1pe"), "manifest.bad_compat")
mcase("compat-empty", "An empty constraint does not parse.",
      manifest(payload=GOOD["payload"], firmware_compat=""), "manifest.bad_compat")

write("manifest.json", {
    "vectors_version": 1,
    "protocol_version": PROTOCOL_VERSION,
    "description": (
        "Manifest validation vectors. A case with 'raw' supplies the exact bytes to "
        "parse; otherwise encode 'manifest' canonically. 'canonical' is the expected "
        "canonical JSON encoding and must round-trip byte-stably."
    ),
    "cases": mcases,
})


# ===================== frame vectors =====================
# Frames whose bytes are small carry exact 'hex' — that is where the framing
# rules are pinned. The two bulk cases carry a 'construct' recipe instead, so
# the vector file stays something a human can read in a review.
fcases = []


def fcase(cid, desc, **kw):
    fcases.append({"id": cid, "description": desc, **kw})


def jframe(cid, desc, tid, sub, obj):
    fcase(cid, desc, hex=frame(tid, sub, canon(obj).encode("utf-8")).hex(),
          decoded={"tid": tid, "sub": sub, "json": obj})


jframe("offer", "server -> device: manifest only, no payload bytes.",
       TID_A, SUB_OFFER, {"manifest": GOOD, "v": PROTOCOL_VERSION})
jframe("fetch", "device -> server: request the bundle by manifest hash.",
       TID_A, SUB_FETCH, {"sha256": BUNDLE_SHA, "v": PROTOCOL_VERSION})

small = b"tiny bundle bytes"
fcase("payload-single-chunk-last",
      "A bundle that fits in one chunk: seq 0 with LAST set. This case pins the "
      "37-byte chunk header exactly — tid(32) sub(1) seq(4 BE) flags(1).",
      hex=frame(TID_B, SUB_PAYLOAD, struct.pack(">IB", 0, 0x01) + small).hex(),
      decoded={"tid": TID_B, "sub": SUB_PAYLOAD, "seq": 0, "flags": 1,
               "data_b64": b64(small)})
fcase("payload-unknown-flag-bit",
      "Unknown flags bits must refuse, so a flag added later cannot be silently "
      "ignored by an old device.",
      hex=frame(TID_A, SUB_PAYLOAD, struct.pack(">IB", 0, 0x02) + small).hex(),
      code="wire.bad_flags")
fcase("payload-chunk-at-max",
      "Exactly PAYLOAD_CHUNK_MAX data bytes is allowed.",
      construct={"tid": TID_A, "sub": SUB_PAYLOAD, "seq": 0, "flags": 0,
                 "data_repeat": {"byte": 65, "count": 32768}},
      decoded={"tid": TID_A, "sub": SUB_PAYLOAD, "seq": 0, "flags": 0})
fcase("payload-chunk-too-large",
      "One byte over PAYLOAD_CHUNK_MAX. Still inside the 65502 the uint16 "
      "envelope permits, so this limit is ours and must be enforced explicitly.",
      construct={"tid": TID_A, "sub": SUB_PAYLOAD, "seq": 0, "flags": 0,
                 "data_repeat": {"byte": 0, "count": 32769}},
      code="wire.chunk_too_large")

jframe("install-result-installed",
       "Verified, placed, loaded. A readback must follow.",
       TID_A, SUB_INSTALL_RESULT,
       {"reason": "", "sha256": BUNDLE_SHA, "state": "installed", "v": PROTOCOL_VERSION})
jframe("install-result-refused",
       "Invariant 3's observable signature: refused means nothing touched the "
       "disk, which is why it is a distinct state from failed.",
       TID_A, SUB_INSTALL_RESULT,
       {"reason": "verify.refused", "sha256": BUNDLE_SHA, "state": "refused", "v": PROTOCOL_VERSION})
jframe("install-result-noop",
       "Invariant 2: the same manifest pushed twice is a no-op.",
       TID_A, SUB_INSTALL_RESULT,
       {"reason": "", "sha256": BUNDLE_SHA, "state": "noop", "v": PROTOCOL_VERSION})
jframe("install-result-failed",
       "Verified but the load failed; the install was rolled back.",
       TID_A, SUB_INSTALL_RESULT,
       {"reason": "install.load_failed", "sha256": BUNDLE_SHA, "state": "failed", "v": PROTOCOL_VERSION})
jframe("readback",
       "Invariant 4: what is actually on disk, hashed by the device.",
       TID_A, SUB_READBACK,
       {"entries": [{"path": p, "sha256": sha(d)} for p, d in sorted(PLUGIN_FILES)],
        "sha256": BUNDLE_SHA, "tree_sha256": BUNDLE_TREE, "v": PROTOCOL_VERSION})

fcase("bad-frame-short-body",
      "A 32-byte body cannot carry tid+sub; short reads drop the connection, as "
      "every other message type in this protocol already does.",
      hex=(bytes([MSG_TYPE_PLUGIN]) + struct.pack(">H", 32) + b"a" * 32).hex(),
      code="wire.bad_frame")
fcase("bad-frame-empty-body", "Zero-length body.",
      hex=(bytes([MSG_TYPE_PLUGIN]) + struct.pack(">H", 0)).hex(),
      code="wire.bad_frame")
fcase("bad-frame-unknown-subtype", "Sub-type 0x05 is not defined in v1.",
      hex=frame(TID_A, 0x05, b"").hex(), code="wire.bad_frame")

write("frames.json", {
    "vectors_version": 1,
    "protocol_version": PROTOCOL_VERSION,
    "description": (
        "Wire frame vectors. 'hex' is the complete frame including the rtty envelope "
        "(type 0xF1, uint16 big-endian length) and must round-trip to identical bytes. "
        "'construct' cases build the frame from the recipe instead of embedding bulk "
        "bytes: data is data_repeat.byte repeated data_repeat.count times. Cases with "
        "'code' must be refused with that code."
    ),
    "msg_type": MSG_TYPE_PLUGIN,
    "payload_chunk_max": 32768,
    "tid_len": 32,
    "cases": fcases,
})

# ===================== verify gate vectors =====================
vcases = []


def vcase(cid, desc, verifier, m, payload_blob, code=None):
    vcases.append({
        "id": cid, "description": desc, "verifier": verifier,
        "manifest": m, "payload_blob": payload_blob,
        "expect": ("refuse" if code else "accept"),
        **({"code": code} if code else {}),
    })


SIZED = manifest(payload={"sha256": BUNDLE_SHA, "size": len(BUNDLE)})

vcase("gate-hashonly-accept",
      "The v1 floor: integrity without authenticity.",
      "hash-only", GOOD, BLOB_BUNDLE)
vcase("gate-hashonly-corrupt-payload",
      "One flipped byte, same length — so this is caught by the hash and not by "
      "the size check.",
      "hash-only", SIZED, BLOB_CORRUPT, "payload.hash_mismatch")
vcase("gate-noop-accept",
      "noop accepts any payload. Dev only, and never a default in any real config.",
      "noop", SIZED, BLOB_CORRUPT)
vcase("gate-noop-still-validates-manifest",
      "The reason noop is survivable at all: it disables authenticity checking, "
      "not path safety. Structural validation runs for every verifier.",
      "noop", manifest(entry="plugins/ugpio/../../evil.py", payload=SIZED["payload"]),
      BLOB_BUNDLE, "manifest.bad_entry")
vcase("gate-noop-still-checks-size",
      "Gate step 2 holds even when the configured verifier does not hash.",
      "noop", manifest(payload={"sha256": BUNDLE_SHA, "size": len(BUNDLE) + 1}),
      BLOB_BUNDLE, "payload.size_mismatch")

vcase("gate-alwaysfail-refuses-valid-input",
      "INVARIANT 3, the load-bearing one: an otherwise perfectly valid offer is "
      "refused, and nothing may touch the disk. Mutation-check this case by "
      "removing the refuse-on-fail branch from the gate; the test must go red.",
      "always-fail", GOOD, BLOB_BUNDLE, "verify.refused")
vcase("gate-order-manifest-before-verify",
      "Precedence is part of the contract: a manifest violation is reported even "
      "when the verifier would also refuse, so the two implementations cannot "
      "disagree about which code comes back.",
      "always-fail", manifest(entry="plugins/atx/acme_relay.py", payload=SIZED["payload"]),
      BLOB_BUNDLE, "manifest.entry_type_mismatch")
vcase("gate-order-size-before-verify",
      "Gate step 2 precedes step 3.",
      "always-fail", manifest(payload={"sha256": BUNDLE_SHA, "size": 99}),
      BLOB_BUNDLE, "payload.size_mismatch")
vcase("gate-order-manifest-before-size",
      "Gate step 1 precedes step 2: both are wrong, the manifest code wins.",
      "hash-only", manifest(name="_bad", entry="plugins/ugpio/_bad.py",
                            payload={"sha256": BUNDLE_SHA, "size": 99}),
      BLOB_BUNDLE, "manifest.bad_name")

vcase("gate-unconfigured-fails-closed",
      "An absent verifier name resolves to a refusal, never to noop.",
      "", GOOD, BLOB_BUNDLE, "verify.unconfigured")
vcase("gate-unknown-verifier-fails-closed",
      "'signed' is deliberately not a v1 tier: naming it must fail closed rather "
      "than silently downgrade.",
      "signed", GOOD, BLOB_BUNDLE, "verify.unconfigured")

write("verify.json", {
    "vectors_version": 1,
    "protocol_version": PROTOCOL_VERSION,
    "description": (
        "Verify-gate vectors. Run Gate(verifier, manifest, payload) where payload is "
        "the bytes of vectors/blobs/<payload_blob>, and assert the outcome. Gate order "
        "is 1) validate manifest 2) check payload length against manifest.payload.size "
        "3) call the verifier; the ordering cases pin that precedence down."
    ),
    "cases": vcases,
})

# ===================== tree hash vectors =====================
tcases = []


def tcase(cid, desc, files):
    tcases.append({
        "id": cid, "description": desc,
        "files": [{"path": p, "content_b64": b64(d)} for p, d in files],
        "tree_sha256": tree_sha256(files),
    })


tcase("empty", "An empty tree hashes to the sha256 of the empty string.", [])
tcase("single-file", "One file.", [("plugins/ugpio/a.py", b"x\n")])
tcase("reference-plugin", "The reference bundle's placed tree.", PLUGIN_FILES)
tcase("sort-order-is-bytewise",
      "Paths sort bytewise, not by locale: uppercase (0x41+) sorts before '_' "
      "(0x5f), which sorts before lowercase (0x61+).",
      [("plugins/ugpio/b.py", b"b"), ("plugins/ugpio/A.py", b"A"),
       ("plugins/ugpio/_z.py", b"z"), ("plugins/ugpio/a.py", b"a")])
tcase("nested-paths",
      "Nested directories are represented by path only; directories are not hashed.",
      [("plugins/hid/x/y.py", b"y"), ("plugins/hid/x.py", b"x")])
tcase("same-content-different-paths",
      "Path is part of the hash, so identical content at different paths differs.",
      [("plugins/atx/p.py", b"same"), ("plugins/atx/q.py", b"same")])
tcase("empty-file",
      "A zero-byte file still contributes its path and the hash of no bytes.",
      [("plugins/msd/empty.py", b"")])

write("treehash.json", {
    "vectors_version": 1,
    "protocol_version": PROTOCOL_VERSION,
    "description": (
        "Canonical tree hash vectors. Both sides must compute these identically or "
        "every readback comparison is meaningless. Algorithm: for each regular file, "
        "sha256_hex(content) + two spaces + POSIX relative path + newline; concatenate "
        "in bytewise path order; sha256_hex the result."
    ),
    "cases": tcases,
})

# ===================== bundle vectors =====================
bcases = []


def bcase(cid, desc, data, code=None, files=None, blob_name=None):
    c = {"id": cid, "description": desc,
         "blob": (blob_name if blob_name else blob(cid + ".tar", data))}
    if code:
        c["code"] = code
    else:
        c["files"] = [{"path": p, "sha256": sha(d)} for p, d in sorted(files or [])]
        c["tree_sha256"] = tree_sha256(files or [])
    bcases.append(c)


def raw_tar(entries):
    """Build a tar directly so unsafe entries can be expressed."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for info, data in entries:
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tf.addfile(info, io.BytesIO(data) if data is not None else None)
    return buf.getvalue()


def reg(path, size):
    i = tarfile.TarInfo(path)
    i.type, i.mode, i.size = tarfile.REGTYPE, 0o644, size
    return i


bcase("valid-reference", "The reference bundle unpacks to the reference tree.",
      BUNDLE, files=PLUGIN_FILES, blob_name=BLOB_BUNDLE)
bcase("unsafe-absolute-path",
      "Invariant 1: an absolute entry path would place outside the loader root.",
      raw_tar([(reg("/etc/kvmd/evil.py", 2), b"x\n")]), "bundle.unsafe_path")
bcase("unsafe-traversal",
      "Invariant 1: '..' escapes the loader root.",
      raw_tar([(reg("plugins/ugpio/../../../evil.py", 2), b"x\n")]), "bundle.unsafe_path")
bcase("unsafe-backslash",
      "Backslash separators are refused rather than normalised.",
      raw_tar([(reg("plugins\\ugpio\\evil.py", 2), b"x\n")]), "bundle.unsafe_path")


def symlink(path, target):
    i = tarfile.TarInfo(path)
    i.type, i.mode, i.size, i.linkname = tarfile.SYMTYPE, 0o777, 0, target
    return i


bcase("unsafe-symlink",
      "A symlink can redirect a later write outside the root, so v1 bundles carry "
      "regular files only.",
      raw_tar([(symlink("plugins/ugpio/link.py", "/etc/shadow"), None)]),
      "bundle.unsafe_entry")


def directory(path):
    i = tarfile.TarInfo(path)
    i.type, i.mode, i.size = tarfile.DIRTYPE, 0o755, 0
    return i


bcase("unsafe-directory-entry",
      "Directories are implied by file paths and are not carried as entries, so "
      "their modes cannot be smuggled in.",
      raw_tar([(directory("plugins/ugpio/"), None)]), "bundle.unsafe_entry")
bcase("malformed-not-a-tar", "Not a readable ustar archive.",
      b"this is not a tar archive at all, not even close\n", "bundle.malformed")

write("bundles.json", {
    "vectors_version": 1,
    "protocol_version": PROTOCOL_VERSION,
    "description": (
        "Bundle unpacking vectors. Read vectors/blobs/<blob>. A case with 'code' must "
        "be refused with that code before anything is written. A valid case must "
        "unpack to exactly 'files' and hash to 'tree_sha256'. These checks are "
        "structural and run regardless of which Verifier is configured — they are "
        "what makes a noop verifier survivable."
    ),
    "cases": bcases,
})

# ===================== offer admission vectors =====================
# Admission runs before a fetch is sent and before any chunk moves. It is a
# distinct check from the verify gate's step 2, which compares the *assembled*
# length against the declared size and cannot run until the bytes have arrived.
acases = []


def acase(cid, desc, m, code=None, installed=0):
    acases.append({
        "id": cid, "description": desc, "manifest": m,
        "installed_revision": installed,
        "expect": ("refuse" if code else "admit"),
        **({"code": code} if code else {}),
    })


acase("admit-reference", "The reference manifest is admitted with nothing installed.", GOOD)
acase("admit-at-cap",
      "A declared size exactly at the 8 MiB ceiling is admitted.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": 8388608}))
acase("refuse-over-cap",
      "One byte over the ceiling. Because a dropped transfer restarts from "
      "chunk 0, an untransferable bundle must be refused while it is still a "
      "declaration rather than discovered on the last chunk.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": 8388609}), "manifest.payload_too_large")
acase("refuse-absurd-size",
      "A wildly oversized declaration is refused without allocating anything.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": 4294967296}), "manifest.payload_too_large")
acase("refuse-zero-size", "An empty bundle is not a plugin.",
      manifest(payload={"sha256": BUNDLE_SHA, "size": 0}), "manifest.bad_payload_size")
acase("refuse-unsafe-entry",
      "Admission validates the whole manifest, so a traversal entry never "
      "reaches the point of transferring bytes.",
      manifest(entry="plugins/ugpio/../../evil.py", payload=GOOD["payload"]), "manifest.bad_entry")
acase("refuse-sandbox-declaration",
      "Reserved fields fail closed at admission too.",
      manifest(payload=GOOD["payload"], sandbox=["net.outbound"]),
      "manifest.sandbox_not_allowed")

# ----- anti-rollback: an integer comparison, no signing model required -----
acase("rollback-upgrade-admitted",
      "A higher revision than the installed one is the normal upgrade path.",
      manifest(revision=5, payload=GOOD["payload"]), installed=4)
acase("rollback-first-install-admitted",
      "No installed revision is 0, so any valid revision is an upgrade.",
      manifest(revision=1, payload=GOOD["payload"]), installed=0)
acase("rollback-equal-refused",
      "Equal is refused, not just lower: re-serving the identical revision is "
      "the freeze half of the attack class. Idempotent re-push is handled by "
      "the payload-hash noop path, not by accepting a stale revision.",
      manifest(revision=4, payload=GOOD["payload"]), "policy.rollback_refused", installed=4)
acase("rollback-lower-refused",
      "The downgrade case: a genuinely-authored older plugin with a known flaw, "
      "re-served. Closed by an integer comparison, independent of any signing "
      "model -- which is why it lands now rather than with signing.",
      manifest(revision=2, payload=GOOD["payload"]), "policy.rollback_refused", installed=7)
acase("rollback-far-lower-refused",
      "Revision 1 against a long-running install.",
      manifest(revision=1, payload=GOOD["payload"]), "policy.rollback_refused", installed=999)
acase("rollback-checked-after-manifest",
      "A manifest violation is reported even when the revision is also stale, "
      "so the two implementations cannot disagree about which code comes back.",
      manifest(revision=1, entry="plugins/atx/acme_relay.py", payload=GOOD["payload"]),
      "manifest.entry_type_mismatch", installed=9)

write("admission.json", {
    "vectors_version": 1,
    "protocol_version": PROTOCOL_VERSION,
    "description": (
        "Offer-admission vectors. Run admit(manifest, installed_revision) -- the check "
        "a device performs on plugin.offer, BEFORE sending plugin.fetch and before any "
        "payload chunk moves. An 'admit' case must pass; a 'refuse' case must refuse "
        "with the given code and no fetch may be sent. installed_revision is the "
        "revision currently installed for this manifest's name, or 0 if none is. "
        "Admission neither sees nor needs the payload, which is exactly what "
        "distinguishes it from the verify gate."
    ),
    "cases": acases,
})
