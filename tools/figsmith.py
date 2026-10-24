#!/usr/bin/env python3
"""tools/figsmith.py - one entrypoint for the whole chain.

The cookbook stitches the pipeline together by hand across five commands. This tool is
the same pipeline as code, so an agent can run it unattended:

    intent -> route -> scaffold -> render -> verify

    python -m tools.figsmith route "论文里的分组柱状图"
    python -m tools.figsmith scaffold "三层架构图" -o out/arch
    python -m tools.figsmith render out/arch.ir.json -o out/arch
    python -m tools.figsmith verify out/arch.ir.json
    python -m tools.figsmith pipeline "三层架构图" -o out/arch     # all of the above

It never fabricates success: a step that cannot run (missing data, no browser) is
reported as blocked, not skipped silently. For a statistical intent, scaffold writes a
CSV header template instead of inventing numbers, and pipeline stops there.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STRUCTURE_TOKENS = "academic"


def _tokens(name: str = STRUCTURE_TOKENS):
    from core.tokens import load

    return load(name)

ROUTE_BACKEND = {
    "structure": "backends.svg",
    "statistical": "backends.mpl2svg",
    "html": "backends.html2pdf",
}


def _run(module: str, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _route(intent: str) -> dict | None:
    from tools.catalog import route

    hits = route(intent)
    return hits[0] if hits else None


# ---------- scaffolds ----------


def _scaffold_structure(chart_type: str, domain: str, tokens: str) -> dict:
    """A valid 4-stage linear pipeline: the smallest figure that exercises every
    structural feature (boxes, arrows, labels) and passes all three checks."""
    n = 4
    nodes = [{"id": f"s{i}", "kind": "box"} for i in range(n)]
    edges = [{"from": f"s{i}", "to": f"s{i + 1}", "label": f"e{i}", "kind": "arrow"}
             for i in range(n - 1)]
    labels = {f"s{i}": f"Stage {i + 1}" for i in range(n)}
    labels.update({f"e{i}": f"step {i + 1}" for i in range(n - 1)})
    return {
        "schema": "figsmith.ir/1.0",
        "meta": {
            "domain": domain, "chart_type": chart_type, "tokens": tokens,
            "title": "TODO figure title", "width_unit": 100,
        },
        "content": {"labels": labels, "legend": [], "footnote": "TODO footnote."},
        "topology": {"nodes": nodes, "edges": edges},
        "layout": {
            "canvas": {"margin": 3, "px_per_unit": 12},
            "grid": {"columns": n, "gap_x": 2.0, "gap_y": 4.0, "box_w": 16, "box_h": 12},
            "nodes": {f"s{i}": {"col": i, "row": 0} for i in range(n)},
        },
        "style": {
            "fill": {f"s{i}": "colors.surface_band" for i in range(n)},
            "stroke": {"default": "colors.border", "width": "stroke.thin"},
            "text": {"default": "fonts.role.panel_label",
                     "size": "fonts.size_pt.panel_label", "color": "colors.ink"},
            "emphasis": [],
        },
    }


def _supported_chart_types() -> set[str]:
    from backends.mpl2svg import SUPPORTED

    return set(SUPPORTED)


def _scaffold_statistical(chart_type: str, domain: str, tokens: str,
                           csv_path: Path, rows: int = 3) -> dict:
    """A series skeleton pointing at a CSV the user fills. No numbers are invented:
    `y` is empty until real data lands, which is what keeps this honest.

    `x` is empty too. An `x` with placeholders and an empty `y` fails the IR validator
    (length mismatch), which meant the honest "fill in your data" state was itself an
    invalid IR. Both arrays start empty and the validator treats that as a scaffold.
    """
    return {
        "schema": "figsmith.ir/1.0",
        "meta": {
            "domain": domain, "chart_type": chart_type, "tokens": tokens,
            "title": "TODO figure title", "width_unit": 100,
        },
        "content": {"labels": {}, "axis": {"x": "TODO x", "y": "TODO y"},
                    "legend": ["Series A"], "footnote": "TODO footnote."},
        "topology": {"nodes": [], "edges": []},
        "layout": {
            "canvas": {"margin": 4, "figsize_inches": [7.0, 4.4]},
            "grid": {"columns": 2, "gap_x": 4.0, "gap_y": 4.0, "box_w": 30, "box_h": 20},
            "nodes": {},
        },
        "style": {
            "fill": {},
            "stroke": {"default": "colors.border", "width": "stroke.thin"},
            "text": {"default": "fonts.role.axis_label",
                     "size": "fonts.size_pt.axis_label", "color": "colors.ink"},
            "emphasis": [],
        },
        "data": {
            "source": str(csv_path),
            "categories": [],
            "series": [{"name": "Series A", "kind": chart_type,
                        "x": [], "y": []}],
            "units": {"x": "TODO", "y": "TODO"},
        },
    }



def _scaffold_html(chart_type: str, domain: str) -> str:
    t = _tokens("web")
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>{chart_type}</title>
<style>
  :root {{ --ink: {t.c('colors.ink')}; --ink-2: {t.c('colors.ink_tertiary')};
           --surface: {t.c('colors.surface')}; --accent: {t.get('colors.accent')[0]}; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  .page {{ width: 1280px; height: 720px; background: var(--surface);
           font-family: "Segoe UI", "Microsoft YaHei", sans-serif; color: var(--ink);
           padding: 72px 96px; display: flex; flex-direction: column; justify-content: center; }}
  .kicker {{ font-size: 16px; letter-spacing: .16em; text-transform: uppercase;
             color: var(--accent); font-weight: 600; margin-bottom: 16px; }}
  h1 {{ font-size: 52px; line-height: 1.12; margin: 0 0 20px; }}
  p {{ font-size: 20px; color: var(--ink-2); line-height: 1.5; margin: 0; }}
</style></head>
<body>
  <div class="page">
    <div class="kicker">{domain}</div>
    <h1>TODO 标题</h1>
    <p>TODO 副标题。这是 {chart_type} 的起点：改文字、换 token，再导出。</p>
  </div>
</body></html>
"""


