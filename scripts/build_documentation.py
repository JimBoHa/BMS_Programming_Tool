"""Create an offline HTML documentation archive from public, tracked sources."""

import argparse
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
STYLE = "body{font:16px/1.6 system-ui,sans-serif;max-width:1080px;margin:40px auto;padding:0 24px;color:#183633}a{color:#007e78}img{max-width:100%;border:1px solid #ccd8d6}pre{overflow:auto;background:#eff5f4;padding:16px}table{border-collapse:collapse}th,td{border:1px solid #ccd8d6;padding:8px;text-align:left}"


def build(output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = (
        subprocess.check_output(
            [
                "git",
                "ls-files",
                "-z",
                "--",
                "docs",
                "README.md",
                "LICENSE",
                "NOTICE",
                "third_party",
            ],
            cwd=ROOT,
        )
        .decode()
        .split("\0")
    )
    renderer = MarkdownIt("commonmark", {"html": False}).enable("table")
    with tempfile.TemporaryDirectory(prefix="bms-docs-") as temporary:
        temporary = Path(temporary)
        for name in paths:
            if not name:
                continue
            source = ROOT / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("Documentation inputs must be tracked regular files.")
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            if source.suffix != ".md":
                continue
            html = renderer.render(source.read_text())
            html = re.sub(
                r'href="(?!https?:)([^"#]+)\.md(#[^"]*)?"',
                lambda m: 'href="' + m[1] + ".html" + (m[2] or "") + '"',
                html,
            )
            target.with_suffix(".html").write_text(
                '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>BMS Studio documentation</title><style>'
                + STYLE
                + "</style>"
                + html
            )
        (temporary / "START-HERE.html").write_text(
            '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=docs/getting-started.html"><a href="docs/getting-started.html">BMS Studio getting started</a>'
        )
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(temporary.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(temporary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    build(parser.parse_args().output)
