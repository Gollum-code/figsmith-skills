#!/usr/bin/env python3
"""core/verify/judge.py - the visual-judge dispatch protocol, as a runner.

`judge_template.md` defines *how to ask* the vision model and *how to collect* the
answer. This module implements that protocol so the acceptance loop has a real
executable step instead of a prose instruction:

    checks pass -> build dispatch (this file) -> vision model answers -> collect verdict

The rule the whole design hangs on: **never fabricate PASS.** If no verdict is
supplied, the result is PENDING, not PASS. An agent that "cannot see" the image
must say so; this file makes that the default outcome.

Usage:
    # Build the dispatch (this is what the host agent feeds to its vision tool)
    python -m core.verify.judge build figure.png --ir fig.ir.json \
        --domain paper-figure --chart-type bar_grouped \
        --intent "论文里的分组柱状图" > dispatch.md

    # Collect a verdict. --verdict-file takes the JSON the model replied with;
    # omit it and the status is PENDING (no fabricated PASS).
    python -m core.verify.judge collect figure.png --verdict-file reply.json

    # Print the dispatch protocol itself (what the model must obey)
    python -m core.verify.judge protocol
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.tokens import load as load_tokens  # noqa: E402

PROTOCOL_PATH = Path(__file__).with_name("judge_template.md")
# Resolved from this file, not from the working directory: the tool has to find the same
# acceptance criteria no matter where the agent ran it from.
DOMAINS_DIR = Path(__file__).resolve().parents[2] / "domains"
RESULTS_DIR = Path("verify-results")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_ir(ir_path: Path | None) -> dict:
    if not ir_path:
        return {}
    try:
        return json.loads(ir_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _element_manifest(ir: dict) -> list[str]:
    """Declare what the renderer claims to have drawn, so the judge can check it.

    The manifest is generated from the IR, not from the PNG: it states intent, the
    judge's job is to confirm the pixels agree.
    """
    items: list[str] = []
    labels = ir.get("content", {}).get("labels", {})
    nodes = ir.get("topology", {}).get("nodes", [])
    edges = ir.get("topology", {}).get("edges", [])

    for node in nodes:
        nid, kind = node.get("id", "?"), node.get("kind", "box")
        text = labels.get(nid, "")
        items.append(f"{kind}「{nid}」文本：{text or '（空）'}")
    for i, edge in enumerate(edges):
        text = labels.get(edge.get("label", ""), "")
        src, dst = edge.get("from", "?"), edge.get("to", "?")
        suffix = f"，标签：{text}" if text else ""
        items.append(f"连线 {i}：{src} → {dst}{suffix}")
    if not items:
        items.append("（IR 中无节点与连线）")
    return items


def build_dispatch(image: Path, ir_path: Path | None, domain: str, chart_type: str,
                   tokens_name: str, intent: str, reference: Path | None,
                   whitelist: list[str]) -> str:
    """Assemble the exact dispatch block from judge_template.md section 2."""
    ir = _read_ir(ir_path)
    if not tokens_name:
        tokens_name = ir.get("meta", {}).get("tokens", "academic")
    if not chart_type:
        chart_type = ir.get("meta", {}).get("chart_type", "unknown")

    manifest = "\n".join(f"{i}. {t}" for i, t in enumerate(_element_manifest(ir), 1))
    accept = _domain_acceptance(domain)

    return f"""你是 FigSmith 视觉裁判。请只依据你看到的像素作答，不推测、不脑补。

## 交付物
- 文件：{image.resolve()}
- 域：{domain} / 图型：{chart_type} / token 集：{tokens_name}

## 参照物
- 参考图：{reference.resolve() if reference else '无'}
- 意图说明：{intent or '（未提供）'}

## 元素清单（生成侧声明，供你核对是否齐全）
{manifest}

## 本域验收标准
{accept}

## 已知偏差白名单
{chr(10).join('- ' + w for w in whitelist) if whitelist else '- （无）'}

## 你的输出（严格 JSON，不要 markdown 代码块以外的任何文字）
{{
  "verdict": "PASS" | "FAIL",
  "issues": [
    {{
      "severity": "major | minor",
      "what": "缺陷描述",
      "where": "图中位置（左上/中部/第三列第二个框...）",
      "evidence": "你实际看到的像素级证据（颜色、偏移量、缺失元素）"
    }}
  ]
}}"""


def _domain_acceptance(domain: str) -> str:
    """Pull the acceptance criteria verbatim from the domain's SKILL.md."""
    skill = DOMAINS_DIR / domain / "SKILL.md"
    if not skill.exists():
        return f"（未找到 {skill}，请按默认标准：图元齐全、文字可读、对齐一致）"
    text = skill.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if "验收" in ln and ln.lstrip().startswith(("#", "##")):
            start = i
            break
    if start is None:
        return f"（{skill} 中未找到验收小节）"
    out: list[str] = []
    for ln in lines[start:]:
        if ln.startswith("## ") and out and ln is not lines[start]:
            break
        out.append(ln)
    return "\n".join(out).strip()


