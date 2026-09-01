"""Run eval checklist against demo points (no LLM, no Amap)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline.pipeline import run_pipeline


async def main():
    checklist_path = ROOT / "data" / "eval" / "eval_checklist.yaml"
    checklist = yaml.safe_load(checklist_path.read_text(encoding="utf-8"))

    print("=" * 60)
    print("奶茶店选址 MVP — 固定点评测清单")
    print("=" * 60)

    for point in checklist["points"]:
        demo_id = point["id"]
        print("\n>> {} ({})".format(point["name"], demo_id))
        result = await run_pipeline({"demo_id": demo_id})
        score = result["score"]
        report_text = " ".join(
            ch["content"] for ch in result["report"]["chapters"].values()
        )

        print("  score: {} -> {}".format(score["total_score"], score["recommendation"]))
        print("  financial unchecked: {}".format("yes" if score.get("financial_unchecked_notice") else "no"))
        print("  veto: {}".format(score.get("veto_reasons") or "none"))
        print("  期望检查:")
        for exp in point["expectations"]:
            ok = _check_expectation(exp, score, report_text, result)
            mark = "OK" if ok else "?"
            print("    [{}] {}".format(mark, exp))

    print("\n完成。标记 ? 的项需人工对照 evidence 与地图。")


def _check_expectation(exp: str, score: dict, text: str, result: dict) -> bool:
    if "财务未核" in exp:
        return bool(score.get("financial_unchecked_notice"))
    if "谨慎选址" in exp and "最高" in exp:
        return score["recommendation"] == "谨慎选址"
    if "不推荐" in exp and "需求" in exp:
        return score["recommendation"] == "不推荐"
    if "过密" in exp:
        return score["subscores"]["competition"]["tea_300m"] >= 9 and "过密" in text
    if "核心商圈" in exp and "不得" in exp:
        return "核心商圈" not in text
    if "300m 茶饮" in exp:
        return str(score["subscores"]["competition"]["tea_300m"]) in text
    return True


if __name__ == "__main__":
    asyncio.run(main())
