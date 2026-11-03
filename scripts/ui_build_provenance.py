"""Validate declared UI inputs and emitted bytes independently of the Node builder."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

PROFILE = "bms-ui-build-provenance/1"
REBUILD = "Rebuild the UI with npm run build in web/ before packaging."
EXTENSIONS = {".js", ".css", ".map", ".woff", ".woff2", ".svg", ".png"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate UI build proof key.")
        result[key] = value
    return result


def nonfinite(_):
    raise ValueError("Nonfinite UI build proof value.")


def read_json(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Missing or unsupported UI build proof/profile. " + REBUILD)
    return json.loads(
        path.read_bytes(),
        object_pairs_hook=pairs,
        parse_constant=nonfinite,
    )


def relative(value):
    if (
        not isinstance(value, str)
        or len(value) > 1024
        or "\\" in value
        or re.search(r"[\x00-\x1f\x7f]", value)
        or re.match(r"^[A-Za-z]:", value)
        or value.startswith("/")
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError("Unsupported UI build path.")
    return value


def input_files(root, profile):
    result, total = {}, 0
    limits = profile["limits"]

    def visit(name, required=True):
        nonlocal total
        full = root / relative(name)
        if full.is_symlink():
            raise ValueError("UI build inputs must not be symlinks: " + name)
        if not full.exists():
            if required:
                raise ValueError("Missing UI build input: " + name + ". " + REBUILD)
            return
        if full.is_dir():
            for child in sorted(full.iterdir()):
                visit(name + "/" + child.name)
            return
        if name in result:
            return
        if not full.is_file() or full.stat().st_size > limits["file_bytes"]:
            raise ValueError("Unsupported UI build input: " + name)
        raw = full.read_bytes()
        total += len(raw)
        if (
            len(raw) > limits["file_bytes"]
            or len(result) >= limits["files"]
            or total > limits["input_bytes"]
        ):
            raise ValueError("UI build inputs exceed the supported size.")
        result[name] = {"bytes": len(raw), "sha256": sha(raw)}

    for name in profile["fixed"]:
        visit(name)
    for name in profile["trees"]:
        visit(name, name == "web/src")
    for name in profile["optional"]:
        visit(name, False)
    return result


def output_files(root, limits):
    result, total = {}, 0
    dist = root / "web/dist"
    if dist.is_symlink() or not dist.is_dir():
        raise ValueError("Missing or unsupported UI output. " + REBUILD)

    def visit(directory):
        nonlocal total
        for full in sorted(directory.iterdir()):
            if full.is_symlink():
                raise ValueError("Built UI must not contain symlinks.")
            if full.is_dir():
                visit(full)
                continue
            path = full.relative_to(dist)
            if (
                not full.is_file()
                or full.stat().st_size > limits["file_bytes"]
                or path != Path("index.html")
                and not (
                    len(path.parts) == 2 and path.parts[0] == "assets" and path.suffix in EXTENSIONS
                )
            ):
                raise ValueError("Unexpected built UI file: " + path.as_posix())
            raw = full.read_bytes()
            total += len(raw)
            if (
                len(raw) > limits["file_bytes"]
                or len(result) >= limits["files"]
                or total > limits["output_bytes"]
            ):
                raise ValueError("Built UI exceeds the supported size.")
            result[path.as_posix()] = {"bytes": len(raw), "sha256": sha(raw)}

    visit(dist)
    if "index.html" not in result:
        raise ValueError("Missing UI entry page. " + REBUILD)
    return result


def environment():
    return {
        key: sha(value.encode())
        for key, value in os.environ.items()
        if key == "NODE_ENV" or key.startswith("VITE_")
    }


def validate(root):
    root = Path(root)
    try:
        profile = read_json(root / "scripts/ui_build_profile.json", 64 * 1024)
        if profile.get("profile") != "bms-ui-build-inputs/1":
            raise ValueError("Unknown UI input profile.")
        ceilings = {
            "files": 4096,
            "file_bytes": 16777216,
            "input_bytes": 67108864,
            "output_bytes": 134217728,
            "proof_bytes": 1048576,
        }
        if (
            set(profile) != {"profile", "fixed", "trees", "optional", "limits"}
            or not all(
                type(profile[k]) is list
                and len(profile[k]) <= 128
                and all(isinstance(v, str) for v in profile[k])
                for k in ("fixed", "trees", "optional")
            )
            or type(profile["limits"]) is not dict
            or set(profile["limits"]) != set(ceilings)
            or not all(
                type(profile["limits"][k]) is int and 0 < profile["limits"][k] <= maximum
                for k, maximum in ceilings.items()
            )
        ):
            raise ValueError("Unsupported UI input profile shape or limits.")
        limits = profile["limits"]
        proof = read_json(root / "web/.bms-ui-build.json", limits["proof_bytes"])
        expected = {
            "profile",
            "input_profile",
            "recipe",
            "mode",
            "tools",
            "environment",
            "inputs",
            "outputs",
            "proof_sha256",
        }
        if (
            type(proof) is not dict
            or set(proof) != expected
            or proof["profile"] != PROFILE
            or proof["input_profile"] != profile["profile"]
            or proof["recipe"] != "snapshot-tsc-vite-production/1"
            or proof["mode"] != "production"
            or not isinstance(proof["proof_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", proof["proof_sha256"])
            or sha(canonical({key: value for key, value in proof.items() if key != "proof_sha256"}))
            != proof["proof_sha256"]
        ):
            raise ValueError("Unsupported or altered UI build proof.")
        for name in ("inputs", "outputs"):
            if type(proof[name]) is not dict or len(proof[name]) > limits["files"]:
                raise ValueError("Unsupported UI build file map.")
            for path, row in proof[name].items():
                relative(path)
                if (
                    type(row) is not dict
                    or set(row) != {"bytes", "sha256"}
                    or type(row["bytes"]) is not int
                    or not 0 <= row["bytes"] <= limits["file_bytes"]
                    or not isinstance(row["sha256"], str)
                    or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
                ):
                    raise ValueError("Unsupported UI build file record.")
        if proof["inputs"] != input_files(root, profile):
            raise ValueError("UI source inputs differ from the compiled snapshot.")
        if proof["outputs"] != output_files(root, limits):
            raise ValueError("UI assets differ from the compiled snapshot.")
        if proof["environment"] != environment():
            raise ValueError("UI build environment changed.")
        tools = proof["tools"]
        if (
            type(tools) is not dict
            or set(tools) != {"node", "typescript", "vite"}
            or not all(
                isinstance(v, str)
                and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", v)
                for v in tools.values()
            )
        ):
            raise ValueError("Unsupported UI compiler versions.")
        lock = read_json(root / "web/package-lock.json", limits["file_bytes"])
        if any(
            tools[name] != lock["packages"]["node_modules/" + name]["version"]
            for name in ("typescript", "vite")
        ):
            raise ValueError("UI compiler versions differ from the package lock.")
        return proof
    except (ValueError, KeyError, TypeError, AttributeError, OSError, UnicodeError) as exc:
        raise ValueError(str(exc) + " " + REBUILD) from exc
