"""V2 consulting-style report helpers: insight blocks, titles, scenarios, QC."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.pipeline.report_state import transit_distance_summary


def insight_block(see: str, means: str, decision: str) -> List[str]:
    return [
        "### What we see（数据事实）",
        see,
        "",
        "### What it means（商业含义）",
        means,
        "",
        "### Decision implication（决策含义）",
        decision,
    ]


def decision_implication(features: dict, score: dict) -> str:
    rec = score.get("recommendation", "")
    tea_300 = features.get("tea_count_300m", 0)
    brand = features.get("brand_positioning") or "即时饮品、年轻向"
    ratio = score.get("rent_ratio")

    if rec == "不推荐":
        if ratio and ratio > 0.30:
            return (
                f"点位评分反映已评分维度，但因租金/营收 {ratio:.1%} > 30% 触发财务否决，"
                "最终建议为「不推荐」；除非租金显著下降或营收假设大幅提高，否则不宜推进。"
            )
        if tea_300 >= 9:
            return (
                "当前不建议以标准大众茶饮模型进入：贴身茶饮竞争过密，"
                "同质化进场易被分流；若坚持该点位，需有清晰差异化（品类/价格/场景）并压租后再评估。"
            )
        return (
            "当前不建议以标准大众茶饮模型进入；"
            "需先解决主要风险（竞争、需求或成本）后再重新生成报告。"
        )
    if rec == "谨慎选址":
        parts = ["当前仅适合谨慎推进：位置或竞争存在明显约束。"]
        if "差异化" not in brand and tea_300 >= 3:
            parts.append("若采用明确差异化定位或租金进一步下降，可重新评估。")
        else:
            parts.append("建议完成三日蹲点与财务回填后再决策。")
        return "".join(parts)
    if not score.get("financial_checked"):
        return (
            "**该分数为点位评分，未包含财务评估，不能直接与含财务评估的综合决策分对比。** "
            "地图与竞争维度表现较好，但仍须先完成财务回填（月租、客单价或预估营收）、"
            "三日蹲点与门头可见性核对后，再决定是否进入租约谈判；不宜仅凭点位分签约。"
        )
    return (
        "当前可进入下一步谈判与实地验证："
        "仍需完成蹲点、门头可见性与租约条款核对，不宜仅凭地图分数签约。"
    )


def chapter_title(key: str, features: dict, score: dict) -> str:
    an = features.get("analytics") or {}
    scene = features.get("scene_type", "mixed")
    tea_300 = features.get("tea_count_300m", 0)

    if key == "district":
        label = features.get("scene_label", "混合型")
        top = an.get("top_categories_500") or []
        if len(top) <= 1:
            return f"点位具备{label}客群基础，但消费场景较单一"
        return f"点位以{label}为主，500m 配套结构已成型"

    if key == "competition":
        bands = an.get("distance_bands_300") or {}
        near = bands.get("0-100m", 0)
        if tea_300 >= 9:
            return "核心风险来自高密度的近场直接竞争"
        if tea_300 >= 6 or near >= 2:
            return "贴身竞争集中，进入需差异化或压租"
        if tea_300 == 0:
            return "贴身茶饮竞品稀少，需核实需求而非盲目乐观"
        return "竞争环境可控，重点核对同档扎堆与价格带"

    if key == "demand":
        return f"需求匹配依赖{features.get('scene_label', '场景')}，非客流普查"

    if key == "transit":
        info = transit_distance_summary(features.get("transit", []))
        effective = info.get("effective_m")
        if info.get("has_walk") and effective and effective <= 500:
            return "交通站点较近，外带场景相对有利"
        return "交通可达性一般，顺路消费转化待验证"

    if key == "finance":
        if not score.get("financial_checked"):
            return "经营可行性：财务评估未核，点位评分≠能赚钱"
        ratio = score.get("rent_ratio")
        if ratio and ratio > 0.30:
            return "财务评估：租金/营收超30%，触发否决"
        if ratio and ratio >= 0.27:
            return "财务评估：处于30%压力谨慎线"
        if ratio and ratio > 0.25:
            return "财务评估：租金压力偏高，需压租或提高营收"
        return "经营压力可测算，仍需补全全成本"

    if key == "risk":
        return "风险与数据边界（含未核项）"

    if key == "conclusion":
        return f"结论：{score.get('recommendation', '—')}及下一步"

    return dict(
        summary="决策摘要",
        district="商圈与场景",
        demand="消费者与需求匹配",
        competition="竞争分析",
        transit="交通与可达性",
        finance="经营可行性",
        risk="风险因素",
        conclusion="结论与建议",
        map="选址分析图",
        appendix="数据说明与来源附录",
    ).get(key, key)


def map_headline(features: dict) -> str:
    an = features.get("analytics") or {}
    tea = features.get("tea_count_300m", 0)
    if tea >= 9:
        return "核心竞争圈（300m）茶饮密度高"
    if tea >= 6:
        return "300m 核心圈存在多家直接竞品"
    return f"{features.get('scene_label', '选址')} · 300m 茶饮 {tea} 家"


def scene_demand_narrative(scene_type: str, cat500: dict) -> str:
    office = cat500.get("office", 0)
    community = cat500.get("community", 0)
    mall = cat500.get("mall", 0)
    school = cat500.get("school", 0)
    transit = cat500.get("transit", 0)
    leisure = cat500.get("leisure", 0)

    if scene_type == "office":
        return (
            "该点位具有稳定办公型消费基础（工作日午间、下班外带更关键），"
            "但周末与夜间需求存在不确定性；需核写字楼到达动线与堂食/外带比例。"
        )
    if scene_type == "community":
        return (
            "社区型更依赖下午、晚间与家庭消费，复购与出入口便利重要；"
            "人流峰值不如商场，寒暑假对周边学校联动点有波动。"
        )
    if scene_type == "mall":
        return (
            "商场型依赖瞬时客流与动线曝光，周末与节假日弹性较大；"
            "铺位楼层与是否位于餐饮/中庭区将显著影响转化。"
        )
    if scene_type == "school":
        return (
            "学校型年轻客群匹配度高，但寒暑假、考试周波动大；"
            "价格敏感度通常更高，需对照品牌定位。"
        )
    if scene_type == "transit":
        return (
            "交通型顺路消费潜力大，但停留意愿与有效转化不确定；"
            "外带与可见性优先于堂食体验。"
        )
    drivers = []
    if office:
        drivers.append(f"办公 {office}")
    if community:
        drivers.append(f"居住 {community}")
    if mall:
        drivers.append(f"商业 {mall}")
    if not drivers:
        return "多种场景信号不强，购买场景支撑偏弱，需靠实地蹲点确认主力客群时段。"
    if office >= 20 and transit >= 15:
        return (
            f"混合型：500m 内 {'、'.join(drivers)} 等并存；"
            "人流更偏「通勤白领 + 周末文娱/旅游」双高峰，"
            "工作日平峰（14:00–16:00）可能冷清，不宜按全天候逛街客流假设排班。"
        )
    return (
        f"混合型：500m 内 {'、'.join(drivers)} 等并存，"
        "需分清工作日与周末谁才是主力，避免用单一场景假设安排产品与排班。"
    )


def competition_insight(tea_300: int, tea_500: int, bands: dict, chain_300: int, brand: str) -> tuple[str, str, str]:
    near = bands.get("0-100m", 0)
    see = (
        f"300m 直接茶饮 {tea_300} 家（500m {tea_500} 家对照）；"
        f"0–100m {near} 家、100–200m {bands.get('100-200m', 0)} 家、200–300m {bands.get('200-300m', 0)} 家；"
        f"连锁 {chain_300} 家、非连锁 {tea_300 - chain_300} 家。"
    )
    if tea_300 >= 9:
        means = (
            "地图点位较多说明周边存在茶饮消费基础，但贴身供给已较密集；"
            "是否构成「红海」须结合价格带、动线与现场转化验证，不能单凭 POI 家数下结论。"
        )
        decision = (
            "不建议标准化大众茶饮模型直接进入；"
            "若品牌具备明显产品、价格或场景差异化，应结合压租与蹲点后再评估。"
        )
    elif tea_300 >= 6 or near >= 2:
        means = (
            "近场已有较多茶饮供给，说明存在消费基础，但贴身竞品将分流有限客流；"
            "同价格带扎堆风险需现场核实。"
        )
        decision = "谨慎进场：优先错位（品类/价位/时段）或争取更优铺位，避免与头部连锁硬碰。"
    elif tea_300 >= 1:
        means = (
            "贴身已有茶饮竞品，存在近场分流与同质化风险；"
            "竞争环境分不会按「零竞品」给满分，需结合价格带与动线判断。"
        )
        decision = f"对照品牌定位「{brand}」判断是补位还是同质化；建议对标最近 3 家竞品菜单与客群。"
    else:
        means = "贴身无茶饮 POI；若餐饮配套也弱，更可能是需求不足而非蓝海。"
        decision = "不宜因「竞品少」单独乐观；先验证门口有效人流与购买场景。"
    return see, means, decision


def build_scenario_table(features: dict, score: dict) -> Optional[List[dict]]:
    fin = features.get("finance") or {}
    rent = features.get("rent")
    base_rev = fin.get("est_monthly_revenue")
    if not rent or not base_rev or rent <= 0 or base_rev <= 0:
        return None

    def row(name: str, rent_v: float, rev_v: float) -> dict:
        ratio = rent_v / rev_v if rev_v else None
        if ratio is None:
            pressure, advice = "—", "数据不足"
        elif ratio > 0.30:
            pressure, advice = "高", "不推荐"
        elif ratio > 0.22:
            pressure, advice = "中", "谨慎"
        else:
            pressure, advice = "低", "可继续评估"
        return {
            "name": name,
            "rent": round(rent_v, 0),
            "revenue": round(rev_v, 0),
            "ratio_pct": round(ratio * 100, 1) if ratio else None,
            "pressure": pressure,
            "advice": advice,
        }

    return [
        row("Conservative（营收 -15%）", rent, base_rev * 0.85),
        row("Base（当前输入）", rent, base_rev),
        row("Better（租金 -10% 且营收 +10%）", rent * 0.9, base_rev * 1.1),
    ]


def finance_threshold_note(rent: float, revenue: Optional[float] = None) -> Optional[str]:
    """Explain what revenue/rent is needed at 30% rent ratio threshold."""
    if not rent or rent <= 0:
        return None
    min_revenue = rent / 0.30
    return (
        f"按租金占营收 ≤30% 的谨慎线，月租 {rent:,.0f} 元时月营收需不低于约 {min_revenue:,.0f} 元；"
        f"此为压力阈值示意，非盈利预测。"
    )


def run_report_qc(features: dict, score: dict, evidence: list) -> Tuple[List[str], List[str]]:
    """Pre-report quality checks; returns (internal_debug, user_facing_notes)."""
    internal: list[str] = []
    user: list[str] = []
    t300 = features.get("tea_count_300m", 0)
    t500 = features.get("tea_count_500m", 0)
    if t300 > t500:
        internal.append(f"QC：300m 茶饮数({t300}) > 500m({t500})")
        if "部分半径 POI" not in " ".join(user):
            user.append("部分半径 POI 数据存在接口异常，相关指标已降级标注，请以实地调研为准。")

    listed = len(features.get("tea_shops_300m") or [])
    if listed != t300:
        internal.append(f"QC：报告竞品清单条数({listed})与计数({t300})不一致")

    if score.get("recommendation") == "推荐选址" and score.get("veto_reasons"):
        internal.append("QC：建议档与否决原因并存，需人工核对")

    if score.get("financial_checked"):
        ratio = score.get("rent_ratio")
        if ratio and ratio > 0.30 and score.get("recommendation") != "不推荐":
            internal.append("QC：租金/营收>30% 但建议档非「不推荐」，需核对否决规则")

    return internal, user
