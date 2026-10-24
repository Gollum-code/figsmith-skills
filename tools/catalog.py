#!/usr/bin/env python3
"""tools/catalog.py - merge per-domain catalogs into one machine-readable index,
and resolve user intent -> domain -> chart type -> template.

P5's completion definition is "intent -> domain -> chart type -> template, automated".
The router is deliberately dumb keyword matching over the catalogs: it needs to be
inspectable and predictable, not clever. A wrong route the user can see beats a smart
one they cannot.

Usage:
    python -m tools.catalog merge                 # rebuild gallery/catalog.json
    python -m tools.catalog route "论文分组柱状图"  # resolve an intent
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAINS_DIR = ROOT / "domains"
GALLERY = ROOT / "gallery"


def _hit(needle: str, text: str) -> bool:
    """Keyword match that respects word boundaries for ASCII terms.

    Plain substring matching makes short keywords match inside unrelated words: "er"
    (entity-relationship) fires on "banner", routing a banner to the ER diagram. ASCII
    keywords therefore match as whole words; CJK has no word boundaries, so those stay
    substring matches.
    """
    n = needle.lower()
    if not n:
        return False
    if n.isascii() and n.isalnum():
        return re.search(rf"\b{re.escape(n)}\b", text) is not None
    return n in text


def load_domain_catalogs() -> list[dict]:
    catalogs = []
    for path in sorted(DOMAINS_DIR.glob("*/references/catalog.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            print(f"warn: {path} is not valid JSON: {exc}", file=sys.stderr)
            continue
        data["_domain_path"] = path.relative_to(ROOT).as_posix()
        catalogs.append(data)
    return catalogs


def merge(out: Path | None = None, write: bool = True) -> dict:
    merged: dict = {
        "schema": "figsmith.catalog.index/1.0",
        "domains": [],
        "chart_types": [],
    }
    for catalog in load_domain_catalogs():
        domain = catalog.get("domain", "unknown")
        merged["domains"].append({
            "id": domain,
            "version": catalog.get("version"),
            "catalog": catalog["_domain_path"],
            "chart_count": len(catalog.get("chart_types", [])),
        })
        for entry in catalog.get("chart_types", []):
            merged["chart_types"].append({
                **entry,
                "domain": domain,
            })
    if write:
        out = out or (GALLERY / "catalog.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged


def route(intent: str, index: dict | None = None) -> list[dict]:
    """Score every chart type against the intent, best first.

    Scoring: exact id match > keyword substring hit. Ties break by domain priority
    (paper-figure first: it is the most constrained domain and the most common ask).

    This is a read-only query. It used to rebuild gallery/catalog.json on every call,
    which made `route` fail on a read-only checkout and race between parallel agents.
    The index is loaded from disk when present and merged in memory otherwise.
    """
    if index is None:
        index_path = GALLERY / "catalog.json"
        if index_path.exists():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                index = merge(write=False)
        else:
            index = merge(write=False)
    text = intent.strip().lower()
    if not text:
        return []

    domain_priority = {d: i for i, d in enumerate(
        ["paper-figure", "arch-diagram", "docs-diagram", "infographic",
         "deck-slides", "poster-flyer", "icon-logo"])}

    scored: list[tuple[int, int, dict]] = []
    for entry in index["chart_types"]:
        score = 0
        eid = entry["id"].lower()
        if eid == text or _hit(eid, text):
            score += 10
        if entry.get("name", "") and entry.get("name", "").lower() in text:
            score += 6
        for kw in entry.get("keywords", []):
            if _hit(kw, text):
                score += 3
        if score:
            scored.append((-score, domain_priority.get(entry["domain"], 99), entry))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [entry for _, _, entry in scored[:5]]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Catalog merge and intent router.")
    ap.add_argument("command", choices=["merge", "route"])
    ap.add_argument("intent", nargs="?")
    args = ap.parse_args(argv)

    if args.command == "merge":
        merged = merge()
        print(f"{len(merged['domains'])} domains, {len(merged['chart_types'])} chart types -> "
              f"{GALLERY / 'catalog.json'}")
        return 0

    if not args.intent:
        print("route requires an intent string", file=sys.stderr)
        return 2
    results = route(args.intent)
    if not results:
        print("no match; broaden the intent or pick a domain manually")
        return 1
    for entry in results:
        backend = {"structure": "backends/svg.py", "statistical": "backends/mpl2svg.py",
                   "html": "backends/html2pdf.py"}.get(entry.get("route"), "?")
        print(f"{entry['domain']:14} {entry['id']:20} route={entry.get('route', '?'):12} "
              f"backend={backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
