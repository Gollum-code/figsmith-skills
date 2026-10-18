#!/usr/bin/env python3
"""tools/regress.py - the blessed-figure regression suite.

P6's completion definition is "blessed all PASS, regression re-runnable". A blessed
figure is one that a human judge accepted; re-running must reproduce it and must not
regress any check.

Each case under tests/blessed/ declares:
    <id>/ir.json        the IR
    <id>/expected.png   the accepted raster (or "accept" placeholder on first run)

The suite runs, for each case:
    1. IR validates
    2. render -> SVG -> PNG
    3. check_contrast / check_tiling / check_overflow all PASS
    4. if an expected PNG exists, compare ink coverage against the current render
       (a big swing means the renderer changed behaviour, which is the regression)

Usage:
    python tools/regress.py            # run everything
    python tools/regress.py --blessed  # (re)record current output as the new expected
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLESSED = ROOT / "tests" / "blessed"
sys.path.insert(0, str(ROOT))


def _run(module: str, *args: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", module, *args],
                          capture_output=True, text=True, cwd=str(ROOT))
    return proc.returncode, (proc.stdout + proc.stderr)


def _ink_ratio(png: Path) -> float:
    from PIL import Image

    img = Image.open(png).convert("L")
    data = list(img.getdata())
    if not data:
        return 0.0
    return sum(1 for v in data if v < 240) / len(data)


def run_case(case_dir: Path, outdir: Path, bless: bool = False) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    ir_path = case_dir / "ir.json"
    result: dict = {"case": case_dir.name, "steps": {}, "passed": True}

    if not ir_path.exists():
        result["steps"]["ir"] = "missing ir.json"
        result["passed"] = False
        return result

    # 1. validate
    code, out = _run("core.ir", str(ir_path))
    result["steps"]["validate"] = "ok" if code == 0 else out.strip()[:300]
    if code != 0:
        result["passed"] = False

    svg = outdir / "figure.svg"
    png = outdir / "figure.png"

    # Route decides the backend. A statistical figure must go through matplotlib (its
    # content is a data layer, not a topology), so rendering it with the SVG writer would
    # silently produce an empty canvas - which is exactly what this suite is for.
    scale = 12.0
    chart_type = ""
    try:
        ir = json.loads(ir_path.read_text(encoding="utf-8-sig"))
        scale = float(ir.get("layout", {}).get("canvas", {}).get("px_per_unit", 12.0))
        chart_type = ir.get("meta", {}).get("chart_type", "")
        has_data = bool(ir.get("data", {}).get("series"))
    except Exception:  # noqa: BLE001
        has_data = False

    if has_data:
        code, out = _run("backends.mpl2svg", str(ir_path), "-o", str(svg), "--png", str(png))
        result["steps"]["render"] = f"mpl2svg ({chart_type})" if code == 0 else out.strip()[:300]
        if code != 0:
            result["steps"]["render_mpl"] = out.strip()[:300]
            result["passed"] = False
            return result
    else:
        code, out = _run("backends.svg", str(ir_path), "-o", str(svg), "--scale", str(scale))
        result["steps"]["render_svg"] = "ok" if code == 0 else out.strip()[:300]
        if code != 0:
            result["passed"] = False
            return result

        code, out = _run("backends.png", str(svg), "-o", str(png), "--width", "1200")
        result["steps"]["render_png"] = "ok" if code == 0 else out.strip()[:300]
        if code != 0:
            result["passed"] = False
            return result

    # 3. checks
    for module in ("core.verify.check_contrast", "core.verify.check_tiling"):
        code, out = _run(module, str(png))
        result["steps"][module.split(".")[-1]] = "ok" if code == 0 else out.strip()[:300]
        if code != 0:
            result["passed"] = False
    code, out = _run("core.verify.check_overflow", str(ir_path))
    result["steps"]["check_overflow"] = "ok" if code == 0 else out.strip()[:300]
    if code != 0:
        result["passed"] = False

    # 4. blessed comparison
    expected = case_dir / "expected.png"
    if bless:
        import shutil

        shutil.copyfile(png, expected)
        result["steps"]["blessed"] = "recorded"
    elif expected.exists():
        a, b = _ink_ratio(expected), _ink_ratio(png)
        drift = abs(a - b)
        result["steps"]["blessed_drift"] = round(drift, 4)
        if drift > 0.02:
            result["passed"] = False
            result["steps"]["blessed"] = f"drift {drift:.3f} > 0.02"
        else:
            result["steps"]["blessed"] = "ok"
    else:
        result["steps"]["blessed"] = "no baseline yet (run --blessed)"

    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Blessed-figure regression suite.")
    ap.add_argument("--blessed", action="store_true", help="record current output as baseline")
    ap.add_argument("--case", default=None, help="run only this case")
    args = ap.parse_args(argv)

    if not BLESSED.exists():
        print("no tests/blessed directory; nothing to run")
        return 0

    cases = sorted(p for p in BLESSED.iterdir() if p.is_dir())
    if args.case:
        cases = [c for c in cases if c.name == args.case]
    if not cases:
        print("no cases found")
        return 0

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        for case in cases:
            result = run_case(case, Path(tmp) / case.name, args.blessed)
            mark = "PASS" if result["passed"] else "FAIL"
            print(f"[{mark}] {result['case']}")
            for step, status in result["steps"].items():
                flag = "" if status == "ok" or step == "blessed_drift" else "  <- "
                print(f"    {step:16} {status}{flag}")
            if not result["passed"]:
                failures += 1

    print(f"\n{len(cases) - failures}/{len(cases)} cases pass")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
