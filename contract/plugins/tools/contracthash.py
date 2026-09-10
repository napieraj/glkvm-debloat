"""Compute CONTRACT-SHA256: the canonical tree hash of the normative contract.

Deliberately the same algorithm as the readback tree hash in wire.md, so both
repos verify contract sync with the function they already had to implement.

CONTRACT-SHA256 itself and tools/ are excluded. tools/ is machinery, not
contract: a cosmetic edit to the generator must not move the hash and make
every repo that has not yet pulled it report a spurious mismatch. A generator
change that actually changes the vectors still moves the hash, because
vectors/ is inside the hashed set.
"""
import hashlib, os, sys

root = sys.argv[1]
files = []
EXCLUDED_DIRS = {"tools"}

for dirpath, dirnames, names in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS or dirpath != root]
    if os.path.relpath(dirpath, root).split(os.sep)[0] in EXCLUDED_DIRS:
        continue
    for n in names:
        if n == "CONTRACT-SHA256":
            continue
        full = os.path.join(dirpath, n)
        files.append((os.path.relpath(full, root).replace(os.sep, "/"), full))

lines = b""
for rel, full in sorted(files, key=lambda f: f[0].encode("utf-8")):
    with open(full, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    lines += (h + "  " + rel + "\n").encode("utf-8")
print(hashlib.sha256(lines).hexdigest())
