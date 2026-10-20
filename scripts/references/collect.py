#!/usr/bin/env python3
"""Download public reference documents; retain provenance and retrieval failures."""

import concurrent.futures
import hashlib
import html
import json
import re
import subprocess
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[2].parent / "Reference_Library"
SEEDS = [
    ("Contemporary Controls", "https://ctrlink.com/basautomation/sae.htm"),
    ("Sedona Alliance", "https://sedona-alliance.org/technology.htm"),
    ("Sedona Alliance", "https://sedona-alliance.org/pdf/SedonaApplicationEditor.pdf"),
    (
        "Honeywell",
        "https://prod-edam.honeywell.com/content/dam/honeywell-edam/hbt/en-us/documents/manuals-and-guides/reference-guides/31-00237.pdf",
    ),
    ("PLCopen", "https://www.plcopen.org/system/files/downloads/tc6_xml_v201_xsd.pdf"),
    ("ALC", "https://eikonforeducators.automatedlogic.com/downloads.html"),
    ("Tridium", "https://downloads.onesight.solutions/Tridium/Niagara%204%20Documents/"),
    (
        "Tridium",
        "https://downloads.onesight.solutions/Tridium/Niagara%204%20Documentation/docKitControl/docKitControl.pdf",
    ),
    (
        "Tridium",
        "https://www.tridium.com/content/dam/tridium/en/documents/document-lists/niagara/NiagaraFramework-FeaturesOverview-4.12.pdf",
    ),
    (
        "Honeywell",
        "https://prod-edam.honeywell.com/content/dam/honeywell-edam/hbt/en-us/documents/manuals-and-guides/user-manuals/31-00089.pdf",
    ),
    (
        "Honeywell",
        "https://prod-edam.honeywell.com/content/dam/honeywell-edam/hbt/en-us/documents/manuals-and-guides/user-manuals/62-0381.pdf",
    ),
    (
        "Honeywell",
        "https://prod-edam.honeywell.com/content/dam/honeywell-edam/hbt/en-us/documents/manuals-and-guides/installation-guides/31-00121.pdf",
    ),
    (
        "Honeywell",
        "https://www.cochranesupply.com/media/assets/product/documents/Honeywell/SPyder5%20Engineering%20Tool.pdf",
    ),
    (
        "Tridium",
        "https://downloads.onesight.solutions/iSMA/Niagara%20Software/IC%20Workbench/Manuals/docN4Install.pdf",
    ),
    (
        "Tridium",
        "https://downloads.onesight.solutions/iSMA/Niagara%20Software/IC%20Workbench/Manuals/Getting_started_with_Niagara_Framework.pdf",
    ),
    (
        "Honeywell",
        "https://prod-edam.honeywell.com/content/dam/honeywell-edam/hbt/en-us/documents/manuals-and-guides/user-manuals/hbt-bms-Spyder-Model-5-VAV-Controller-User-Guide-31-00282ES.pdf",
    ),
    (
        "Honeywell",
        "https://buildings.honeywell.com/content/dam/hbtbt/en/documents/downloads/Sylk%20Actuator%20Analytics%20Service%20User%20Guide%20-%2031-00420.pdf",
    ),
    ("Temco", "https://temcocontrols.com/ftp/software/10SoftwareManual.zip"),
]


def retrieve(url):
    r = subprocess.run(
        [
            "curl",
            "-fLsS",
            "--retry",
            "1",
            "--connect-timeout",
            "12",
            "--max-time",
            "120",
            "--max-filesize",
            "500000000",
            url,
        ],
        capture_output=True,
    )
    if r.returncode:
        raise RuntimeError(r.stderr.decode(errors="replace")[-400:])
    return r.stdout


def main():
    (ROOT / "manuals").mkdir(parents=True, exist_ok=True)
    (ROOT / "research").mkdir(parents=True, exist_ok=True)
    records = {}
    extracted = []
    if (ROOT / "catalog.json").exists():
        all_records = json.loads((ROOT / "catalog.json").read_text())
        extracted = [r for r in all_records if r.get("status") == "extracted"]
        records = {r["url"]: r for r in all_records if r.get("status") != "extracted"}
    queue, seen, downloads = deque((v, u, 0) for v, u in SEEDS), set(), {}
    while queue:
        vendor, url, depth = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        if re.search(r"\.(pdf|zip|chm)(?:\?|$)", url, re.I):
            downloads[url] = vendor
            continue
        try:
            body = retrieve(url).decode(errors="replace")
            (
                ROOT / "research" / (hashlib.sha256(url.encode()).hexdigest()[:12] + ".html")
            ).write_text(body)
            records[url] = {"vendor": vendor, "url": url, "kind": "index", "status": "retrieved"}
            for link in re.findall(r"href=[\"\']([^\"\']+)", body, re.I):
                absolute = urljoin(url, html.unescape(link)).split("#")[0]
                if urlparse(absolute).scheme == "http" and re.search(
                    r"\.(pdf|zip|chm)(?:\?|$)", absolute, re.I
                ):
                    absolute = "https:" + absolute[5:]
                if urlparse(absolute).scheme != "https":
                    continue
                if re.search(r"\.(pdf|zip|chm)(?:\?|$)", absolute, re.I):
                    if vendor != "Tridium" or re.search(r"\.pdf(?:\?|$)", absolute, re.I):
                        downloads[absolute] = vendor
                elif (
                    depth < 2
                    and urlparse(absolute).netloc == "eikonforeducators.automatedlogic.com"
                ):
                    queue.append((vendor, absolute, depth + 1))
        except Exception as e:
            records[url] = {
                "vendor": vendor,
                "url": url,
                "kind": "index",
                "status": "failed",
                "error": str(e),
            }

    def download(item):
        url, vendor = item
        old = records.get(url)
        if old and old.get("path") and (ROOT / old["path"]).exists():
            return old
        record = {"vendor": vendor, "url": url, "kind": "document", "retrieved": "2026-10-18"}
        try:
            body = retrieve(url)
            ext = (
                "pdf"
                if body.startswith(b"%PDF-")
                else "zip"
                if body.startswith(b"PK")
                else "chm"
                if body.startswith(b"ITSF")
                else None
            )
            if not ext:
                raise ValueError("Response is not a PDF, ZIP, or CHM document")
            name = re.sub(r"[^a-zA-Z0-9._-]+", "-", unquote(urlparse(url).path.rsplit("/", 1)[-1]))[
                :130
            ]
            if not name.lower().endswith("." + ext):
                name += "." + ext
            path = Path("manuals") / (
                vendor + "-" + hashlib.sha256(url.encode()).hexdigest()[:8] + "-" + name
            )
            (ROOT / path).write_bytes(body)
            record.update(
                status="downloaded",
                path=str(path),
                bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
            )
        except Exception as e:
            record.update(status="failed", error=str(e))
        return record

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for record in pool.map(download, downloads.items()):
            records[record["url"]] = record
            (ROOT / "catalog.json").write_text(
                json.dumps(list(records.values()) + extracted, indent=2)
            )
            print(record["vendor"], record["status"], record.get("path", record["url"]), flush=True)
    print("Total sources:", len(records), "documents:", len(downloads), flush=True)


if __name__ == "__main__":
    main()
