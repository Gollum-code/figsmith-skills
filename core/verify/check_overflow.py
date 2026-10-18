#!/usr/bin/env python3
"""check_overflow.py - overflow / overlap / text width budget.

Three independent checks, all pure geometry, no vision needed:

  1. TEXT WIDTH BUDGET (METHOD 2.1)
     CJK chars * 1.0 * size + latin chars * 0.55 * size, and the end of the string
     must sit >= 10px from the container edge. Overflow -> wrap, never shrink.

  2. ELEMENT OVERFLOW
     Every element box must stay inside the canvas minus the margin.

  3. ELEMENT OVERLAP
     No two boxes may overlap, unless one is a `band` (bands are allowed to sit
     under boxes) or the pair is declared in `allow_overlap`.

Input: an IR JSON (see core/IR.md) that has been through layout resolution, i.e. every
node carries an explicit {x, y, w, h} in layout.nodes.

Usage:
    python -m core.verify.check_overflow <ir.json> [...] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.tokens import load as load_tokens  # noqa: E402
from backends.svg import resolve_layout  # noqa: E402

EDGE_CLEARANCE_PX = 10.0
CJK_RANGES = (
    (0x2E80, 0x9FFF),
    (0xAC00, 0xD7A3),
    (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F),
    (0xFF00, 0xFFEF),
    (0x20000, 0x2FA1F),
)


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in CJK_RANGES)


def text_width_px(text: str, size_px: float, tokens=None) -> float:
    """Width budget: real font metrics when available, CJK*1.0 + latin*0.55 otherwise."""
    if tokens is not None:
        return tokens.text_width(text, size_px)
    cjk = sum(1 for ch in text if is_cjk(ch))
    latin = len(text) - cjk
    return cjk * 1.0 * size_px + latin * 0.55 * size_px


def _wrap_lines(text: str, size_px: float, box_w: float, tokens) -> list[str]:
    """Mirror the renderer's wrapping so the check measures what will ship."""
    limit = max(box_w - 2 * EDGE_CLEARANCE_PX, size_px)
    segments = [s.strip() for s in text.split("\n") if s.strip()] if "\n" in text else [text.strip()]
    lines: list[str] = []
    for segment in segments:
        if tokens.text_width(segment, size_px) <= limit:
            lines.append(segment)
            continue
        cur = ""
        for word in segment.split(" "):
            candidate = f"{cur} {word}".strip()
            if tokens.text_width(candidate, size_px) <= limit or not cur:
                cur = candidate
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines or [text]


def _bbox(node) -> tuple[float, float, float, float]:
    return (node.x, node.y, node.right, node.bottom)


_bbox_of = _bbox


