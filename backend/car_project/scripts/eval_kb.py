# coding: utf-8
"""车主客服问答离线评估：路由准确率 / Hit@1 / 拒答正确率 / 引用合规 / 延迟。

为什么默认只跑「检索 + 判定」不跑生成：
    生成的质量主要取决于检索与 prompt 约束，而检索是确定性最强的环节。
    默认模式不调 LLM、不烧额度、秒级跑完，适合日常回归；需要评估
    生成质量时再加 ``--judge``（对每条用例真实调用 answer）。

用法（在 car_project/ 目录下）：
    .venv/Scripts/python.exe -m scripts.eval_kb                # 检索模式
    .venv/Scripts/python.exe -m scripts.eval_kb --judge        # 含生成判定
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from service import kbService

#: car_project/ 目录（与 kbService.BASE_DIR 一致），向上两级到项目根找 docs/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
GOLD_PATH = _PROJECT_ROOT / "docs" / "kb" / "eval" / "gold.jsonl"
REPORT_PATH = Path(__file__).resolve().parent.parent / "instance" / "kb_eval_report.json"


def load_cases() -> list[dict[str, Any]]:
    """加载评测集。

    Returns:
        用例列表；文件缺失时抛 FileNotFoundError（评测集是硬依赖）。
    """
    return [
        json.loads(line)
        for line in GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _pct(values: list[int]) -> float:
    """通过率：round(x / n * 100, 1)。"""
    return round(sum(values) / len(values) * 100, 1) if values else 0.0


def run(judge: bool) -> dict[str, Any]:
    """执行评估。

    Args:
        judge: True 时每条用例真实调用 answer（含 LLM 生成），评估拒答与引用合规。

    Returns:
        指标字典，同时写入 instance/kb_eval_report.json。
    """
    cases = load_cases()
    routed_ok: list[int] = []       # 路由是否命中期望域（无期望域的用例不计数）
    hit1: list[int] = []            # 检索 top1 是否命中 gold
    refuse_ok: list[int] = []       # 拒答判定是否正确
    citation_ok: list[int] = []     # 回答是否带引用（judge 模式）
    latencies: list[float] = []     # 检索延迟（毫秒）
    misses: list[dict[str, Any]] = []  # 未命中明细，报告里逐条可查

    for case in cases:
        question = case["question"]
        gold_ids = case.get("gold", [])
        expect_domain = case.get("expect_domain")
        should_refuse = bool(case.get("should_refuse"))

        domain, _ = kbService.route_domain(question)
        if expect_domain is not None:
            routed_ok.append(int(domain == expect_domain))

        t0 = time.perf_counter()
        hits = kbService.search(question, domain=domain, top_k=3)
        latencies.append((time.perf_counter() - t0) * 1000)

        top_ids = [h["kb_id"] for h in hits]
        if gold_ids:
            hit1.append(int(bool(top_ids) and top_ids[0] in gold_ids))

        if judge:
            out = kbService.answer(question)
            if should_refuse:
                refuse_ok.append(int(out["refused"]))
            else:
                refuse_ok.append(int(not out["refused"]))
                citation_ok.append(int(not out["citation_missing"]))

        if gold_ids and (not top_ids or top_ids[0] not in gold_ids):
            misses.append(
                {"id": case["id"], "question": question, "expect": gold_ids, "got": top_ids}
            )

    lat_sorted = sorted(latencies)
    report = {
        "total": len(cases),
        "mode": "judge" if judge else "retrieval",
        "domain_acc": _pct(routed_ok),
        "domain_n": len(routed_ok),
        "hit_at_1": _pct(hit1),
        "hit_n": len(hit1),
        "refuse_acc": _pct(refuse_ok) if refuse_ok else None,
        "citation_acc": _pct(citation_ok) if citation_ok else None,
        "latency_ms_p50": round(statistics.median(latencies), 1),
        "latency_ms_p95": round(lat_sorted[int(len(lat_sorted) * 0.95) - 1], 1),
        "misses": misses,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="车主客服问答离线评估")
    parser.add_argument("--judge", action="store_true", help="含 LLM 生成判定（消耗额度）")
    args = parser.parse_args()

    report = run(judge=args.judge)
    print(f"评测 {report['total']} 条（{report['mode']} 模式）")
    print(f"  路由准确率   {report['domain_acc']}%  (n={report['domain_n']})")
    print(f"  Hit@1        {report['hit_at_1']}%  (n={report['hit_n']})")
    if report["refuse_acc"] is not None:
        print(f"  拒答正确率   {report['refuse_acc']}%")
        print(f"  引用合规率   {report['citation_acc']}%")
    print(f"  检索延迟     P50 {report['latency_ms_p50']} ms / P95 {report['latency_ms_p95']} ms")
    if report["misses"]:
        print("  未命中明细：")
        for m in report["misses"]:
            print(f"    ✗ {m['id']} {m['question']} 期望 {m['expect']} 实得 {m['got']}")
    print(f"报告已写入 {REPORT_PATH}")


if __name__ == "__main__":
    main()
