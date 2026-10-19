#!/usr/bin/env python3
"""tests/test_security.py - regression tests for the input-handling fixes.

Every case here is a confirmed attack that was fixed. They stay as tests so the exact
break cannot come back silently.

Run: python tests/test_security.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []
TESTS: list = []


def case(name: str):
    def deco(fn):
        def wrapper():
            try:
                fn()
                print(f"[PASS] {name}")
            except AssertionError as exc:
                FAILURES.append(f"{name}: {exc}")
                print(f"[FAIL] {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                FAILURES.append(f"{name}: unexpected {type(exc).__name__}: {exc}")
                print(f"[FAIL] {name}: unexpected {type(exc).__name__}: {exc}")
        TESTS.append(wrapper)
        return wrapper
    return deco


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ICON_GEN = _load(ROOT / "domains" / "icon-logo" / "scripts" / "icon_gen.py", "icon_gen")
MERMAID = _load(ROOT / "domains" / "docs-diagram" / "scripts" / "parse_mermaid.py", "parse_mermaid")

from backends.svg import render as svg_render  # noqa: E402
from backends.drawio import mxfile_to_ir  # noqa: E402
from tools.build_gallery import json_for_script  # noqa: E402

TMP = Path(tempfile.gettempdir())


def _base_ir():
    return {
        "schema": "figsmith.ir/1.0",
        "meta": {"domain": "arch-diagram", "chart_type": "layered", "tokens": "academic"},
        "content": {"labels": {"a": "Node A"}, "legend": [], "footnote": ""},
        "topology": {"nodes": [{"id": "a", "kind": "box"}], "edges": []},
        "layout": {"canvas": {"margin": 2, "px_per_unit": 12},
                   "grid": {"columns": 1, "gap_x": 2, "gap_y": 3, "box_w": 20, "box_h": 10},
                   "nodes": {"a": {"col": 0, "row": 0}}},
        "style": {"fill": {"a": "colors.surface_band"},
                  "stroke": {"default": "colors.border", "width": "stroke.thin"},
                  "text": {"default": "fonts.role.panel_label",
                           "size": "fonts.size_pt.panel_label", "color": "colors.ink"},
                  "emphasis": []},
    }


# ---- SVG injection ----


@case("svg: label text is escaped (no raw <script>)")
def _svg_label_escape():
    ir = _base_ir()
    ir["content"]["labels"]["a"] = "</text><script>alert(1)</script>"
    svg = svg_render(ir, str(TMP / "s1.svg"), 12)
    assert "<script>alert(1)</script>" not in svg, "label markup reached the SVG raw"


@case("svg: a hex-looking style.fill cannot break out of the attribute")
def _svg_color_injection():
    ir = _base_ir()
    ir["style"]["fill"]["a"] = '#fff" onload="alert(1)'
    try:
        svg = svg_render(ir, str(TMP / "s2.svg"), 12)
    except KeyError:
        return  # rejected outright is the desired outcome
    assert 'onload="alert(1)' not in svg, "attribute injection reached the SVG"


@case("svg: negative grid coordinates are clamped to the canvas")
def _svg_negative_coords():
    ir = _base_ir()
    ir["layout"]["nodes"]["a"] = {"col": -5, "row": -3}
    svg = svg_render(ir, str(TMP / "s3.svg"), 12)
    assert 'x="-' not in svg and 'y="-' not in svg, "negative pixel coordinate emitted"


# ---- icon generator ----


@case("icon_gen: path data with a quote is rejected")
def _icon_d_injection():
    try:
        ICON_GEN.render({"name": "x", "grid": 24, "stroke": 2,
                         "strokes": [{"d": 'M4 12 H20" onload="alert(1)'}]})
    except ValueError:
        return
    raise AssertionError("icon_gen rendered a path that injects an attribute")


@case("icon_gen: tag-like path data is rejected")
def _icon_tag_injection():
    try:
        ICON_GEN.render({"name": "x", "grid": 24, "stroke": 2,
                         "strokes": [{"d": 'M4 12" /><script>alert(1)</script>'}]})
    except ValueError:
        return
    raise AssertionError("icon_gen rendered a path containing a script tag")


@case("icon_gen: legitimate path data still renders")
def _icon_happy():
    svg = ICON_GEN.render({"name": "x", "grid": 24, "stroke": 2,
                           "strokes": [{"d": "M4 12 H20 M14 6 l6 6 -6 6"}]})
    assert "<path" in svg and "M4 12 H20" in svg, "valid icon failed to render"


# ---- gallery ----


@case("gallery: '</script>' in a catalog value is escaped")
def _gallery_script_escape():
    payload = json_for_script({"name": "</script><script>alert(1)</script>"})
    assert "</script>" not in payload, "raw </script> survives serialization"
    assert json.loads(payload)["name"] == "</script><script>alert(1)</script>", \
        "escaping broke the JSON round-trip"


# ---- mermaid ----


@case("mermaid: an oversized single line is rejected fast")
def _mermaid_line_cap():
    src = "flowchart TD\n" + "a" * 50000
    t0 = time.perf_counter()
    try:
        MERMAID.parse(src)
    except MERMAID.MermaidError:
        pass
    else:
        raise AssertionError("oversized line was not rejected")
    assert time.perf_counter() - t0 < 2.0, "oversized line was not rejected quickly"


@case("mermaid: a well-formed diagram still parses")
def _mermaid_happy():
    parsed = MERMAID.parse("flowchart TD\n  a[Client] -->|HTTPS| b[API]\n  b --> c[DB]\n")
    assert parsed["type"] == "flowchart", parsed["type"]
    assert len(parsed["edges"]) == 2, parsed["edges"]


# ---- drawio ----


@case("drawio: a decompression bomb is rejected, not expanded")
def _drawio_bomb():
    import base64
    import urllib.parse
    import zlib

    body_xml = "<mxGraphModel><root><mxCell id=\"x" + ("0" * (50 * 1024 * 1024))
    body_xml += "\"/></root></mxGraphModel>"
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    blob = comp.compress(body_xml.encode()) + comp.flush()
    enc = urllib.parse.quote(base64.b64encode(blob).decode().rstrip("="), safe="")
    mx = f'<mxfile host="app"><diagram id="x" name="bomb">{enc}</diagram></mxfile>'
    try:
        mxfile_to_ir(mx)
    except ValueError:
        return
    raise AssertionError("decompression bomb was accepted")


@case("drawio: malformed compressed body raises ValueError")
def _drawio_malformed():
    mx = ('<mxfile host="app"><diagram id="x" name="bad">'
          'not-base64-not-base64-not-base64!!!</diagram></mxfile>')
    try:
        mxfile_to_ir(mx)
    except ValueError:
        return
    raise AssertionError("malformed compressed body did not raise ValueError")


@case("drawio: a valid compressed diagram still parses")
def _drawio_happy():
    import base64
    import urllib.parse
    import zlib

    xml = ('<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="a" value="A" vertex="1" parent="1">'
           '<mxGeometry x="10" y="10" width="100" height="40" as="geometry"/></mxCell>'
           '</root></mxGraphModel>')
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    blob = comp.compress(xml.encode()) + comp.flush()
    enc = urllib.parse.quote(base64.b64encode(blob).decode().rstrip("="), safe="")
    mx = f'<mxfile host="app"><diagram id="x" name="ok">{enc}</diagram></mxfile>'
    ir = mxfile_to_ir(mx)
    assert [n["id"] for n in ir["topology"]["nodes"]] == ["a"], ir["topology"]["nodes"]


if __name__ == "__main__":
    print()
    for test in TESTS:
        test()
    print(f"\n{len(TESTS) - len(FAILURES)}/{len(TESTS)} passed, {len(FAILURES)} failure(s)")
    raise SystemExit(1 if FAILURES else 0)
