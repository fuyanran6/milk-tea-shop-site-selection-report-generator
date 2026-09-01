"""Report chapter generation: deep template path + optional LLM path."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.pipeline.features import NO_MAIN_RISK_LINE, format_categories, format_categories_lines
from app.pipeline.rag import retrieve
from app.pipeline.report_insights import (
    build_scenario_table,
    chapter_title,
    competition_insight,
    decision_implication,
    finance_threshold_note,
    insight_block,
    scene_demand_narrative,
)
from app.pipeline.report_state import (
    competition_pressure_phrase,
    district_poi_total_line,
    finance_rent_pressure_detail,
    poi_total_unreliable,
    rent_pressure_phrase,
    score_summary_line,
    transit_distance_summary,
    valid_walk_distance,
)

DEMO_REPORT_NOTICE = (
    "**【演示点报告】** 本报告基于内置演示数据生成，用于产品功能展示与体验，"
    "不代表对真实候选地址的分析结论。"
)

CHAPTERS = [
    ("summary", "决策摘要"),
    ("district", "商圈与场景"),
    ("demand", "消费者与需求匹配"),
    ("competition", "竞争分析"),
    ("transit", "交通与可达性"),
    ("finance", "经营可行性"),
    ("risk", "风险因素"),
    ("conclusion", "结论与建议"),
    ("map", "选址分析图"),
    ("appendix", "数据说明与来源附录"),
]

SUBSCORE_ZH = {
    "demand": "需求匹配",
    "competition": "竞争环境",
    "consumer_scene": "消费场景",
    "cost": "财务评估",
}


def _score_label(score: dict) -> str:
    return "综合决策分" if score.get("financial_checked") else "点位评分"


def _score_line(score: dict) -> str:
    label = _score_label(score)
    if score.get("financial_checked"):
        base = f"{label}：{score['total_score']}/100（点位评分 + 财务评估）"
    else:
        max_p = score.get("max_possible", 80)
        base = f"{label}：{score['total_score']}/{max_p}（未含财务评估）"
    veto = score.get("veto_reasons") or []
    if veto:
        base += f"；最终建议「{score['recommendation']}」"
        if any("租金" in v for v in veto):
            base += "（财务否决规则已生效）"
    return base


def _no_main_risks_text(features: dict, score: dict) -> str:
    unchecked: list[str] = []
    if not score.get("financial_checked"):
        unchecked.append("财务评估（月租、客单价或预估营收/杯量）")
    if features.get("rating_sample_count", 0) == 0:
        unchecked.append("竞品官方 rating")
    if not features.get("nearest_transit_distance") and not features.get("transit"):
        unchecked.append("交通可达性距离")
    if unchecked:
        return NO_MAIN_RISK_LINE + " 以下项尚未核实：" + "、".join(unchecked) + "。"
    return NO_MAIN_RISK_LINE


async def generate_report(
    features: dict[str, Any],
    score_result: dict[str, Any],
    evidence: list[dict[str, Any]],
    llm_key=None,
    basemap_note: str = "",
) -> dict[str, Any]:
    scene = features.get("scene_type", "mixed")
    rag_hits: dict[str, list[dict]] = {}
    chapters: dict[str, dict[str, Any]] = {}

    for key, title in CHAPTERS:
        rag_key = key if key != "summary" else "conclusion"
        hits = retrieve(rag_key, scene, limit=3)
        rag_hits[key] = hits

    use_llm = False  # 报告统一走模板生成，保证与证据表、计分一致

    for key, title in CHAPTERS:
        chapter_evidence = _filter_evidence(key, evidence)
        rag_docs = rag_hits.get(key, [])
        if use_llm and key not in ("map", "appendix", "summary"):
            content = await _llm_generate(
                key, title, features, score_result, chapter_evidence, rag_docs, llm_key, basemap_note
            )
        else:
            content = _template_generate(
                key, features, score_result, chapter_evidence, rag_docs, basemap_note
            )
        chapters[key] = {
            "title": title,
            "content": content,
            "evidence_ids": [e["claim_id"] for e in chapter_evidence],
            "rag_refs": [d["filename"] for d in rag_docs],
        }

    # 决策摘要始终由程序组装，保证与计分一致、原因具体
    chapters["summary"]["content"] = _build_summary(features, score_result)

    # 导航保留通用章节名；结论性副标题写入 headline，由模板/Word 置于正文开头
    for key, _ in CHAPTERS:
        if key in ("summary", "map", "appendix"):
            continue
        chapters[key]["headline"] = chapter_title(key, features, score_result)

    return {
        "chapters": chapters,
        "chapter_order": [{"key": k, "title": chapters[k]["title"]} for k, _ in CHAPTERS],
        "rag_hits": rag_hits,
        "evidence": evidence,
    }


def _collect_reasons(features: dict, score: dict) -> list[str]:
    """支撑当前建议档的核心原因（尽量点名本址特征）。"""
    reasons = []
    an = features.get("analytics") or {}
    sub = score.get("subscores", {})

    demand = sub.get("demand", {})
    d_score, d_max = demand.get("score", 0), demand.get("max", 35)
    if d_score >= d_max * 0.7:
        reasons.append(
            f"需求匹配较强（{d_score}/{d_max}）：{an.get('scene_why', features.get('scene_label', ''))}"
        )
    elif d_score >= d_max * 0.45:
        reasons.append(
            f"需求匹配中等（{d_score}/{d_max}）：500m 结构为 {an.get('categories_zh_500', '—')}"
        )
    else:
        if poi_total_unreliable(features):
            reasons.append(
                f"需求匹配偏弱（{d_score}/{d_max}）：500m 多类 POI 触顶，总量不可靠，请以下方分类结构为准"
            )
        else:
            total = an.get("poi_total_500")
            if total is None:
                reasons.append(
                    f"需求匹配偏弱（{d_score}/{d_max}）：500m 多类 POI 触顶，总量不可靠，请以下方分类结构为准"
                )
            else:
                reasons.append(
                    f"需求匹配偏弱（{d_score}/{d_max}）：500m POI 总量 {total}，购买场景支撑不足"
                )

    tea_300 = features.get("tea_count_300m", 0)
    comp = sub.get("competition", {})
    reasons.append(
        f"{competition_pressure_phrase(comp.get('score', 0), comp.get('max', 30))}："
        f"300m 茶饮 {tea_300} 家，连锁 {an.get('chain_300', 0)} 家；{an.get('density_note', '')}"
    )

    scene = sub.get("consumer_scene", {})
    transit_info = transit_distance_summary(features.get("transit", []))
    reasons.append(
        f"消费场景 {scene.get('score', 0)}/{scene.get('max', 15)}："
        f"餐饮/休闲配套见 500m 结构；{transit_info['text']}"
    )

    if score.get("financial_checked"):
        ratio = score.get("rent_ratio")
        cost = sub.get("cost", {})
        if ratio is not None:
            reasons.append(
                f"财务评估 {cost.get('score')}/{cost.get('max')}：租金/营收约 {ratio:.0%}"
            )
        else:
            reasons.append(f"财务评估已计入（{cost.get('score')}/{cost.get('max')}）")

    brand = features.get("brand_positioning")
    if brand:
        reasons.append(f"品牌定位对照：「{brand}」— 需与周边竞品价格带/客群是否同档一并现场核实")

    return reasons


def _collect_main_risks(features: dict, score: dict) -> list:
    """经营与选址层面的主要风险（不含数据缺失类提示）。"""
    risks = []
    seen = set()

    def add(text):
        if text and text not in seen:
            seen.add(text)
            risks.append(text)

    for vr in score.get("veto_reasons", []):
        add(vr)

    tea_300 = features.get("tea_count_300m", 0)
    an = features.get("analytics") or {}
    veto_text = " ".join(score.get("veto_reasons", []))
    if tea_300 >= 9 and "竞争" not in veto_text and "茶饮" not in veto_text:
        add(f"竞争过密：300m 内茶饮 {tea_300} 家（连锁 {an.get('chain_300', 0)}）")

    nearest = an.get("nearest_competitor")
    if nearest and (nearest.get("distance_m") or 999) <= 80:
        add(f"贴身竞品过近：{nearest.get('name')} 约 {nearest.get('distance_m')}m")

    sub = score.get("subscores", {})
    demand = sub.get("demand", {})
    if demand.get("score", 0) <= demand.get("max", 35) * 0.35:
        add("需求匹配偏弱：500m 商业配套不足以支撑茶饮消费场景")

    comp = sub.get("competition", {})
    if comp.get("score", 0) <= comp.get("max", 30) * 0.4 and tea_300 < 9:
        add(f"竞争压力较大：300m 茶饮 {tea_300} 家")

    if an.get("chain_ratio_300") is not None and an["chain_ratio_300"] >= 0.6 and tea_300 >= 3:
        add(f"连锁占比高（约 {an['chain_ratio_300']:.0%}），品牌虹吸与价格战风险更高")

    scene = sub.get("consumer_scene", {})
    nearest_t = features.get("nearest_transit_distance")
    if scene.get("score", 0) <= scene.get("max", 15) * 0.45:
        add("消费场景偏弱：餐饮休闲配套或交通可达性不足")
    elif nearest_t and nearest_t > 800:
        add(f"交通偏弱：最近交通直线约 {int(nearest_t)}m")

    if tea_300 == 0 and not features.get("data_source") == "demo":
        dining_300 = (features.get("categories_300m") or {}).get("dining", 0)
        capped = (features.get("category_capped") or {}).get("dining", False)
        from app.pipeline.features import format_count_display
        dining_disp = format_count_display(dining_300, capped)
        if dining_300 < 10:
            add("无茶饮竞品且餐饮配套较弱，需警惕是否为需求空白而非蓝海。")
        elif dining_300 >= 30:
            add(
                f"虽无贴身茶饮竞品，但周边餐饮配套成熟（{dining_disp}家），"
                f"需现场验证餐饮客流是否转化为饮品购买习惯。"
            )
        else:
            add("竞品较少，但购买场景需现场蹲点验证。")

    ratio = score.get("rent_ratio")
    rent_msg = rent_pressure_phrase(ratio)
    if rent_msg and (ratio is None or ratio <= 0.30):
        add(rent_msg)

    fin = features.get("finance") or {}
    if fin.get("breakeven_cups_day") and fin.get("cups_gap") is not None and fin["cups_gap"] < 0:
        add(
            f"预估日杯量低于「仅覆盖租金」粗算线："
            f"预估 {features.get('daily_cups')} 杯 vs 约需 {fin['breakeven_cups_day']} 杯"
        )

    scene_type = features.get("scene_type")
    if scene_type == "transit":
        add("交通型点位停留意愿通常偏低，外带与动线比堂食更关键（需现场确认）")
    if scene_type == "school":
        add("学校型点位存在寒暑假淡季风险（需现场确认营业日历）")

    return risks


def _collect_tips(features: dict, score: dict) -> list:
    """数据缺失、未核项与工具边界提示（不进主要风险，不含系统 debug）。"""
    tips = []
    seen = set()

    def add(text):
        if text and text not in seen:
            seen.add(text)
            tips.append(text)

    if not score.get("financial_checked"):
        add(score.get("financial_unchecked_notice", "财务未核：用户未提供租金等经营信息。"))

    if features.get("rating_sample_count", 0) == 0:
        add("官方 rating 未返回，竞品口碑信号不足")

    if features.get("data_source") == "demo":
        add("当前为演示数据，非实时周边")

    transit_status = features.get("transit_data_status")
    if transit_status == "DATA_INCONSISTENCY":
        pass  # handled via validation_user_notes
    elif not features.get("nearest_transit_distance") and not features.get("transit"):
        add("交通距离信息不足，可达性判断可能偏保守")

    for note in features.get("validation_user_notes") or []:
        add(note)

    return tips


def _collect_advantages(features: dict, score: dict) -> list:
    """主要优势（分项表现突出时列出，无则省略整栏）。"""
    advantages = []
    sub = score.get("subscores", {})
    an = features.get("analytics") or {}

    demand = sub.get("demand", {})
    d_score, d_max = demand.get("score", 0), demand.get("max", 35)
    if d_score >= d_max * 0.75:
        advantages.append(
            f"需求匹配突出（{d_score}/{d_max}）：{an.get('scene_why', features.get('scene_label', '场景'))}"
        )

    tea_300 = features.get("tea_count_300m", 0)
    comp = sub.get("competition", {})
    if tea_300 <= 2 and comp.get("score", 0) >= comp.get("max", 30) * 0.75:
        advantages.append(f"竞争相对温和：300m 茶饮仅 {tea_300} 家")

    scene = sub.get("consumer_scene", {})
    if scene.get("score", 0) >= scene.get("max", 15) * 0.75:
        advantages.append("消费场景较好：餐饮休闲配套与顺路购买条件较优")

    transit_info = transit_distance_summary(features.get("transit", []))
    if transit_info["good_access"]:
        advantages.append(f"交通可达性较好：{transit_info['text_short']}")

    if score.get("financial_checked") and score.get("rent_ratio") is not None:
        if score["rent_ratio"] <= 0.20:
            advantages.append(f"财务评估压力可控：租金/营收约 {score['rent_ratio']:.0%}")

    if score.get("total_score", 0) >= 75 and score.get("recommendation") == "推荐选址":
        if not advantages:
            advantages.append(f"综合分 {score['total_score']} 分，各分项整体表现较好")

    return advantages


def _collect_risks(features: dict, score: dict) -> list:
    """风险章用：主要风险 + 提示合并展示。"""
    return _collect_main_risks(features, score) + _collect_tips(features, score)


def _build_summary(features: dict, score: dict) -> str:
    an = features.get("analytics") or {}
    lines: list[str] = []
    if features.get("data_source") == "demo":
        lines.extend([DEMO_REPORT_NOTICE, ""])
    lines.extend([
        f"**Recommendation：{score['recommendation']}**",
        "",
        f"**Decision implication：** {decision_implication(features, score)}",
        "",
        f"{_score_line(score)}",
    ])
    if not score.get("financial_checked"):
        lines.append(
            "**该分数为点位评分，未包含财务评估，不能直接与含财务评估的综合决策分对比。**"
        )
    lines.extend([
        "评分反映位置、需求、竞争等点位维度；财务评估单独成章；最终建议受独立否决规则约束。",
        f"点位速写：{features.get('address')} · {features.get('scene_label')} · "
        f"300m 茶饮 {features.get('tea_count_300m')} 家 · 500m 茶饮 {features.get('tea_count_500m')} 家",
        "",
        "### 核心原因",
    ])
    for r in _collect_reasons(features, score):
        lines.append(f"- {r}")

    advantages = _collect_advantages(features, score)
    if advantages:
        lines.extend(["", "### 主要优势"])
        for a in advantages:
            lines.append(f"- {a}")

    lines.extend(["", "### 主要风险"])
    main_risks = _collect_main_risks(features, score)
    if main_risks:
        for r in main_risks:
            lines.append(f"- {r}")
    else:
        lines.append(f"- {_no_main_risks_text(features, score)}")

    tips = _collect_tips(features, score)
    if tips:
        lines.extend(["", "### 提示"])
        for t in tips:
            lines.append(f"- {t}")

    rent = features.get("rent")
    fin = features.get("finance") or {}
    if rent and fin.get("est_monthly_revenue"):
        threshold = finance_threshold_note(rent, fin["est_monthly_revenue"])
        if threshold:
            lines.extend(["", "### 财务阈值参考", f"- {threshold}"])

    lines.extend([
        "",
        "### 建议（可执行）",
        "- 按工作日+周末覆盖午晚高峰，做三日蹲点：记录经过/进店/成交，区分有效人流与过路",
        "- 现场核对门头可见性、是否被遮挡、是否顺路；商场点优先核中庭/扶梯口，社区点核出入口 50m 内",
        "- 若继续谈租：用房东报价回填月租与客单价，重跑本工具看财务评估是否翻盘",
    ])
    if an.get("nearest_competitor"):
        n = an["nearest_competitor"]
        lines.append(f"- 重点对标最近竞品「{n.get('name')}」（约 {n.get('distance_m')}m）：价格带、出品与排队时段")
    disclaimer = score.get("score_disclaimer", "")
    if disclaimer:
        lines.extend(["", disclaimer])
    return "\n".join(lines)


def _template_generate(
    key: str,
    features: dict,
    score: dict,
    evidence: list,
    rag_docs: list,
    basemap_note: str = "",
) -> str:
    an = features.get("analytics") or {}
    if key == "district":
        return _chapter_district(features, score, an, rag_docs)
    if key == "demand":
        return _chapter_demand(features, score, an, rag_docs)
    if key == "competition":
        return _chapter_competition(features, score, an, rag_docs)
    if key == "transit":
        return _chapter_transit(features, score, rag_docs)
    if key == "finance":
        return _chapter_finance(features, score, rag_docs)
    if key == "risk":
        return _chapter_risk(features, score, rag_docs)
    if key == "conclusion":
        return _chapter_conclusion(features, score, rag_docs)
    if key == "map":
        basemap = basemap_note or ("街道底图：高德静态地图" if features.get("basemap_ok") else "未加载街道底图")
        return "\n".join([
            "**图层说明：** 候选点、300m/500m/1000m 查询半径圆（非路网等时圈）、"
            "直接茶饮（红/深蓝圆点）、间接饮品（咖啡/果汁等，橙色三角）、"
            "交通站点（绿色方块）。",
            basemap,
        ])
    if key == "appendix":
        return _fixed_appendix(features, score, basemap_note)
    return ""


def _chapter_district(features, score, an, rag_docs) -> str:
    scene = features.get("scene_type")
    cat500 = features.get("categories_500m") or {}
    capped = features.get("category_capped") or {}
    see = (
        f"场景判定 **{features.get('scene_label')}**：{an.get('scene_why', '')}\n"
        f"- 300m：{an.get('categories_zh_300') or format_categories(features.get('categories_300m', {}))}\n"
        f"- {district_poi_total_line(features, an)}\n"
        f"- 1000m：{an.get('categories_zh_1000')}"
    )
    meaning = {
        "mall": "商场型吃瞬时客流与曝光，楼层/动线决定转化；租金通常更高。",
        "community": "社区型吃复购与出入口，峰值不如商场但客群更稳。",
        "office": "办公型工作日午晚高峰关键，周末可能偏淡。",
        "school": "学校型年轻客群匹配，但寒暑假波动大。",
        "transit": "交通型人流大、停留短，外带与可见性优先。",
        "mixed": "多场景并存，须分清主力时段与客群。",
    }
    means = meaning.get(scene, meaning["mixed"])
    decision = (
        "开奶茶前须现场确认：是否顺路、是否死角/高层冷区、是否与主力客群动线重合；"
        "POI 只说明周边有什么，不等于门口有效人流。"
    )
    lines = insight_block(see, means, decision)
    lines.extend([
        "",
        "### 500m 结构明细",
        format_categories_lines(cat500, capped),
        "",
        "### 局限",
        "- POI 不直接等于进店率；楼层与门头须实地核。",
    ])
    if any(capped.values()):
        lines.append("- 部分 POI 类别因接口分页上限，计数达到 100 时显示为 100+，以实地调研为准。")
    lines.append(f"- 数据来源：{features.get('data_source')}，查询时间 {features.get('query_time')}。")
    return _finalize_chapter(lines, rag_docs)


def _chapter_demand(features, score, an, rag_docs) -> str:
    brand = features.get("brand_positioning", "即时饮品、年轻向")
    demand = score["subscores"]["demand"]
    cat500 = features.get("categories_500m") or {}
    scene = features.get("scene_type")
    rating_line = (
        f"500m 茶饮官方 rating 均值 **{features['rating_avg_500m']}**（n={features['rating_sample_count']}）\n"
        f"- 说明：仅统计 500m 内有返回 rating 字段的茶饮 POI 样本均值，不代表全市场口碑或客流。"
        if features.get("rating_avg_500m") is not None
        else "官方 rating 未返回"
    )
    see = (
        f"人群分析为 **POI 场景代理**（非年龄/收入画像、非客流预测）。\n"
        f"{_explain_demand_score(demand)}\n"
        f"计分按 500m 配套**数量分档**，场景判定（如商场型）本身不加分。\n"
        f"品牌定位：**{brand}**。\n"
        f"{rating_line}"
    )
    means = scene_demand_narrative(scene, cat500)
    decision = (
        "分数高只说明配套结构更支持「顺路买一杯」，仍须三日蹲点验证店门口有效人流；"
        "分数低时即使竞品少，也可能是需求不足。"
    )
    lines = insight_block(see, means, decision)
    lines.extend([
        "",
        "### 500m POI 结构",
        format_categories_lines(cat500, features.get("category_capped")),
        "",
        "### 需求匹配分档明细",
    ])
    for reason in demand.get("reasons") or []:
        lines.append(f"- {reason}")
    lines.extend([
        "",
        "### 局限",
        "- 未接入评价全文；rating 仅官方字段有则用。",
    ])
    return _finalize_chapter(lines, rag_docs)


def _chapter_competition(features, score, an, rag_docs) -> str:
    shops = features.get("tea_shops_300m", []) or []
    shops_sorted = sorted(shops, key=lambda s: s.get("distance_m") or 9999)
    bands = an.get("distance_bands_300") or {}
    comp = score["subscores"]["competition"]
    brand = features.get("brand_positioning") or "即时饮品、年轻向"
    see, means, decision = competition_insight(
        features.get("tea_count_300m", 0),
        features.get("tea_count_500m", 0),
        bands,
        an.get("chain_300", 0),
        brand,
    )
    see = (
        f"竞争环境分 **{comp['score']}/{comp['max']}**（{competition_pressure_phrase(comp['score'], comp['max'])}）。\n" + see
        + f"\n间接饮品（咖啡/果汁）300m **{features.get('indirect_count_300m', 0)}** 家"
        f"（其中咖啡约 {features.get('indirect_coffee_300m', 0)} 家），500m **{features.get('indirect_count_500m', 0)}** 家。"
    )
    if features.get("indirect_capped"):
        see += (
            "\n间接饮品 POI 已达接口返回上限（单类最多约 100 条），"
            "500m 数量可能被低估；若 300m 与 500m 计数接近，应优先以实地调研为准。"
        )
    lines = insight_block(see, means, decision)
    lines.extend([
        "",
        "### 竞争数量对照表",
        "| 类型 | 300m | 500m | 说明 |",
        "| --- | --- | --- | --- |",
        f"| 直接茶饮 | {features.get('tea_count_300m', 0)} | {features.get('tea_count_500m', 0)} | 计入竞争计分 |",
        f"| 间接饮品（咖啡/果汁等） | {features.get('indirect_count_300m', 0)} | {features.get('indirect_count_500m', 0)} | 单独统计，不计入茶饮家数 |",
        "",
        "### 直接茶饮清单（300m，直线距离）",
    ])
    if not shops_sorted:
        lines.append("- 300m 内未发现直接茶饮 POI")
    else:
        lines.append("| 店名 | 直线距离 | 连锁 | rating |")
        lines.append("| --- | --- | --- | --- |")
        for s in shops_sorted[:20]:
            rating = s.get("rating")
            rating_s = f"{rating}" if rating is not None else "未返回"
            chain = "是" if s.get("chain") else "否"
            lines.append(f"| {s.get('name', '未知')} | {s.get('distance_m', '—')}m | {chain} | {rating_s} |")

    indirect = features.get("indirect_beverages_300m") or []
    lines.extend(["", "### 间接饮品清单（300m）"])
    if not indirect:
        lines.append("- 300m 内未发现咖啡/果汁类间接饮品 POI")
    else:
        lines.append("| 店名 | 直线距离 | 类型 |")
        lines.append("| --- | --- | --- |")
        for s in sorted(indirect, key=lambda x: x.get("distance_m") or 9999)[:15]:
            subtype = "咖啡" if s.get("beverage_subtype") == "coffee" else "其他饮品"
            lines.append(f"| {s.get('name', '未知')} | {s.get('distance_m', '—')}m | {subtype} |")

    lines.extend([
        "",
        "### 局限",
        "- POI 可能有滞后；连锁识别依赖公开名单。",
        "- 禁止编造排队、营业额。",
    ])
    return _finalize_chapter(lines, rag_docs)


def _chapter_transit(features, score, rag_docs) -> str:
    transit = sorted(
        features.get("transit", []) or [],
        key=lambda t: float(t.get("distance_m") or 99999),
    )
    scene = score["subscores"]["consumer_scene"]
    transit_info = transit_distance_summary(transit)
    nearest_d = transit_info.get("nearest_transit_distance")
    see_parts = [
        f"消费场景分 **{scene['score']}/{scene['max']}**；",
        f"{transit_info['text']}。",
    ]
    if nearest_d is not None:
        see_parts.append(f"- **最近交通直线距离**：{int(nearest_d)}m（全量交通 POI 最小值）")
    if transit:
        for t in transit[:5]:
            walk = ""
            walk_m = valid_walk_distance(t.get("distance_m"), t.get("walk_distance_m"))
            if walk_m is not None:
                walk = f"，路网步行约 {walk_m}m"
            else:
                walk = f"（{t.get('walk_note', '仅直线距离')}）"
            see_parts.append(
                f"- **{t.get('name')}**：直线 {t.get('distance_m')}m{walk}"
            )
    else:
        status = features.get("transit_data_status")
        if status == "DATA_INCONSISTENCY":
            see_parts.append(
                "- 候选地址含交通站点线索，但周边交通 POI 未返回对应站点；"
                "本章不将交通 POI 作为可靠证据，可达性判断已降级。"
            )
        else:
            see_parts.append("- 1000m 内未发现地铁/公交 POI（或数据未返回）")
    see = "\n".join(see_parts)
    means = (
        "近地铁/公交有利于通勤外带，但不等于店门口有效停留；"
        "枢纽型点位常见「人多不进店」。半径圆为查询半径，非步行等时圈。"
    )
    decision = "交通是加分项而非充分条件；须现场确认从站点到铺位是否顺路、有无遮挡。"
    lines = insight_block(see, means, decision)
    lines.extend([
        "",
        "### 局限",
        "- 路径规划失败时已降级为直线距离并注明。",
    ])
    return _finalize_chapter(lines, rag_docs)


def _chapter_finance(features, score, rag_docs) -> str:
    fin = features.get("finance") or {}
    if not score.get("financial_checked"):
        return _finalize_chapter([
            "### 1. 判断",
            f"**{score.get('financial_unchecked_notice', '财务未核')}**",
            "",
            "### 2. 当前已填信息",
            f"- 面积：{features.get('area_sqm') or '未填'}",
            f"- 月租：{features.get('rent') or '未填'}",
            f"- 客单价：{features.get('price') or '未填'}",
            f"- 预估月营收：{features.get('revenue') or '未填'}",
            f"- 预估日杯量：{features.get('daily_cups') or '未填'}",
            "",
            "### 3. 建议你补哪些数再重跑",
            "- 至少：月租 +（预估月营收 **或** 客单价+日杯量）",
            "- 经验安全线（非国标）：租金占营收一般宜控制在较低区间；超过 30% 本工具会触发财务否决",
            "",
            "### 4. 局限",
            "- 无经营输入时，综合决策分无法计算，点位评分高 ≠ 能赚钱。",
        ], rag_docs)

    ratio = score.get("rent_ratio")
    cost = score["subscores"]["cost"]
    see = (
        f"财务评估分 **{cost.get('score')}/{cost.get('max')}**；"
        f"租金/营收约 **{ratio:.1%}**。"
        + ("（接近30%谨慎线）" if ratio and ratio >= 0.27 and ratio <= 0.30 else "")
        + ("（偏紧）" if ratio and 0.25 < ratio < 0.27 else "")
        + f"\n- 月租 {features.get('rent')}；估算月营收 {fin.get('est_monthly_revenue')}"
    )
    if fin.get("breakeven_cups_day") is not None:
        see += f"\n- 仅覆盖租金粗算日杯量约 **{fin['breakeven_cups_day']}** 杯（未含人工水电）"
    means = "本页为条件敏感性测算，不是营业额预测；占比偏高时应优先压租或提高营收假设。"
    decision = "若 Conservative 情景仍偏高，不建议签约；Better 情景仅说明改善方向，不作承诺。"
    lines = insight_block(see, means, decision)

    scenarios = build_scenario_table(features, score)
    if scenarios:
        lines.extend([
            "",
            "### 情景分析（条件敏感性，非预测）",
            "| 情景 | 月租 | 月营收 | 租金/营收 | 经营压力 | 建议 |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for row in scenarios:
            rp = f"{row['ratio_pct']}%" if row.get("ratio_pct") is not None else "—"
            lines.append(
                f"| {row['name']} | {row['rent']} | {row['revenue']} | {rp} | {row['pressure']} | {row['advice']} |"
            )
        lines.append("- 口径：Conservative 营收×0.85；Better 租金×0.9 且营收×1.1；仅作压力对比。")

    rent = features.get("rent")
    rev = fin.get("est_monthly_revenue")
    if rent:
        threshold = finance_threshold_note(rent, rev)
        if threshold:
            lines.extend(["", "### 决策阈值参考", f"- {threshold}"])
    if ratio and rent and rev and ratio > 0.30:
        lines.extend(["", "### 租金压力说明", f"- {finance_rent_pressure_detail(rent, rev, ratio)}"])

    lines.extend([
        "",
        "### 局限",
        "- 未建模全成本；转让费、递增须看合同。",
    ])
    return _finalize_chapter(lines, rag_docs)


def _chapter_risk(features, score, rag_docs) -> str:
    main_risks = _collect_main_risks(features, score)
    tips = _collect_tips(features, score)
    lines = [
        "### 1. 主要风险（经营与选址）",
    ]
    if main_risks:
        for i, r in enumerate(main_risks, 1):
            lines.append(f"{i}. {r}")
    else:
        lines.append(f"1. {_no_main_risks_text(features, score)}")

    lines.append("")
    lines.append("### 2. 提示（数据缺失与未核项）")
    if tips:
        for i, t in enumerate(tips, 1):
            lines.append(f"{i}. {t}")
    else:
        lines.append("暂无关键数据缺失")

    lines.extend([
        "",
        "### 3. 必须现场确认（不进综合分）",
        "- 门头 15–20m 外是否可见，是否被树/柱/广告牌遮挡",
        "- 人流动线是否顺路，是否需要绕行",
        "- 商场：是否中庭/扶梯口/美食区，是否电梯死角或高层冷区",
        "- 社区：是否主出入口约 50m 内、菜场或多小区交汇",
        "- 物业：电容量、上下水、外摆与招牌限制",
        "",
        "### 4. 局限",
        "- 政策新闻未自动计分；若你有政策备注请自行写入决策附件。",
    ])
    return _finalize_chapter(lines, rag_docs)


def _chapter_conclusion(features, score, rag_docs) -> str:
    if score.get("financial_checked"):
        score_head = f"综合决策分 **{score['total_score']}/100**"
    else:
        score_head = f"点位评分 **{score['total_score']}/{score.get('max_possible', 80)}**"
    lines = [
        "### 1. 结论",
        f"{score_head}，最终建议 **{score['recommendation']}**。",
        "",
        score_summary_line(score),
        "",
        decision_implication(features, score),
        "",
        "该建议由程序规则与否决条件给出，不是模型另打分。",
        "",
        "### 2. 为什么是这个档",
    ]
    for r in _collect_reasons(features, score)[:4]:
        lines.append(f"- {r}")
    if score.get("veto_reasons"):
        lines.append("- 触发否决/降档：" + "；".join(score["veto_reasons"]))

    section = 3
    rent = features.get("rent")
    fin = features.get("finance") or {}
    threshold = None
    if rent and fin.get("est_monthly_revenue"):
        threshold = finance_threshold_note(rent, fin["est_monthly_revenue"])
    if threshold:
        lines.extend(["", f"### {section}. 财务阈值参考", f"- {threshold}"])
        ratio = score.get("rent_ratio")
        rev = fin.get("est_monthly_revenue")
        if ratio and rent and rev and ratio > 0.30:
            lines.append(f"- {finance_rent_pressure_detail(rent, rev, ratio)}")
        section += 1

    lines.extend([
        "",
        f"### {section}. 下一步行动清单",
        f"{section}.1. **三日蹲点**：覆盖工作日+周末；时段建议 11:30–13:30、17:30–19:30、20:30–22:00；每 15 分钟记经过/进店/成交",
        f"{section}.2. **竞品对标**：对 300m 内最近 3 家记录价格带、招牌品、堂食/外带比例",
        f"{section}.3. **财务回填**：拿到月租意向后，连同客单价/预估杯量重跑本报告，看成本项是否改变建议档",
        f"{section}.4. **租约**：关注递增方式、转让费、租期是否足以摊销装修",
        "",
        f"### {section + 1}. 局限声明",
        "- 本工具是初筛助手，不能替代现场调研与签约前尽职调查。",
    ])
    return _finalize_chapter(lines, rag_docs)


def _data_mode_line(features: dict) -> str:
    if features.get("data_source") == "demo":
        return "数据模式：演示数据"
    return "数据模式：实时 API 查询"


def _fixed_appendix(features: dict, score: dict, basemap_note: str = "") -> str:
    if basemap_note:
        basemap_line = basemap_note.replace("街道底图：", "", 1).strip()
        if not basemap_line.startswith("高德"):
            basemap_line = basemap_note
    elif features.get("basemap_ok"):
        basemap_line = "高德静态街道底图（已加载）"
    else:
        basemap_line = "未加载街道底图"
    disclaimer = score.get("score_disclaimer", "")
    demo_line = ""
    if features.get("data_source") == "demo":
        demo_line = f"- **报告类型：** 演示点报告（内置脱敏数据，非真实点位分析）\n"
    return f"""{demo_line}- **位置与竞争：** {_data_mode_line(features)}
