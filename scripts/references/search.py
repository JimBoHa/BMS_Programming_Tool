#!/usr/bin/env python3
"""Search all indexed multivendor PDF pages and extracted ALC HTML help."""

import argparse
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[2].parent / "Reference_Library"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("query", help='SQLite FTS5 query, e.g. simulation or "online debugging"')
parser.add_argument("--limit", type=int, default=10)
args = parser.parse_args()
db = sqlite3.connect(root / "index/manuals.sqlite3")
catalog = {r.get("id"): r for r in json.loads((root / "catalog.json").read_text()) if r.get("id")}
for id, page, excerpt in db.execute(
    "SELECT document,page,snippet(pages,2,'[',']',' … ',42) FROM pages WHERE pages MATCH ? ORDER BY bm25(pages) LIMIT ?",
    (args.query, args.limit),
):
    record = catalog[id]
    print(f"PDF page {page}: {root / record['path']}\n{excerpt}\n")
for path, title, excerpt in db.execute(
    "SELECT path,title,snippet(html_help,2,'[',']',' … ',42) FROM html_help WHERE html_help MATCH ? ORDER BY bm25(html_help) LIMIT ?",
    (args.query, args.limit),
):
    print(f"HTML: {title}\n{root / path}\n{excerpt}\n")
