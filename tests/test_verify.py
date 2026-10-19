#!/usr/bin/env python3
"""tests/test_verify.py - the verifier must not lie.

These are the tests that matter most: a verifier that reports PASS on a broken figure
is worse than no verifier at all, because the acceptance loop trusts it.

Run: python tests/test_verify.py    (or: pytest tests/ -q)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.tokens import load as load_tokens  # noqa: E402
from core.verify.check_contrast import check as contrast_check  # noqa: E402
from core.verify.check_tiling import check as tiling_check  # noqa: E402
from core.verify.judge import collect_verdict  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

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
        wrapper.__name__ = fn.__name__
        TESTS.append(wrapper)
        return wrapper
    return deco


# ---------- contrast ----------


@case("contrast: low-contrast fixture must FAIL")
def _contrast_fails():
    result = contrast_check(str(FIXTURES / "fig_lowcontrast.png"), 40.0)
    assert not result["passed"], f"verifier passed a low-contrast figure: {result['reason']}"


@case("contrast: clean fixture must PASS")
def _contrast_passes():
    result = contrast_check(str(FIXTURES / "fig_good.png"), 40.0)
    assert result["passed"], f"verifier rejected a clean figure: {result['reason']}"


# ---------- tiling ----------


@case("tiling: repeated-band fixture must FAIL")
def _tiling_fails():
    result = tiling_check(str(FIXTURES / "fig_tiled.png"), 0.92)
    assert not result["passed"], f"verifier passed a tiled figure: {result['reason']}"


@case("tiling: clean fixture must PASS")
def _tiling_passes():
    result = tiling_check(str(FIXTURES / "fig_good.png"), 0.92)
    assert result["passed"], f"verifier rejected a clean figure: {result['reason']}"


# ---------- judge: the no-fabrication contract ----------


@case("judge: no reply => PENDING, never PASS")
def _judge_pending():
    record = collect_verdict(FIXTURES / "fig_good.png", None)
    assert record["status"] == "PENDING", record
    assert record["verdict"] is None


@case("judge: malformed reply => PENDING, never PASS")
def _judge_malformed(tmp: Path = Path("verify-results")):
    bad = tmp / "junk.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not json", encoding="utf-8")
    record = collect_verdict(FIXTURES / "fig_good.png", bad)
    assert record["status"] == "PENDING", record
    assert record["verdict"] is None


@case("judge: PASS with a major issue => re-judged FAIL")
def _judge_contradiction(tmp: Path = Path("verify-results")):
    reply = tmp / "contradiction.json"
    reply.parent.mkdir(parents=True, exist_ok=True)
    reply.write_text(
        '{"verdict":"PASS","issues":[{"severity":"major","what":"missing box",'
        '"where":"row 2","evidence":"no rect"}]}', encoding="utf-8")
    record = collect_verdict(FIXTURES / "fig_good.png", reply)
    assert record["status"] == "FAIL", record


@case("judge: honest PASS => PASS")
def _judge_pass(tmp: Path = Path("verify-results")):
    reply = tmp / "pass.json"
    reply.parent.mkdir(parents=True, exist_ok=True)
    reply.write_text('{"verdict":"PASS","issues":[]}', encoding="utf-8")
    record = collect_verdict(FIXTURES / "fig_good.png", reply)
    assert record["status"] == "PASS", record


# ---------- tokens ----------


@case("tokens: every renderable set resolves its required paths")
def _tokens_resolve():
    from core.tokens.loader import check

    for name in ("academic", "web", "tech"):
        problems, _warnings = check(name)
        assert not problems, f"{name}: {problems}"


@case("tokens: unknown set raises instead of silently falling back")
def _tokens_unknown():
    try:
        load_tokens("does-not-exist")
    except ValueError:
        return
    raise AssertionError("load() accepted an unknown token set")


@case("tokens: sequential ramp returns the requested number of stops")
def _tokens_ramp():
    t = load_tokens("academic")
    stops = t.sequential(4)
    assert len(stops) == 4, stops
    assert all(s.startswith("#") for s in stops), stops


@case("tokens: hex path returns a real hex")
def _tokens_hex():
    t = load_tokens("academic")
    assert t.c("colors.ink").startswith("#"), t.c("colors.ink")


# ---------- router ----------


@case("router: 'banner' does not match the 'er' keyword")
def _router_boundary():
    from tools.catalog import route

    hits = route("社媒 banner")
    assert hits, "no route for '社媒 banner'"
    assert hits[0]["id"] != "er", f"'banner' matched the 'er' keyword: {hits[0]['id']}"
    assert hits[0]["route"] == "html", f"expected the html route, got {hits[0]['route']}"


@case("router: domain priority keeps paper-figure first on ties")
def _router_priority():
    from tools.catalog import route

    hits = route("分层架构图")
    assert hits and hits[0]["domain"] == "paper-figure", hits


if __name__ == "__main__":
    print()
    for test in TESTS:
        test()
    print(f"\n{len(TESTS) - len(FAILURES)}/{len(TESTS)} passed, {len(FAILURES)} failure(s)")
    raise SystemExit(1 if FAILURES else 0)
