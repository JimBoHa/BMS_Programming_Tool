#!/usr/bin/env python3
"""Build a pinned external MatIEC compiler in a private source/build directory.

No upstream source is modified or redistributed by this repository. GNU Bison
is built privately when the system parser generator is too old. The direct
build follows the pinned Makefile.am compilation units without requiring a
system installation of Autoconf/Automake or changing the shell environment.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "3a41303bcb4e50403417bc39c63f88981d7d961e"
BISON_URL = "https://ftp.gnu.org/gnu/bison/bison-3.8.2.tar.xz"
BISON_SHA256 = "9bba0214ccf7f1079c5d59210045227bcf619519840ebfa80cd3849cff5a5bf2"


def run(args, *, cwd=None, env=None, timeout=600):
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True, timeout=timeout)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def library_digest(directory):
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def parser_generator(tools):
    binary = tools / "bison-3.8.2-install/bin/bison"
    if binary.is_file():
        return binary
    tools.mkdir(parents=True, exist_ok=True)
    archive = tools / "bison-3.8.2.tar.xz"
    if not archive.exists():
        request = urllib.request.Request(BISON_URL, headers={"User-Agent": "BMS-Studio-build/1"})
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read(8 * 1024 * 1024)
            if response.read(1):
                raise SystemExit("Bison source archive exceeds build limit.")
        archive.write_bytes(content)
    if sha256(archive) != BISON_SHA256:
        raise SystemExit("Bison source checksum differs from the pinned primary packaging record.")
    source = tools / "bison-3.8.2"
    if not source.exists():
        with tarfile.open(archive) as package:
            package.extractall(tools, filter="data")
    prefix = binary.parents[1]
    run(
        [source / "configure", "--prefix=" + str(prefix), "--disable-nls", "M4=/usr/bin/m4"],
        cwd=source,
    )
    run(["make", "-j4"], cwd=source)
    run(["make", "install"], cwd=source)
    return binary


def setup(source, destination):
    for executable in ("git", "clang", "clang++", "flex", "make"):
        if not shutil.which(executable):
            raise SystemExit("Required build tool is unavailable: " + executable)
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "https://github.com/beremiz/matiec.git", source])
        run(["git", "checkout", "--detach", PIN], cwd=source)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if actual != PIN:
        raise SystemExit("Expected MatIEC revision " + PIN + ", found " + actual)
    changed = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=source, text=True
    )
    if changed.strip():
        raise SystemExit(
            "MatIEC checkout has changes or untracked files; use a clean pinned checkout."
        )
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / ".build.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        bison = parser_generator(destination.parent / "iec-build-tools")
        stage = destination / "source"
        if stage.exists():
            shutil.rmtree(stage)
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        # No platform substitutions are needed by this pinned compiler. Its
        # only config/config.h consumers use these package identity strings.
        (stage / "config/config.h").write_text(
            '#define PACKAGE_NAME "matiec"\n#define PACKAGE_VERSION "0.1"\n'
        )
        run(
            [bison, "-d", "-Wno-yacc", "-o", "iec_bison.cc", "iec_bison.yy"],
            cwd=stage / "stage1_2",
            env={
                **os.environ,
                "BISON_PKGDATADIR": str(bison.parents[1] / "share/bison"),
                "M4": "/usr/bin/m4",
            },
        )
        run(["flex", "--warn", "-oiec_flex.cc", "iec_flex.ll"], cwd=stage / "stage1_2")
        units = [
            stage / "main.cc",
            stage / "stage4/stage4.cc",
            stage / "stage4/generate_c/generate_c.cc",
        ]
        for directory in ("absyntax", "absyntax_utils", "stage3"):
            units += sorted((stage / directory).glob("*.cc"))
        units += [
            stage / "stage1_2" / name
            for name in (
                "iec_bison.cc",
                "iec_flex.cc",
                "stage1_2.cc",
                "create_enumtype_conversion_functions.cc",
            )
        ]
        objects = destination / "objects"
        objects.mkdir(exist_ok=True)

        def compile_unit(unit):
            output = objects / (str(unit.relative_to(stage)).replace("/", "_") + ".o")
            run(
                [
                    "clang++",
                    "-std=c++11",
                    "-O2",
                    "-Wno-deprecated-register",
                    "-DYY_BUF_SIZE=65536",
                    '-DDEFAULT_LIBDIR="' + str(stage / "lib") + '"',
                    '-DHGVERSION="' + PIN + '"',
                    "-I" + str(stage / "stage1_2"),
                    "-c",
                    unit,
                    "-o",
                    output,
                ]
            )
            return output

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            built = list(pool.map(compile_unit, units))
        binary = destination / "bin/iec2c"
        binary.parent.mkdir(exist_ok=True)
        run(["clang++", *built, "-o", binary])
        manifest = {
            "format": "bms-iec-toolchain/1",
            "repository": "https://github.com/beremiz/matiec",
            "revision": PIN,
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "host_c_compiler": subprocess.check_output(["clang", "--version"], text=True).strip(),
            "binary_sha256": sha256(binary),
            "library_sha256": library_digest(stage / "lib"),
            "bison_url": BISON_URL,
            "bison_sha256": BISON_SHA256,
            "build": "private source copy; system clang++ C++11; no compiler/runtime source patches",
            "compiler_license": "GPL-3.0-or-later; runtime headers have individual LGPL notices",
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        run([binary, "-v"])
        print("Private IEC toolchain ready:", destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT.parent / "Reference_Sources/matiec")
    parser.add_argument(
        "--destination", type=Path, default=ROOT.parent / ".toolchain" / ("matiec-" + PIN[:12])
    )
    args = parser.parse_args()
    setup(args.source.resolve(), args.destination.resolve())


if __name__ == "__main__":
    main()