- **街道底图：** {basemap_line}
- **选址分析图：** 高德栅格底图叠加分析图层；提供 PNG 与 SVG 下载
- **租金、面积、客单价、品牌定位、预估营收/杯量：** 用户提供；未提供则财务结论降级
- **客流：** 未实地计数；不以公开信息冒充客流预测；人群为 POI 场景代理
- **评分数字：** 仅当官方字段返回时使用；评价全文未接入
- **选址方法、租金经验安全线、调研口径：** 本地知识库
- **{disclaimer}**
- **建议**结合现场调研（动线、楼层、可见性、三日人流）再决策

### 计分口径摘要

- 需求匹配 35 + 竞争环境 30 + 消费场景 15 + 财务评估 20（需经营输入）
- 300m 茶饮 ≥9 家：建议档最高「谨慎选址」
- 已填财务且租金/营收 >30%：不推荐
- 未填租金：输出点位评分（未含财务评估），须结合财务回填再决策
"""


def _score_level_label(score: float, max_score: float) -> str:
    if not max_score:
        return "—"
    ratio = score / max_score
    if ratio >= 0.75:
        return "较强"
    if ratio >= 0.45:
        return "中等"
    return "偏弱"


def _explain_demand_score(demand: dict) -> str:
    s, m = demand.get("score", 0), demand.get("max", 35)
    level = _score_level_label(s, m)
    pct = round(s / m * 100) if m else 0
    meanings = {
        "较强": "500m 内商场、办公、餐饮等配套数量达到较高档，「顺路买一杯」相对成立；仍须核实店门口动线与有效人流。判定为商场型不会自动给满分。",
        "中等": "有一定消费配套，但按数量分档尚未到高档，或结构不均衡；需对照品牌定位判断是否真匹配。",
        "偏弱": "500m 内支撑茶饮即时消费的配套偏少；即使竞品不多，也可能属于需求不足而非空白机会。",
    }
    return (
        f"**{s}/{m} 分**（约满分 {pct}%）表示需求匹配**{level}**：{meanings.get(level, '')}"
    )


def _finalize_chapter(lines: list, rag_docs: list) -> str:
    """正文完成后，知识库引用固定为最后一段。"""
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            cleaned.append("")
            continue
        if "本段参考知识库" in s or "知识库要点摘录" in s:
            continue
        if s.startswith("> "):
            continue
        if s.startswith("<p class=\"kb-ref\"") or s.startswith("<p class='kb-ref'"):
            continue
        cleaned.append(line)
    body = "\n".join(cleaned).rstrip()
    return body + _rag_block(rag_docs)


def _rag_block(docs: list) -> str:
    if not docs:
        return ""
    refs = "、".join(d["filename"] for d in docs)
    return '\n\n<p class="kb-ref">本段参考知识库：{}</p>'.format(refs)


def _evidence_hint(*args):
    return None


def _ev_footer(eid):
    return ""


def _filter_evidence(key: str, evidence: list) -> list:
    if key == "competition":
        return [e for e in evidence if any(x in e.get("claim", "") for x in ("茶饮", "竞品", "竞争", "连锁"))]
    if key == "transit":
        return [e for e in evidence if "交通" in e.get("claim", "")]
    if key == "finance":
        return [e for e in evidence if any(x in e.get("claim", "") for x in ("租金", "财务", "杯"))]
    if key == "district":
        return [e for e in evidence if any(x in e.get("claim", "") for x in ("场景", "POI", "候选点", "配套"))]
    if key == "demand":
        return [e for e in evidence if any(x in e.get("claim", "") for x in ("场景", "rating", "需求"))]
    return evidence[:8]


async def _llm_generate(
    key: str,
    title: str,
    features: dict,
    score: dict,
    evidence: list,
    rag_docs: list,
    user_llm_key,
    basemap_note: str = "",
) -> str:
    api_key = user_llm_key or os.getenv("LLM_API_KEY")
    fallback = _template_generate(key, features, score, evidence, rag_docs, basemap_note)
    if not api_key:
        return fallback

    system = _load_system_prompt()
    an = features.get("analytics") or {}
    user_msg = json.dumps(
        {
            "chapter": title,
            "instruction": (
                "用咨询报告口吻扩写本章。必须包含：判断、依据、含义、局限。"
                "只能使用 evidence / analytics / finance 中的事实与数字。"
                "禁止编造店名、客流、回本。不得修改 score_locked。"
                "可引用 knowledge 作方法提示，但不得把方法说成已在现场验证的事实。"
            ),
            "score_locked": {
                "total": score["total_score"],
                "recommendation": score["recommendation"],
                "subscores": score.get("subscores"),
                "veto_reasons": score.get("veto_reasons"),
            },
            "point": {
                "address": features.get("address"),
                "scene_label": features.get("scene_label"),
                "brand_positioning": features.get("brand_positioning"),
                "tea_count_300m": features.get("tea_count_300m"),
                "tea_count_500m": features.get("tea_count_500m"),
                "analytics": an,
                "finance": features.get("finance"),
            },
            "evidence": evidence,
            "knowledge": [{"file": d["filename"], "text": d["body"][:1000]} for d in rag_docs],
        },
        ensure_ascii=False,
    )

    base = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.25,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        text = data["choices"][0]["message"]["content"]
        # 若模型几乎没写，回落模板
        if not text or len(text.strip()) < 80:
            return fallback
        return _finalize_chapter([text], rag_docs)
    except Exception as exc:
        return fallback + f"\n\n（LLM 调用失败，已降级深度模板：{exc}）"


def _load_system_prompt() -> str:
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "prompts" / "system.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "你是奶茶店选址报告撰写助手。只能使用提供的证据。禁止编造。"
