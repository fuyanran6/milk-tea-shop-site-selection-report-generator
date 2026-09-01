"""Report state consistency checks (QA)."""

from __future__ import annotations

from typing import Any, Optional

# 与 amap_poi.CATEGORY_FETCH_* 保持一致
CATEGORY_DISPLAY_CAP = 100


def valid_walk_distance(straight_m: Any, walk_m: Any) -> Optional[int]:
    """Walking route must not be shorter than straight-line distance."""
    if straight_m is None or walk_m is None:
        return None
    try:
        straight = int(float(straight_m))
        walk = int(float(walk_m))
    except (TypeError, ValueError):
        return None
    if walk < straight:
        return None
    return walk


def sanitize_transit_walk_distances(transit_list: list) -> list:
    """Drop implausible walking distances (walk < straight)."""
    cleaned: list = []
    for t in transit_list or []:
        if not isinstance(t, dict):
            continue
        item = dict(t)
        straight = item.get("distance_m")
        walk = valid_walk_distance(straight, item.get("walk_distance_m"))
        if walk is None:
            item["walk_distance_m"] = None
            if item.get("walk_note") == "步行路径规划成功":
                item["walk_note"] = "步行路径异常，仅直线距离"
        else:
            item["walk_distance_m"] = walk
        cleaned.append(item)
    return cleaned


def nearest_transit_distance_m(transit_list: list) -> Optional[float]:
    """最近交通直线距离 = 所有返回交通 POI 中 distance_m 的最小值。"""
    distances: list[float] = []
    for t in transit_list or []:
        d = t.get("distance_m")
        if d is not None:
            distances.append(float(d))
    return min(distances) if distances else None


def pick_nearest_transit(transit_list: list) -> Optional[dict]:
    """直线距离最近的交通 POI（与 nearest_transit_distance_m 对应）。"""
    best: Optional[dict] = None
    best_d: Optional[float] = None
    for t in transit_list or []:
        d = t.get("distance_m")
        if d is None:
            continue
        d = float(d)
        if best_d is None or d < best_d:
            best_d = d
            best = t
    return best


def transit_distance_summary(transit_list: list) -> dict[str, Any]:
    nearest_d = nearest_transit_distance_m(transit_list)
    t = pick_nearest_transit(transit_list)
    if nearest_d is None or not t:
        return {
            "nearest_transit_distance": None,
            "effective_m": None,
            "straight_m": None,
            "walk_m": None,
            "has_walk": False,
            "text": "交通距离信息不足",
            "text_short": "交通距离信息不足",
            "good_access": False,
        }
    straight = nearest_d
    walk = valid_walk_distance(straight, t.get("walk_distance_m"))
    has_walk = walk is not None
    if has_walk and straight is not None:
        text = f"最近交通：路网步行距离约 {int(walk)}m（直线约 {int(straight)}m）"
        text_short = f"路网步行距离约 {int(walk)}m（直线约 {int(straight)}m）"
        good_access = walk <= 500
    elif has_walk:
        text = f"最近交通：路网步行距离约 {int(walk)}m"
        text_short = f"路网步行距离约 {int(walk)}m"
        good_access = walk <= 500
    else:
        text = f"最近交通：直线距离约 {int(straight)}m（非实际步行路径，需现场实测）"
        text_short = text
        good_access = False
    return {
        "nearest_transit_distance": straight,
        "effective_m": straight,
        "straight_m": straight,
        "walk_m": walk,
        "has_walk": has_walk,
        "text": text,
        "text_short": text_short,
        "good_access": good_access,
    }


def resolve_transit_features(transit_list: list) -> dict[str, Any]:
    info = transit_distance_summary(transit_list)
    return {
        "nearest_transit_distance": info["nearest_transit_distance"],
        "transit_nearest_m": info["nearest_transit_distance"],
        "transit_nearest_straight_m": info["straight_m"],
        "transit_nearest_walk_m": info["walk_m"],
        "transit_has_walk_route": info["has_walk"],
        "transit_summary_text": info["text"],
    }


def rent_pressure_phrase(ratio: Optional[float]) -> Optional[str]:
    """租金/营收压力表述（>30% 为否决，约 30% 为谨慎线）。"""
    if ratio is None:
        return None
    if ratio > 0.30:
        return f"租金/营收 {ratio:.1%} > 30%，触发财务否决"
    if ratio >= 0.27:
        return f"租金处于本工具30%压力谨慎线：租金/营收约 {ratio:.0%}"
    if ratio > 0.25:
        return f"租金压力偏高：租金/营收约 {ratio:.0%}"
    return None


