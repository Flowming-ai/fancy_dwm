#!/usr/bin/env python3
"""Maintainer command: record intentional, reviewed source/configuration edits."""
from pathlib import Path
import hashlib
import subprocess

root = Path(__file__).resolve().parents[1]
files = subprocess.check_output(
    ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
).decode().split("\0")
lines = []
for name in sorted(set(files)):
    if not name or name == "SHA256SUMS":
        continue
    path = root / name
    if path.is_symlink():
        raise SystemExit("Unexpected symlink: " + name)
    if path.is_file():
        lines.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + name)
(root / "SHA256SUMS").write_text("\n".join(lines) + "\n")
print(f"Recorded {len(lines)} files in SHA256SUMS.")
