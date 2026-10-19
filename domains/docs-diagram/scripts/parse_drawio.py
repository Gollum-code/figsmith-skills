#!/usr/bin/env python3
"""parse_drawio.py - draw.io (.drawio / mxfile) -> FigSmith IR.

Thin wrapper over backends.drawio.mxfile_to_ir (which performs the actual XML parsing,
including compressed diagrams). Kept as a separate CLI entrypoint so the docs-diagram
domain has a single, documented command for both source formats:

    python -m domains.docs-diagram.scripts.parse_drawio input.drawio -o out.ir.json
    python -m domains.docs-diagram.scripts.parse_mermaid input.mmd   -o out.ir.json

The parser never invents style: drawio's own colors/shapes are dropped and FigSmith's
token set is re-applied by the renderer. Only topology, labels and geometry survive the
round-trip, which is the whole point of the interoperability route (METHOD 4).
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backends.drawio import mxfile_to_ir  # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Parse a draw.io file into a FigSmith IR.")
    ap.add_argument("source")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--tokens", default="academic")
    args = ap.parse_args(argv)

    src = Path(args.source)
    text = src.read_text(encoding="utf-8-sig")
    try:
        ir = mxfile_to_ir(text, args.tokens)
    except (ValueError, ET.ParseError) as exc:
        print(f"parse failed: {exc}", file=sys.stderr)
        return 1

    out = args.out or str(src.with_suffix(".ir.json"))
    Path(out).write_text(json.dumps(ir, indent=2, ensure_ascii=False), encoding="utf-8")
    n_nodes = len(ir.get("topology", {}).get("nodes", []))
    n_edges = len(ir.get("topology", {}).get("edges", []))
    print(f"parsed drawio '{ir.get('meta', {}).get('source_file', src.stem)}': "
          f"{n_nodes} nodes, {n_edges} edges -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
