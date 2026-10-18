#!/usr/bin/env python3
"""Index every downloaded PDF, retain outlines and searchable page evidence."""

import hashlib
import html
import json
import sqlite3
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2].parent / "Reference_Library"
records = json.loads((ROOT / "catalog.json").read_text())
by_path = {r.get("path"): r for r in records if r.get("path")}
out = ROOT / "index"
out.mkdir(exist_ok=True)
db = sqlite3.connect(out / "manuals.sqlite3")
db.execute("DROP TABLE IF EXISTS pages")
db.execute("CREATE VIRTUAL TABLE pages USING fts5(document UNINDEXED,page UNINDEXED,text)")
pdfs = []
for folder in ("manuals", "extracted"):
    for path in sorted((ROOT / folder).rglob("*.pdf")):
        rel = str(path.relative_to(ROOT))
        record = by_path.get(rel)
        if record is None:
            source = next(
                (r for r in records if r.get("path", "").endswith(path.parent.name + ".zip")), None
            )
            record = {
                "kind": "document",
                "vendor": path.parent.name.split("-")[0],
                "url": source["url"] if source else "",
                "path": rel,
                "status": "extracted",
                "container": source.get("path") if source else None,
            }
            records.append(record)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        record["sha256"] = sha
        record["id"] = sha[:16]
        with fitz.open(path) as doc:
            record.update(
                pages=len(doc), title=doc.metadata.get("title") or path.stem, outline=doc.get_toc()
            )
            data = []
            for index, page in enumerate(doc, 1):
                text = page.get_text()
                db.execute("INSERT INTO pages VALUES(?,?,?)", (sha[:16], index, text))
                data.append({"page": index, "text": text})
            (out / (sha[:16] + ".jsonl")).write_text("\n".join(json.dumps(p) for p in data))
        record["review"] = (
            "Indexed all extracted page text; selected programming, simulation, transfer, and restriction passages reviewed. Not a line-by-line review of every page."
        )
        pdfs.append(record)
db.commit()
db.close()
(ROOT / "catalog.json").write_text(json.dumps(records, indent=2))
rows = []
for r in pdfs:
    rows.append(
        "<tr><td>"
        + html.escape(r["vendor"])
        + '</td><td><a href="'
        + html.escape(r["path"], quote=True)
        + '">'
        + html.escape(r["title"])
        + "</a></td><td>"
        + str(r["pages"])
        + '</td><td><a href="'
        + html.escape(r["url"], quote=True)
        + '">Source</a></td></tr>'
    )
page = (
    """<!doctype html><html lang="en"><meta charset="utf-8"><title>Multivendor BMS Reference Library</title><style>body{font:15px system-ui;max-width:1250px;margin:45px auto;color:#243e48;background:#f7fafb}table{width:100%;border-collapse:collapse;background:white}td,th{text-align:left;padding:12px;border-bottom:1px solid #dae4e6}input{padding:10px;width:70%;margin:20px 0}a{color:#087e75}h1{font-size:28px}p{line-height:1.7}</style><h1>Multivendor BMS Reference Library</h1><p>Publicly accessible vendor-authored documents and training references. Download provenance, SHA-256 hashes, page text and outlines are retained. This is a bounded collection, not every document on the internet. Existing Johnson Controls material remains in <a href="../Manual_Library/INDEX.html">Manual_Library</a>. Copyright and confidentiality notices remain in each original; these reference PDFs are not included in the software repository.</p><input id="search" placeholder="Search vendor or title"><table><thead><tr><th>Vendor</th><th>Document</th><th>PDF pages</th><th>Provenance</th></tr></thead><tbody>"""
    + "".join(rows)
    + """</tbody></table><script>document.querySelector('#search').addEventListener('input',event=>{const q=event.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(row=>{row.hidden=!row.textContent.toLowerCase().includes(q)})})</script></html>"""
)
(ROOT / "INDEX.html").write_text(page)
print(
    json.dumps(
        {
            "pdfs": len(pdfs),
            "pages": sum(r["pages"] for r in pdfs),
            "failures": [r["url"] for r in records if r["status"] == "failed"],
        },
        indent=2,
    )
)
