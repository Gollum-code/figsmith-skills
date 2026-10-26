#!/usr/bin/env python3
"""tests/test_regressions.py - guards for the defects fixed in the audit pass.

Each case reproduces a bug that shipped: a verifier that skipped checks, a rasterizer
that dropped every box, a parser that lost data, a layout that ignored the catalog.

Run: python tests/test_regressions.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="figsmith_regress_"))
FAILURES: list[str] = []
SKIPPED: list[str] = []
TESTS: list = []


class Skip(Exception):
    """Raised when a case cannot run in this install (e.g. a domain is not installed)."""


def case(name: str):
    def deco(fn):
        def wrapper():
            try:
                fn()
                print(f"[PASS] {name}")
            except Skip as exc:
                SKIPPED.append(f"{name}: {exc}")
                print(f"[SKIP] {name}: {exc}")
            except AssertionError as exc:
                FAILURES.append(f"{name}: {exc}")
                print(f"[FAIL] {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                FAILURES.append(f"{name}: unexpected {type(exc).__name__}: {exc}")
                print(f"[FAIL] {name}: unexpected {type(exc).__name__}: {exc}")
        TESTS.append(wrapper)
        return wrapper
    return deco


def _docs_diagram():
    """Import the domain parser, or skip when only core is installed.

    A core-only install has no `domains/`, so these cases cannot run there. Skipping is
    honest; failing would make `python tests/test_regressions.py` red on a valid install.
    """
    from importlib import import_module

    try:
        return import_module("domains.docs-diagram.scripts.parse_mermaid")
    except ModuleNotFoundError as exc:
        raise Skip(f"docs-diagram domain not installed ({exc.name})") from exc


def _base_ir(**over) -> dict:
    ir = {
        "schema": "figsmith.ir/1.0",
        "meta": {"domain": "arch-diagram", "chart_type": "pipeline",
                 "tokens": "academic", "width_unit": 60},
        "content": {"labels": {"a": "Source", "b": "Sink"}},
        "topology": {"nodes": [{"id": "a", "kind": "box"}, {"id": "b", "kind": "box"}],
                     "edges": [{"from": "a", "to": "b", "kind": "arrow"}]},
        "layout": {"canvas": {"margin": 4, "px_per_unit": 8},
                   "grid": {"columns": 1, "gap_x": 3.0, "gap_y": 4.0,
                            "box_w": 40, "box_h": 8},
                   "nodes": {}},
        "style": {"fill": {}, "stroke": {"default": "colors.border",
                                        "width": "stroke.thin"},
                  "text": {"default": "fonts.role.panel_label",
                           "size": "fonts.size_pt.panel_label",
                           "color": "colors.ink"},
                  "emphasis": []},
    }
    ir.update(over)
    return ir


# ---------------------------------------------------------------- verify plumbing


@case("verify: the raster path matches what render writes")
def _png_for():
    from tools.figsmith import _png_for

    assert _png_for(Path("out/arch.ir.json")) == Path("out/arch.png"), _png_for(Path("x.ir.json"))
    assert _png_for(Path("out/slide.html")) == Path("out/slide.png")
    assert _png_for(Path("out/fig.json")) == Path("out/fig.png")


# ---------------------------------------------------------------- renderers


@case("png: the Pillow fallback draws rectangles (width/height, not w/h)")
def _pillow_rects():
    from backends import png as P
    from PIL import Image

    saved = P.find_browser
    P.find_browser = lambda: None  # force the fallback
    try:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="120" '
            'viewBox="0 0 200 120">'
            '<rect x="0" y="0" width="200" height="120" fill="#FFFFFF"/>'
            '<rect x="20" y="20" width="80" height="40" fill="#111111"/>'
            '</svg>'
        )
        src = TMP / "rect.svg"
        src.write_text(svg, encoding="utf-8")
        out = TMP / "rect.png"
        P.svg_to_png(src, out)
        img = Image.open(out).convert("L")
        assert img.getpixel((60, 40)) < 60, f"box was not filled: {img.getpixel((60, 40))}"
    finally:
        P.find_browser = saved


@case("svg: root size wins over a rectangle, and units are honoured")
def _svg_size():
    from backends.svg import parse_svg_size

    matplotlib_like = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="400pt" height="200pt" '
        'viewBox="0 0 400 200"><rect width="10" height="10" x="0" y="0"/></svg>'
    )
    assert parse_svg_size(matplotlib_like) == (400.0, 200.0, "pt")
    unitless = '<svg width="1200.00" height="300.00" viewBox="0 0 1200 300"></svg>'
    assert parse_svg_size(unitless) == (1200.0, 300.0, "px")
    missing = '<svg viewBox="0 0 640 480"></svg>'
    assert parse_svg_size(missing) == (640.0, 480.0, "px")


@case("svg: a back edge in the ambiguous case still gets an arrow head")
def _arrow_head():
    from backends.svg import Node, _arrow
    from core.tokens import load

    tokens = load("academic")
    src = Node("a", "box", 10, 10, 100, 40)
    dst = Node("b", "box", 50, 10, 100, 40)  # overlapping columns, same row
    out = _arrow(src, dst, "#333333", 1.2, tokens, {}, {"from": "a", "to": "b"}, 12.0)
    assert "<path" in out, f"connector has no head: {out}"


# ---------------------------------------------------------------- verifier


@case("overflow: a wrapped long word is not reported as overflow")
def _overflow_long_word():
    from core.verify.check_overflow import check

    ir = _base_ir()
    ir["content"]["labels"]["a"] = "supercalifragilisticexpialidocious_identifier"
    ir["topology"]["nodes"] = [{"id": "a", "kind": "box"}]
    ir["topology"]["edges"] = []
    ir["layout"]["grid"]["box_w"] = 10
    result = check(ir)
    kinds = [i["kind"] for i in result["issues"]]
    assert "text_overflow" not in kinds, f"false overflow: {result['issues']}"


@case("contrast: a sparse but readable figure passes")
def _contrast_sparse():
    from PIL import Image, ImageDraw

    from core.verify.check_contrast import check

    img = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(img).text((40, 40), "Body text that is readable", fill=(20, 20, 20))
    p = TMP / "sparse.png"
    img.save(p)
    assert check(p)["passed"], check(p)["reason"]


@case("contrast: a hairline that rasterizes below the floor fails")
def _contrast_hairline():
    from PIL import Image, ImageDraw

    from core.verify.check_contrast import check

    img = Image.new("RGB", (600, 400), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 560, 360], fill=(243, 243, 243))
    d.text((40, 60), "Some body text here", fill=(20, 20, 20))
    p = TMP / "hairline.png"
    img.save(p)
    result = check(p)
    assert not result["passed"], f"invisible structure passed: {result}"


@case("probe: a dark-background figure still yields bands and columns")
def _probe_dark():
    import numpy as np

    from core.probe.probe_geometry import measure

    gray = np.full((200, 300), 0.12)
    gray[40:60, 40:260] = 0.75
    gray[120:140, 40:260] = 0.9
    report = measure(gray)
    assert report["band_count"] == 2, report["band_count"]
    assert 0.05 < report["ink_coverage"] < 0.4, report["ink_coverage"]


# ---------------------------------------------------------------- layout


@case("layout: layout_spec picks the strategy")
def _layout_spec():
    from backends.svg import auto_layout

    def nodes(n=4):
        return [{"id": f"s{i}", "kind": "box"} for i in range(n)]

    linear = _base_ir(meta={**_base_ir()["meta"], "layout_spec": "row-n-equal"})
    linear["topology"]["nodes"] = nodes()
    lay = auto_layout(linear)
    assert [lay[f"s{i}"]["row"] for i in range(4)] == [0, 0, 0, 0], lay

    stack = _base_ir(meta={**_base_ir()["meta"], "layout_spec": "stacked-bands"})
    stack["topology"]["nodes"] = nodes()
    lay = auto_layout(stack)
    assert [lay[f"s{i}"]["row"] for i in range(4)] == [0, 1, 2, 3], lay

    grid = _base_ir(meta={**_base_ir()["meta"], "layout_spec": "split-mid"})
    grid["topology"]["nodes"] = nodes()
    lay = auto_layout(grid)
    assert lay["s2"]["row"] == 1 and lay["s2"]["col"] == 0, lay


# ---------------------------------------------------------------- parsers


@case("mermaid: a leading comment does not hide the header")
def _mermaid_comment():
    parsed = _docs_diagram().parse("%% generated\nflowchart TD\n  a --> b\n")
    assert parsed["type"] == "flowchart", parsed["type"]


@case("mermaid: participant aliases survive into the IR")
def _mermaid_alias():
    m = _docs_diagram()
    parsed = m.parse("sequenceDiagram\n  participant C as Web Client\n  C->>S: hi\n")
    ir = m.to_ir(parsed)
    assert ir["content"]["labels"]["C"] == "Web Client", ir["content"]["labels"]


@case("mermaid: subgraph bands record their members")
def _mermaid_subgraph():
    m = _docs_diagram()
    source = "flowchart TD\n  subgraph Backend\n    a[API]\n    b[Worker]\n  end\n  c --> a\n"
    ir = m.to_ir(m.parse(source))
    bands = [n for n in ir["topology"]["nodes"] if n["kind"] == "band"]
    assert bands and set(bands[0]["members"]) == {"a", "b"}, bands


@case("drawio: exported ids are XML-escaped")
def _drawio_escape():
    import xml.etree.ElementTree as ET

    from backends.drawio import ir_to_mxfile

    ir = _base_ir()
    ir["topology"]["nodes"][0]["id"] = 'x" injected="1'
    ir["topology"]["edges"][0]["from"] = 'x" injected="1'
    out = ir_to_mxfile(ir)
    ET.fromstring(out)  # must stay well-formed
    assert 'injected="1"' not in out, "attribute injection survived escaping"


@case("data: inlined numbers next to a declared source are rejected")
def _data_freeze():
    from core.ir import Report, validate

    ir = _base_ir()
    ir["topology"] = {"nodes": [], "edges": []}
    ir["content"]["labels"] = {}
    ir["data"] = {
        "source": "data.csv",
        "series": [{"name": "A", "x": [0, 1], "y": [1, 2]}],
        "units": {"x": "u", "y": "u"},
    }
    rep = Report()
    validate(ir, rep)
    assert any("inlines x/y" in e for e in rep.errors), rep.errors


if __name__ == "__main__":
    print()
    for test in TESTS:
        test()
    passed = len(TESTS) - len(FAILURES) - len(SKIPPED)
    print(f"\n{passed}/{len(TESTS)} passed, {len(SKIPPED)} skipped, "
          f"{len(FAILURES)} failure(s)")
    raise SystemExit(1 if FAILURES else 0)
