#!/usr/bin/env python3
"""Index statically extracted vendor help without executing its scripts."""

import html
import json
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2].parent / "Reference_Library"


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0
        self.in_title = False
        self.title = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "title":
            self.in_title = True
        if tag in ("p", "br", "div", "h1", "h2", "h3", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
        if self.in_title:
            self.title.append(data)


db = sqlite3.connect(ROOT / "index/manuals.sqlite3")
db.execute("DROP TABLE IF EXISTS html_help")
db.execute("CREATE VIRTUAL TABLE html_help USING fts5(path UNINDEXED,title,text)")
rows = []
for file in sorted((ROOT / "extracted/ALC-LogicBuilder-4.1-help").rglob("*.htm")):
    raw = file.read_bytes()
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        source = raw.decode("cp1252", errors="replace")
    parser = Text()
    parser.feed(source)
    text = re.sub(r"[ \t\r\f]+", " ", "".join(parser.parts))
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    title = "".join(parser.title).strip() or next(
        (x.strip() for x in text.splitlines() if len(x.strip()) > 3), file.stem
    )
    rel = str(file.relative_to(ROOT))
    db.execute("INSERT INTO html_help VALUES(?,?,?)", (rel, title, text))
    rows.append({"path": rel, "title": title, "characters": len(text)})
db.commit()
db.close()
(ROOT / "index/alc-html-help.json").write_text(json.dumps(rows, indent=2))
links = "".join(
    '<tr><td><a href="'
    + html.escape(r["path"], quote=True)
    + '">'
    + html.escape(r["title"])
    + "</a></td><td>"
    + str(r["characters"])
    + "</td></tr>"
    for r in rows
)
(ROOT / "HTML_HELP.html").write_text(
    '<!doctype html><html lang="en"><meta charset="utf-8"><title>ALC offline programming help</title><style>body{font:15px system-ui;margin:40px auto;max-width:1100px;color:#294955}td{padding:10px;border-bottom:1px solid #ddd}input{padding:12px;width:80%;margin:20px 0}a{color:#087f75}</style><h1>ALC Eikon / WebCTRL 4.1 help</h1><p>1,273 statically extracted HTML help files from the public educator installer. Search titles below or query the local SQLite full-text index. Scripts in the installer were not executed. Original copyright notices remain. This is legacy help, not evidence of current controller compatibility.</p><input id="q" placeholder="Search titles"><table>'
    + links
    + '</table><script>document.querySelector("#q").oninput=e=>document.querySelectorAll("tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase()))</script></html>'
)
print("Indexed HTML help files:", len(rows), "characters:", sum(r["characters"] for r in rows))