def _overlap(a, b) -> float:
    """Overlap area; 0 when disjoint. Touching edges count as 0 (that's adjacency)."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    return ix * iy


def check(ir: dict, scale: float | None = None) -> dict:
    issues: list[dict] = []
    meta = ir.get("meta", {})
    tokens = load_tokens(meta.get("tokens", "academic"))

    # Resolve through the same layout engine the renderer uses. Checking a different
    # layout than the one rendered is how "checks pass, figure is broken" happens.
    if scale is None:
        scale = float(ir.get("layout", {}).get("canvas", {}).get("px_per_unit", 8.0))
    nodes, info = resolve_layout(ir, scale)
    canvas_w, canvas_h = info["canvas_w"], info["canvas_h"]
    margin = info["margin"]

    layout_nodes = {n.id: n for n in nodes}
    labels = ir.get("content", {}).get("labels", {})
    style_text = ir.get("style", {}).get("text", {})
    size_path = style_text.get("size", "fonts.size_pt.panel_label")
    size_pt = tokens.s(size_path, 10.0)
    # Same pt->px conversion the renderer uses, via the same layout info. Two different
    # conversions is exactly how "check passes, figure overflows" happens.
    size_px = size_pt * info["effective_dpi"] / 72.0
    size_px = min(size_px, info["box_px"][1] * 0.42)

    topo_nodes = {n["id"]: n for n in ir.get("topology", {}).get("nodes", [])}

    # ---- 1 + 2. text budget and canvas containment ----
    for nid, node in layout_nodes.items():
        x0, y0, x1, y1 = node.x, node.y, node.right, node.bottom

        if x0 < margin - 0.01 or y0 < margin - 0.01 or x1 > canvas_w - margin + 0.01 or y1 > canvas_h - margin + 0.01:
            issues.append({
                "kind": "canvas_overflow", "node": nid,
                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                "detail": f"box escapes margin {margin:.1f} in canvas {canvas_w:.0f}x{canvas_h:.0f}",
            })

        text = labels.get(nid)
        if text:
            # Judge the wrapped form, not the raw string: the renderer wraps, so the
            # binding constraint is the widest *line*, and vertical fit.
            lines = _wrap_lines(text, size_px, node.w, tokens)
            widest = max((text_width_px(line, size_px, tokens) for line in lines), default=0.0)
            line_h = size_px * tokens.get("fonts.line_height_ratio", 1.35)
            needed_h = line_h * len(lines)
            if widest + 2 * EDGE_CLEARANCE_PX > node.w:
                issues.append({
                    "kind": "text_overflow", "node": nid, "text": text,
                    "widest_line_px": round(widest, 1), "box_width_px": round(node.w, 1),
                    "detail": (f"widest line {widest:.0f}px + {2 * EDGE_CLEARANCE_PX:.0f}px clearance "
                               f"> box {node.w:.0f}px; add an explicit break or widen the box"),
                })
            elif needed_h + 2 * EDGE_CLEARANCE_PX > node.h:
                issues.append({
                    "kind": "text_overflow", "node": nid, "text": text,
                    "lines": len(lines), "needed_height_px": round(needed_h, 1),
                    "box_height_px": round(node.h, 1),
                    "detail": (f"{len(lines)} wrapped lines need {needed_h:.0f}px "
                               f"> box height {node.h:.0f}px; increase box_h"),
                })

    # ---- 3. overlap ----
    allow = set(map(tuple, ir.get("layout", {}).get("allow_overlap", [])))
    ids = list(layout_nodes)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a_id, b_id = ids[i], ids[j]
            a, b = layout_nodes[a_id], layout_nodes[b_id]
            if topo_nodes.get(a_id, {}).get("kind") == "band" or topo_nodes.get(b_id, {}).get("kind") == "band":
                continue
            pair = tuple(sorted((a_id, b_id)))
            if pair in allow:
                continue
            area = _overlap(_bbox_of(a), _bbox_of(b))
            if area > 0.01:
                issues.append({
                    "kind": "overlap", "nodes": [a_id, b_id],
                    "overlap_px2": round(area, 1),
                    "detail": f"{a_id} and {b_id} overlap by {area:.0f}px^2",
                })

    return {
        "file": None,
        "issues": issues,
        "passed": not issues,
        "checked_nodes": len(layout_nodes),
        "font_size_pt": size_pt,
        "canvas": [round(canvas_w, 1), round(canvas_h, 1)],
    }


def check_file(path: str | Path) -> dict:
    p = Path(path)
    try:
        ir = json.loads(p.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"file": str(p), "issues": [{"kind": "io", "detail": "file not found"}], "passed": False}
    except json.JSONDecodeError as exc:
        return {"file": str(p), "issues": [{"kind": "io", "detail": f"invalid JSON: {exc}"}], "passed": False}
    result = check(ir)
    result["file"] = str(p)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Overflow / overlap / text-budget checker.")
    ap.add_argument("irs", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = [check_file(p) for p in args.irs]
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for r in results:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"[{mark}] {r['file']}  ({r.get('checked_nodes', 0)} nodes)")
            for issue in r["issues"]:
                print(f"  - {issue['kind']}: {issue.get('detail', '')}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