def poi_total_unreliable(features: dict) -> bool:
    capped = features.get("category_capped") or {}
    return any(capped.values())


def district_poi_total_line(features: dict, an: dict) -> str:
    if poi_total_unreliable(features):
        return (
            "500m 内多个 POI 类别达到接口返回上限，无法可靠统计总量；"
            "以下采用分类结构进行判断。"
        )
    total = an.get("poi_total_500", 0)
    top = "、".join(f"{n}{c}" for n, c in (an.get("top_categories_500") or [])[:4]) or "无"
    return f"500m POI 总量约 **{total}**；主导：{top}"


def competition_pressure_phrase(score: float, max_score: float) -> str:
    if not max_score:
        return "竞争压力：—"
    ratio = score / max_score
    if ratio >= 0.75:
        level = "低"
    elif ratio >= 0.45:
        level = "中"
    else:
        level = "高"
    return f"竞争压力：{level}（{score}/{max_score}）"


def score_summary_line(score: dict) -> str:
    if score.get("financial_checked"):
        line = f"综合决策分 {score['total_score']}/100（点位评分 + 财务评估）"
    else:
        max_p = score.get("max_possible", 80)
        line = f"点位评分 {score['total_score']}/{max_p}（未含财务评估）"
    veto = score.get("veto_reasons") or []
    if veto:
        if any("租金" in v or "财务" in v for v in veto):
            source = "程序计分 + 财务否决规则"
        else:
            source = "程序计分 + 否决规则"
        line += f"；最终建议「{score['recommendation']}」（来源：{source}）"
    else:
        line += f"；最终建议「{score['recommendation']}」（来源：程序计分）"
    return line


def finance_rent_pressure_detail(rent: float, revenue: float, ratio: float) -> str:
    min_rev = rent / 0.30
    uplift = ((min_rev / revenue) - 1) * 100 if revenue > 0 else None
    better_ratio = (rent * 0.9) / (revenue * 1.1) * 100 if revenue > 0 else None
    text = (
        f"在当前租金不变的情况下，月营收需提升至约 {min_rev:,.0f} 元，"
        f"租金/营收才可降至 30% 以内"
    )
    if uplift is not None:
        text += f"，较当前营收假设仍需提升约 {uplift:.0f}%"
    if better_ratio is not None:
        text += f"。即使 Better 情景下仍为 {better_ratio:.1f}%，说明当前租金压力仍是结构性限制"
    text += "。以上为压力阈值计算，不是营业额预测。"
    return text


def validate_report_consistency(features: dict, score: dict, report: dict) -> list[str]:
    """Return internal QC errors; empty if OK."""
    issues: list[str] = []
    is_demo = features.get("data_source") == "demo"
    tea_300 = features.get("tea_count_300m", 0)
    tea_500 = features.get("tea_count_500m", 0)
    fin_checked = score.get("financial_checked")

    if not is_demo:
        forbidden = ["示例茶饮", "演示点A", "演示点 A", "当前为演示数据", "非实时周边"]
        if fin_checked:
            forbidden.extend(["财务未核", "未提供租金等经营信息"])
        for key, ch in (report.get("chapters") or {}).items():
            text = ch.get("content", "") + " " + ch.get("headline", "")
            for token in forbidden:
                if token in text:
                    issues.append(f"QC：章节 {key} 含污染文本「{token}」")

    if poi_total_unreliable(features):
        for key, ch in (report.get("chapters") or {}).items():
            if "POI 总量约" in ch.get("content", ""):
                issues.append(f"QC：章节 {key} 仍含不可靠 POI 总量")

    if fin_checked and score.get("recommendation") == "推荐选址":
        ratio = score.get("rent_ratio")
        if ratio and ratio > 0.30:
            issues.append("QC：租金/营收>30% 但建议为推荐选址")

    if tea_300 == 0 and not is_demo:
        for key in ("risk", "summary"):
            ch = (report.get("chapters") or {}).get(key, {})
            if "300m 茶饮 9" in ch.get("content", "") or "茶饮9" in ch.get("content", ""):
                issues.append(f"QC：章节 {key} 含与 state 不符的茶饮数量")

    rec = score.get("recommendation")
    for key, ch in (report.get("chapters") or {}).items():
        content = ch.get("content", "")
        if "推荐选址" in content and rec == "不推荐" and key in ("summary", "conclusion"):
            if "**Recommendation：推荐" in content:
                issues.append(f"QC：章节 {key} 建议档与 score 不一致")

    return issues