def collect_verdict(image: Path, verdict_file: Path | None) -> dict:
    """Turn a model reply into a result record. Absent reply => PENDING, never PASS."""
    result = {
        "image": str(image),
        "judged_at": _now(),
        "status": "PENDING",
        "verdict": None,
        "issues": [],
        "note": "",
    }
    if not verdict_file or not verdict_file.exists():
        result["note"] = "未提供裁判回复：视觉验收待完成，禁止填 PASS。"
        return result

    try:
        reply = json.loads(verdict_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        result["note"] = f"裁判回复不是合法 JSON（{exc}）：按 PENDING 处理，禁止填 PASS。"
        return result
    if not isinstance(reply, dict):
        result["note"] = f"裁判回复不是 JSON 对象：按 PENDING 处理，禁止填 PASS。"
        return result

    verdict = str(reply.get("verdict", "")).upper()
    raw_issues = reply.get("issues")
    if raw_issues is None:
        issues: list = []
    elif isinstance(raw_issues, list):
        issues = raw_issues
    else:
        # A malformed `issues` is a malformed reply, not a crash: the whole point of
        # this function is that a bad verdict degrades to PENDING, never to an exception
        # the caller has to handle.
        result["note"] = (f"裁判回复的 issues 不是数组（得到 "
                          f"{type(raw_issues).__name__}）：按 PENDING 处理，禁止填 PASS。")
        return result

    for issue in issues:
        if not isinstance(issue, dict):
            result["note"] = "裁判回复的 issues 含非对象条目：按 PENDING 处理，禁止填 PASS。"
            return result
    result["issues"] = issues

    if verdict not in ("PASS", "FAIL"):
        result["note"] = f"裁判回复缺少合法 verdict（得到 {verdict!r}）：按 PENDING 处理。"
        return result

    has_major = any(str(i.get("severity", "")).lower() == "major" for i in issues)
    if verdict == "PASS" and has_major:
        # The model contradicted itself; judge_template.md section 3 rules major => FAIL.
        result["status"] = "FAIL"
        result["note"] = "裁判填 PASS 但列有 major issue，按协议改判 FAIL。"
    else:
        result["status"] = verdict
    result["verdict"] = verdict
    return result


def _print_protocol() -> int:
    if not PROTOCOL_PATH.exists():
        print("judge_template.md is missing", file=sys.stderr)
        return 1
    print(PROTOCOL_PATH.read_text(encoding="utf-8-sig"))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Visual-judge dispatch and collection.")
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="emit the dispatch block for the vision model")
    b.add_argument("image")
    b.add_argument("--ir", default=None)
    b.add_argument("--domain", required=True)
    b.add_argument("--chart-type", default="")
    b.add_argument("--tokens", default="")
    b.add_argument("--intent", default="")
    b.add_argument("--reference", default=None)
    b.add_argument("--whitelist", action="append", default=[])

    c = sub.add_parser("collect", help="collect a verdict reply")
    c.add_argument("image")
    c.add_argument("--verdict-file", default=None)
    c.add_argument("--out", default=None, help="append the result record here (JSONL)")

    sub.add_parser("protocol", help="print the dispatch protocol")

    args = ap.parse_args(argv)

    if args.command == "protocol":
        return _print_protocol()

    if args.command == "build":
        print(build_dispatch(
            Path(args.image), Path(args.ir) if args.ir else None,
            args.domain, args.chart_type, args.tokens, args.intent,
            Path(args.reference) if args.reference else None, args.whitelist,
        ))
        return 0

    record = collect_verdict(Path(args.image),
                             Path(args.verdict_file) if args.verdict_file else None)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"status: {record['status']}")
    if record["note"]:
        print(f"note:   {record['note']}")
    for issue in record["issues"]:
        print(f"  [{issue.get('severity', '?')}] {issue.get('where', '?')}: "
              f"{issue.get('what', '')} ({issue.get('evidence', '')})")
    return 0 if record["status"] in ("PASS", "PENDING") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
