"""Audit publishable files/history using private rules; never print matched values.

Site networks and known passwords belong in an external, untracked JSON file.
The tool only reads repository content; it does not rewrite history or revoke keys.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

IPV4 = re.compile(rb"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)")
COMMON = (
    (
        "github-token",
        re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{50,255})"),
    ),
    (
        "private-key",
        re.compile(
            rb"(?m)^-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----\r?\n"
            rb"(?:[A-Za-z0-9+/=]{16,}\r?\n)+"
            rb"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
)
MAX_BLOB = 64 * 1024 * 1024


def rules(document):
    """Keep literals in memory and reject invalid profiles without echoing them."""
    try:
        networks = tuple(
            ipaddress.ip_network(s, strict=False) for s in document.get("networks", [])
        )
        literals = []
        for label, value in document.get("secrets", {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label) or not isinstance(value, str):
                raise ValueError
            if len(value) < 4:
                raise ValueError
            variants = {
                value.encode(),
                value.encode("utf-16le"),
                quote(value, safe="").encode(),
                base64.b64encode(value.encode()),
                json.dumps(value, ensure_ascii=True)[1:-1].encode(),
            }
            literals.extend((label, variant) for variant in variants)
        return {"networks": networks, "literals": tuple(literals)}
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid private audit rules; values were not printed.") from None


def scan_bytes(data, private):
    """Find positions/categories only. Returned records never contain the match."""
    found = set()
    for label, pattern in COMMON:
        found.update((m.start(), label) for m in pattern.finditer(data))
    for match in IPV4.finditer(data):
        try:
            address = ipaddress.ip_address(match.group().decode("ascii"))
        except ValueError:
            continue
        if any(address in net for net in private["networks"]):
            found.add((match.start(), "configured-network-address"))
    for label, literal in private["literals"]:
        start = 0
        while (offset := data.find(literal, start)) >= 0:
            found.add((offset, "known-secret:" + label))
            start = offset + len(literal)
    return [
        {"line": data.count(b"\n", 0, offset) + 1, "kind": label} for offset, label in sorted(found)
    ]


def safe_location(location, private):
    if scan_bytes(location.encode(), private):
        return "<redacted-location-" + hashlib.sha256(location.encode()).hexdigest()[:12] + ">"
    return location


def git(root, *args, data=None):
    result = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError("Git inspection failed; command output was withheld.")
    return result.stdout


def scan_worktree(root, private):
    findings, skipped, scanned = [], [], 0
    for raw in git(root, "ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = root / name
        location = safe_location(name, private)
        if path.is_symlink():
            data = os.readlink(path).encode()
        elif path.is_file() and path.stat().st_size <= MAX_BLOB:
            data = path.read_bytes()
        else:
            skipped.append({"location": location, "reason": "missing-or-oversized"})
            continue
        scanned += 1
        findings.extend({"location": location, **row} for row in scan_bytes(data, private))
    return {"objects_scanned": scanned, "findings": findings, "skipped": skipped}


def scan_history(root, private):
    """Read unique reachable blobs and commits, including deleted historical files."""
    names = {}
    for line in git(root, "rev-list", "--objects", "--all").splitlines():
        oid, _, path = line.partition(b" ")
        names.setdefault(oid.decode(), os.fsdecode(path) if path else "<commit>")
    checks = git(
        root,
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        data="".join(oid + "\n" for oid in names).encode(),
    )
    wanted, skipped = [], []
    for line in checks.decode().splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[1] not in ("blob", "commit"):
            continue
        oid, kind, size = parts
        location = safe_location(names[oid], private)
        if int(size) > MAX_BLOB:
            skipped.append({"object": oid, "location": location, "reason": "oversized"})
        else:
            wanted.append((oid, kind, location))
    process = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    findings = []
    try:
        for oid, kind, location in wanted:
            process.stdin.write((oid + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3 or header[0].decode() != oid:
                raise ValueError("Historical object inspection did not match its request.")
            size = int(header[2])
            data = process.stdout.read(size)
            if len(data) != size or process.stdout.read(1) != b"\n":
                raise ValueError("Historical object inspection was incomplete.")
            findings.extend(
                {"object": oid, "object_type": kind, "location": location, **row}
                for row in scan_bytes(data, private)
            )
    finally:
        process.stdin.close()
        process.stdout.close()
        process.wait()
    return {"objects_scanned": len(wanted), "findings": findings, "skipped": skipped}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--private-rules", type=Path)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.private_rules.read_text()) if args.private_rules else {}
        private = rules(document)
        result = (scan_history if args.history else scan_worktree)(args.root, private)
    except (ValueError, OSError, json.JSONDecodeError):
        parser.exit(
            2, "Audit could not complete; private values and command output were withheld.\n"
        )
    result.update(
        profile="publishable-privacy-audit/1",
        scope="reachable-git-history" if args.history else "tracked-working-files",
        custom_rules_loaded=bool(args.private_rules),
        complete=not result["skipped"],
    )
    text = json.dumps(result, indent=2) + "\n"
    if args.output:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.chmod(args.output, 0o600)
    else:
        print(text, end="")
    return int(bool(result["findings"] or result["skipped"]))


if __name__ == "__main__":
    raise SystemExit(main())