def cmd_route(args: argparse.Namespace) -> int:
    hit = _route(args.intent)
    if not hit:
        print("no match; broaden the intent or name a domain")
        return 1
    print(f"domain:     {hit['domain']}")
    print(f"chart_type: {hit['id']}  ({hit.get('name', '')})")
    print(f"route:      {hit.get('route', '?')}")
    print(f"backend:    {ROUTE_BACKEND.get(hit.get('route'), '?')}")
    return 0


def cmd_scaffold(args: argparse.Namespace) -> int:
    hit = _route(args.intent)
    if not hit:
        print("no match for intent; pass --domain/--chart-type or broaden it")
        return 1
    domain, chart_type = hit["domain"], hit["id"]
    route = hit.get("route", "structure")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if route == "statistical" and chart_type not in _supported_chart_types():
        # Failing loudly beats handing over a scaffold that dies at render time: the
        # catalog lists chart types the statistical backend has not implemented yet.
        from backends.mpl2svg import SUPPORTED

        print(f"blocked: chart_type {chart_type!r} ({domain}) is listed as statistical but "
              f"mpl2svg does not implement it.")
        print(f"  implemented: {', '.join(sorted(SUPPORTED))}")
        print("  render it by hand through matplotlib, or pick an implemented type.")
        return 2

    if route == "html":
        target = out.with_suffix(".html")
        target.write_text(_scaffold_html(chart_type, domain), encoding="utf-8")
    elif route == "statistical":
        csv_path = out.with_name(out.name + "-data.csv")
        csv_path.write_text(
            "category,Series A\n" + "\n".join(f"c{i + 1}," for i in range(3)) + "\n",
            encoding="utf-8")
        target = out.with_suffix(".ir.json")
        target.write_text(
            json.dumps(_scaffold_statistical(chart_type, domain, STRUCTURE_TOKENS, csv_path),
                       indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        target = out.with_suffix(".ir.json")
        target.write_text(
            json.dumps(_scaffold_structure(chart_type, domain, STRUCTURE_TOKENS),
                       indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"scaffolded {domain}/{chart_type} (route={route}) -> {target}")
    if route == "statistical":
        # Point at the CSV, not at the IR: the IR already references it, and the CSV is
        # the file that has to be filled in.
        print(f"  fill in real data at {csv_path}, then render")
    return 0


def _detect_route(ir_path: Path) -> str:
    try:
        ir = json.loads(ir_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return "structure"
    if ir.get("data", {}).get("series"):
        return "statistical"
    return "structure"


def cmd_render(args: argparse.Namespace) -> int:
    src = Path(args.source)
    out = Path(args.out) if args.out else src.with_suffix("")
    out.parent.mkdir(parents=True, exist_ok=True)

    if src.suffix == ".html":
        from backends.html2pdf import render as html_to_pdf_render

        size_w, _, size_h = args.size.partition("x")
        try:
            result = html_to_pdf_render(
                src.read_text(encoding="utf-8"),
                out.with_suffix(".pdf"),
                int(size_w) if size_w.isdigit() else 1280,
                int(size_h) if size_h.isdigit() else 720,
                out.with_suffix(".png"),
                source_path=src,
            )
            print(f"wrote {result['pdf']} and {result['png']}")
            return 0
        except RuntimeError as exc:
            print(f"html route failed: {exc}")
            return 1
    else:
        route = _detect_route(src)
        if route == "statistical":
            code, log = _run("backends.mpl2svg", str(src),
                             "-o", str(out.with_suffix(".svg")), "--png", str(out.with_suffix(".png")))
        else:
            code, log = _run("backends.svg", str(src), "-o", str(out.with_suffix(".svg")),
                             "--scale", args.scale)
            if code == 0:
                code, log = _run("backends.png", str(out.with_suffix(".svg")),
                                 "-o", str(out.with_suffix(".png")), "--width", args.width)
    print(log.strip().splitlines()[-1] if log.strip() else "")
    return code


def _png_for(src: Path) -> Path:
    """The PNG that `render` writes for this source.

    `render` strips the source suffix and writes `<stem>.png`, but `.ir.json` has two
    suffixes, so `src.with_suffix(".png")` produced `arch.ir.png` and the verify step
    silently found nothing - skipping the contrast and tiling checks while still
    printing PASS. The renderer is the single source of truth for the artifact name.
    """
    name = src.name
    for suffix in (".ir.json", ".json", ".html", ".svg"):
        if name.endswith(suffix):
            return src.with_name(name[: -len(suffix)] + ".png")
    return src.with_suffix(".png")


def cmd_verify(args: argparse.Namespace) -> int:
    src = Path(args.source)
    failures = 0
    if src.name.endswith(".ir.json") or src.suffix == ".json":
        rc, log = _run("core.ir", str(src))
        print(f"  ir           {'ok' if rc == 0 else 'FAIL'}")
        failures += rc != 0
        rc, _ = _run("core.verify.check_overflow", str(src))
        print(f"  overflow     {'ok' if rc == 0 else 'FAIL'}")
        failures += rc != 0

    png = _png_for(src)
    if png.exists():
        for mod, label in (("core.verify.check_contrast", "contrast"),
                           ("core.verify.check_tiling", "tiling")):
            rc, _ = _run(mod, str(png))
            print(f"  {label:<12} {'ok' if rc == 0 else 'FAIL'}")
            failures += rc != 0
    else:
        # A missing artifact is a failure, not a skip: reporting PASS while two of the
        # three checks never ran is exactly the "fabricated PASS" the project forbids.
        print(f"  raster       MISSING ({png.name}); run `render` first")
        failures += 1

    # Visual acceptance is never asserted by this script; it is dispatched separately.
    print("  visual       PENDING (dispatch core.verify.judge; no fabricated PASS)")
    print("PASS (scripted checks only)" if failures == 0 else f"{failures} check(s) failed")
    return 0 if failures == 0 else 1


def cmd_pipeline(args: argparse.Namespace) -> int:
    print(f"intent: {args.intent}")
    if cmd_route(argparse.Namespace(intent=args.intent)) != 0:
        return 1
    ns = argparse.Namespace(intent=args.intent, out=args.out)
    if cmd_scaffold(ns) != 0:
        return 1
    out = Path(args.out)
    if out.with_suffix(".html").exists():
        src = out.with_suffix(".html")
    else:
        src = out.with_suffix(".ir.json")

    hit = _route(args.intent)
    if hit and hit.get("route") == "statistical":
        print("blocked: statistical scaffold needs real data before it can render "
              "(no numbers are invented). Fill data.source, then run render + verify.")
        return 2

    print("render:")
    if cmd_render(argparse.Namespace(source=src, out=args.out, scale="12",
                                     width="1600", size="1280x720")) != 0:
        return 1
    print("verify:")
    return cmd_verify(argparse.Namespace(source=src))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="FigSmith end-to-end pipeline.")
    sub = ap.add_subparsers(dest="command", required=True)

    r = sub.add_parser("route", help="resolve an intent to domain/chart/route")
    r.add_argument("intent")

    s = sub.add_parser("scaffold", help="write a route-appropriate starter")
    s.add_argument("intent")
    s.add_argument("-o", "--out", required=True)

    d = sub.add_parser("render", help="render a scaffolded source")
    d.add_argument("source")
    d.add_argument("-o", "--out", default=None)
    d.add_argument("--scale", default="12")
    d.add_argument("--width", default="1600")
    d.add_argument("--size", default="1280x720")

    v = sub.add_parser("verify", help="run the checks on a source + its PNG")
    v.add_argument("source")

    p = sub.add_parser("pipeline", help="route -> scaffold -> render -> verify")
    p.add_argument("intent")
    p.add_argument("-o", "--out", required=True)

    args = ap.parse_args(argv)
    return {
        "route": cmd_route, "scaffold": cmd_scaffold, "render": cmd_render,
        "verify": cmd_verify, "pipeline": cmd_pipeline,
    }[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
