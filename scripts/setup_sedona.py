#!/usr/bin/env python3
"""Build the pinned Sedona compiler and an experimental loopback-only 64-bit SVM.

The SDK remains an external AFL-3.0 dependency. All upstream source stays intact.
Port changes are applied to build copies and are reproduced below. This script
does not install a system Java runtime or alter shell startup files.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import platform
import shutil
import subprocess
from pathlib import Path

PIN = "406b11f3816fb00db6482640f9cf3397b874b515"
ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd=None):
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def setup(sdk, java_home):
    if not sdk.exists():
        sdk.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "https://github.com/linsong/sedona.git", sdk])
        run(["git", "checkout", "--detach", PIN], cwd=sdk)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=sdk, text=True).strip()
    if actual != PIN:
        raise SystemExit(
            f"Expected SDK revision {PIN}, found {actual}. Use a separate pinned checkout."
        )
    changed = subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=sdk, text=True)
    if changed.strip():
        raise SystemExit("SDK tracked files have local changes. Use a clean pinned checkout.")
    with (sdk / ".bms-toolchain.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            build(sdk, java_home)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def build(sdk, java_home):
    java = java_home / "bin"
    for module in ("sedona", "sedonac"):
        source = sdk / "src" / module / "src"
        classes = sdk / "build" / ("classes-" + module)
        classes.mkdir(parents=True, exist_ok=True)
        args = [java / "javac", "--release", "8", "-d", classes]
        if module == "sedonac":
            args += ["-classpath", sdk / "lib/sedona.jar"]
        run(args + sorted(source.rglob("*.java")))
        if module == "sedona":
            (classes / "version.txt").write_text("version=1.2.29\ntime=local-build\n")
        else:
            # Upstream FieldLayout assumes reference fields are four bytes.
            # Retain its four-byte packing order and reserve the actual pointer width.
            upstream = source / "sedonac/steps/FieldLayout.java"
            original = "sizeMatch = (sizeof == refSize && !f.isInline());"
            patched = "sizeMatch = (sizeof == 4 && !f.isInline());\n        offIncr = refSize;"
            if upstream.read_text().count(original) != 1:
                raise SystemExit("Unexpected upstream compiler source; port patch was not applied.")
            copy = sdk / "build/FieldLayout.java"
            copy.write_text(upstream.read_text().replace(original, patched))
            run(
                [
                    java / "javac",
                    "--release",
                    "8",
                    "-classpath",
                    os.pathsep.join([str(sdk / "lib/sedona.jar"), str(classes)]),
                    "-d",
                    classes,
                    copy,
                ]
            )
            # Null-reference comparison must use ObjEq rather than testing only
            # the low 32 bits of a pointer. Disabling this optional optimization
            # also keeps generated kits usable on four-byte platforms.
            upstream = source / "sedonac/steps/OptimizeIr.java"
            original = "if (a.opcode == SCode.LoadNull)"
            if upstream.read_text().count(original) != 1:
                raise SystemExit("Unexpected null optimizer; port patch was not applied.")
            copy = sdk / "build/OptimizeIr.java"
            copy.write_text(upstream.read_text().replace(original, original[:-1] + " && false)"))
            run(
                [
                    java / "javac",
                    "--release",
                    "8",
                    "-classpath",
                    os.pathsep.join([str(sdk / "lib/sedona.jar"), str(classes)]),
                    "-d",
                    classes,
                    copy,
                ]
            )
        run([java / "jar", "cf", sdk / "lib" / f"{module}.jar", "-C", classes, "."])

    def compile(*args):
        run(
            [
                java / "java",
                "-Dsedona.home=" + str(sdk),
                "-cp",
                os.pathsep.join(str(sdk / "lib" / j) for j in ("sedona.jar", "sedonac.jar")),
                "sedonac.Main",
                *args,
            ],
            cwd=sdk,
        )

    for name in (
        "sys",
        "inet",
        "sox",
        "web",
        "pstore",
        "datetime",
        "datetimeStd",
        "basicSchedule",
        "func",
        "types",
        "math",
        "logic",
        "timing",
        "hvac",
        "serial",
    ):
        compile(sdk / "src/kits" / name)
    compile(sdk / "platforms/src/generic/unix")
    manifest = sdk / "build/generic-64.xml"
    manifest.write_text(
        (sdk / "platforms/src/generic/unix/generic-unix.xml")
        .read_text()
        .replace('refSize="4"', 'refSize="8"')
    )
    stage = sdk / "build/bms-unix-64"
    compile(manifest, "-outDir", stage)

    # The datagram ABI is packed by Sedona, not by the host C compiler. These
    # offsets follow FieldLayout's declared-field order for an eight-byte pointer.
    udp = stage / "inet_UdpSocket_std.c"
    text = udp.read_text()
    placeholder = '    printf("UdpSocket unsupported pointer size\\n");'
    if text.count(placeholder) != 2:
        raise SystemExit("Unexpected UDP source; ABI patch was not applied.")
    names = ("addr", "port", "buf", "off", "len", "scope", "flow")
    offsets = (0, 8, 12, 20, 24, 28, 32)
    for direction in ("get", "set"):
        lines = []
        for name, offset in zip(names, offsets, strict=True):
            kind = "Ref" if name in ("addr", "buf") else "Int"
            call = f"{direction}{kind}(sedona, {offset}"
            lines.append(
                f"    c->{name} = {call});" if direction == "get" else f"    {call}, c->{name});"
            )
        text = text.replace(placeholder, "\n".join(lines), 1)
    udp.write_text(text)
    sockets = stage / "inet_util_std.c"
    sockets.write_text(sockets.read_text().replace("INADDR_ANY", "htonl(INADDR_LOOPBACK)"))
    vm = stage / "vm.c"
    # The original LoadNull shares a 32-bit integer write with LoadI0. On a
    # 64-bit stack cell that leaves stale pointer bits and corrupts tree cleanup.
    original = "Case LoadNull:"
    if vm.read_text().count(original) != 1:
        raise SystemExit("Unexpected VM source; null-pointer patch was not applied.")
    vm.write_text(
        vm.read_text().replace(original, "Case LoadNull: (++sp)->aval = NULL; ++cp; EndInstr;")
    )
    args = [
        "clang",
        "-std=gnu99",
        "-O2",
        "-D__UNIX__=1",
        "-DSOCKET_FAMILY_INET=1",
        '-DPLAT_BUILD_VERSION="1.2.29-bms64"',
        "-I" + str(stage),
    ]
    if platform.system() == "Darwin":
        (stage / "endian.h").write_text("#include <machine/endian.h>\n")
        args += ["-D__DARWIN__=1"]
    elif platform.system() != "Linux":
        raise SystemExit("The simulation port currently supports macOS and Linux only.")
    run(args + sorted(stage.glob("*.c")) + ["-o", sdk / "bin/svm-bms64"])
    image = sdk / "build/test-bms64.xml"
    image.write_text((sdk / "scode/platUnix.xml").read_text().replace('refSize="4"', 'refSize="8"'))
    compile(image)
    shutil.copyfile(sdk / "LICENSE.md", ROOT / "third_party/Sedona-LICENSE.md")
    print("Built compiler, standard kits, and loopback-only SVM:", sdk / "bin/svm-bms64")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=ROOT.parent / "Reference_Sources/sedona")
    parser.add_argument(
        "--java-home", type=Path, required=True, help="Existing JDK 17 home directory"
    )
    options = parser.parse_args()
    setup(options.sdk.resolve(), options.java_home.resolve())
