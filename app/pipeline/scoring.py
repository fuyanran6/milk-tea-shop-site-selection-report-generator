"""Load scoring configuration and compute scores with veto rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

import yaml

from app.pipeline.features import CAT_LABELS, format_count_display
from app.pipeline.report_state import poi_total_unreliable

ROOT = Path(__file__).resolve().parents[2]
SCORING_PATH = ROOT / "config" / "scoring.yaml"


def load_scoring_config() -> dict[str, Any]:
    with open(SCORING_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _competition_score(tea_count_300m: int, cfg: dict) -> tuple[float, str]:
    for tier in cfg["competition_tiers"]:
        if tea_count_300m <= tier["max_count"]:
            return float(tier["score"]), tier["label"]
    return 8.0, "低"


def _tier_score(count: int, tiers: list) -> float:
    for tier in tiers:
        if count <= int(tier["max_count"]):
            return float(tier["score"])
    return float(tiers[-1]["score"]) if tiers else 0.0


def _demand_score(
    categories_500m: dict,
    tea_300m: int,
    dining_500m: int,
    cfg: dict,
    category_capped: Optional[dict] = None,
) -> Tuple[float, List[str]]:
    """按 500m 配套数量分档计分；场景类型不直接加分。"""
    demand_cfg = cfg["demand"]
    category_capped = category_capped or {}
    total = sum(categories_500m.values())
    reasons: list[str] = []

    if total <= demand_cfg["min_poi_total"] and not any(category_capped.values()):
        reasons.append(f"500m 内 POI 总量仅 {total}，需求匹配极低")
        return float(demand_cfg["weak_demand_max_score"]), reasons

    score = 0.0
    weights = demand_cfg["category_weights"]
    tiers_map = demand_cfg.get("category_tiers") or {}
    for cat, w in weights.items():
        count = int(categories_500m.get(cat, 0) or 0)
        capped = bool(category_capped.get(cat))
        disp = format_count_display(count, capped)
        label = CAT_LABELS.get(cat, cat)
        cat_tiers = tiers_map.get(cat)
        if cat_tiers:
            contrib = _tier_score(count, cat_tiers)
        elif count > 0:
            # 无分档配置时按数量比例，避免「有 1 家就拿满」
            contrib = float(w) * min(1.0, count / max(float(w) * 2, 1.0))
        else:
            contrib = 0.0
        if contrib > 0:
            reasons.append(f"{label} {disp} 家 → {contrib:.0f}/{w} 分")
        score += contrib

    score = min(float(cfg["weights"]["demand"]), score)

    if tea_300m == 0 and dining_500m <= 2:
        score = min(score, float(demand_cfg["weak_demand_max_score"]))
        reasons.append("300m 无茶饮且 500m 餐饮极弱，禁止空白地带满分")

    return score, reasons


def _consumer_scene_score(
    categories_500m: dict,
    transit_effective_m: Optional[float],
    transit_has_walk: bool,
    cfg: dict,
    scene_type: str = "mixed",
) -> Tuple[float, List[str]]:
    cs_cfg = cfg["consumer_scene"]
    dining = categories_500m.get("dining", 0)
    leisure = categories_500m.get("leisure", 0)
    office = categories_500m.get("office", 0)
    transit = categories_500m.get("transit", 0)
    mall = categories_500m.get("mall", 0)
    dining_score = min(1.0, (dining + leisure * 0.5) / 15.0)

    transit_score = 0.3
    if transit_effective_m is not None:
        if transit_effective_m <= cs_cfg["transit_near_m"]:
            transit_score = 1.0
        elif transit_effective_m <= cs_cfg["transit_far_m"]:
            transit_score = 0.6
        else:
            transit_score = 0.2

    raw = dining_score * cs_cfg["dining_leisure_weight"] + transit_score * cs_cfg["transit_weight"]

    peak_factor = 1.0
    if scene_type in ("office", "transit"):
        peak_factor = 0.78
    elif scene_type == "mixed" and office >= 30 and transit >= 20 and mall < 15:
        peak_factor = 0.80
    elif scene_type == "mixed" and office >= 20 and transit >= 15:
        peak_factor = 0.85

    score = raw * peak_factor * float(cfg["weights"]["consumer_scene"])
    if transit_effective_m is None:
        transit_reason = "交通距离信息不足"
    else:
        transit_reason = f"最近交通直线约 {int(transit_effective_m)}m"
        if transit_has_walk:
            transit_reason += "（最近站点另有步行路径数据，见交通章节）"
        elif transit_effective_m > cs_cfg["transit_near_m"]:
            transit_reason += "（非步行路径，交通便利性需现场核实）"
    reasons = [
        f"500m 餐饮 {dining} 家、休闲 {leisure} 家",
        transit_reason,
    ]
    if peak_factor < 1.0:
        reasons.append(
            "办公/交通枢纽主导场景：工作日平峰（如 14:00–16:00）客流可能断崖，"
            "消费场景分已作时段性保守折算"
        )
    return score, reasons


def _cost_score(rent, revenue, price, daily_cups, cfg) -> Tuple[Optional[float], List[str], Optional[float]]:
    if rent is None or rent <= 0:
        return None, ["未提供月租，成本项未评分"], None

    if revenue and revenue > 0:
        ratio = rent / revenue
    elif price and price > 0 and daily_cups and daily_cups > 0:
        est_revenue = price * daily_cups * 30
        ratio = rent / est_revenue
        revenue = est_revenue
    else:
        return None, ["已填月租但缺少客单价或预估月营收/杯量，成本项未评分"], None

    ideal = cfg["cost"]["ideal_rent_ratio"]
    if ratio <= ideal:
        score = float(cfg["cost"]["max_score"])
    elif ratio <= cfg["cost"]["rent_ratio_veto"]:
        score = float(cfg["cost"]["max_score"]) * (1 - (ratio - ideal) / (cfg["cost"]["rent_ratio_veto"] - ideal) * 0.5)
    else:
        score = 0.0

    return score, [f"租金/营收占比 {ratio:.1%}"], ratio


def compute_score(features: dict[str, Any], user_inputs: dict[str, Any]) -> dict[str, Any]:
    cfg = load_scoring_config()
    w = cfg["weights"]

    tea_300m = features.get("tea_count_300m", 0)
    categories_500m = features.get("categories_500m", {})
    dining_500m = categories_500m.get("dining", 0)
    transit_nearest = features.get("transit_nearest_m")
    transit_has_walk = bool(features.get("transit_has_walk_route"))

    comp_score, comp_label = _competition_score(tea_300m, cfg)
    demand_score, demand_reasons = _demand_score(
        categories_500m, tea_300m, dining_500m, cfg, features.get("category_capped")
    )
    scene_score, scene_reasons = _consumer_scene_score(
        categories_500m, transit_nearest, transit_has_walk, cfg, features.get("scene_type", "mixed")
    )

    rent = _parse_float(user_inputs.get("rent"))
    revenue = _parse_float(user_inputs.get("revenue"))
    price = _parse_float(user_inputs.get("price"))
    daily_cups = _parse_float(user_inputs.get("daily_cups"))

    cost_score, cost_reasons, rent_ratio = _cost_score(rent, revenue, price, daily_cups, cfg)
    financial_checked = cost_score is not None

    scored_total = comp_score + demand_score + scene_score
    max_scored = w["competition"] + w["demand"] + w["consumer_scene"]
    if financial_checked:
        scored_total += cost_score
        max_scored += w["cost"]

    position_max = w["competition"] + w["demand"] + w["consumer_scene"]
    normalized = round(scored_total / max_scored * 100, 1) if max_scored > 0 else 0.0
    display_score = normalized if financial_checked else round(scored_total, 1)
    display_max = 100 if financial_checked else position_max

    veto_reasons: list[str] = []
    recommendation = _score_to_recommendation(normalized, cfg)

    if tea_300m >= cfg["veto"]["competition_dense_count"]:
        veto_reasons.append(f"300m 茶饮 {tea_300m} 家 ≥ {cfg['veto']['competition_dense_count']}，竞争过密")
        if recommendation == cfg["recommendation_labels"]["recommend"]:
            recommendation = cfg["recommendation_labels"]["cautious"]

    poi_total_500 = sum(categories_500m.values())
    if poi_total_500 <= cfg["veto"]["demand_too_low_poi_total"]:
        if not poi_total_unreliable(features):
            veto_reasons.append(f"500m POI 总量 {poi_total_500}，需求匹配过低")
            recommendation = cfg["recommendation_labels"]["reject"]

    if rent_ratio is not None and rent_ratio > cfg["veto"]["rent_ratio_veto"]:
        veto_reasons.append(f"租金/营收 {rent_ratio:.1%} > 30%，财务否决")
        recommendation = cfg["recommendation_labels"]["reject"]

    return {
        "subscores": {
            "demand": {"score": round(demand_score, 1), "max": w["demand"], "reasons": demand_reasons},
            "competition": {"score": round(comp_score, 1), "max": w["competition"], "label": comp_label, "tea_300m": tea_300m},
            "consumer_scene": {"score": round(scene_score, 1), "max": w["consumer_scene"], "reasons": scene_reasons},
            "cost": {"score": round(cost_score, 1) if cost_score is not None else None, "max": w["cost"], "reasons": cost_reasons},
        },
        "total_score": display_score,
        "max_possible": display_max,
        "normalized_score": normalized,
        "financial_checked": financial_checked,
        "financial_unchecked_notice": None if financial_checked else cfg["financial_unchecked_notice"].strip(),
        "recommendation": recommendation,
        "veto_reasons": veto_reasons,
        "score_disclaimer": (
            cfg["score_disclaimer"].strip()
            if financial_checked
            else cfg.get("score_disclaimer_unchecked", cfg["score_disclaimer"]).strip()
        ),
        "rent_ratio": rent_ratio,
    }


def _score_to_recommendation(score: float, cfg: dict) -> str:
    labels = cfg["recommendation_labels"]
    th = cfg["recommendation_thresholds"]
    if score >= th["recommend"]:
        return labels["recommend"]
    if score >= th["cautious"]:
        return labels["cautious"]
    return labels["reject"]


def _parse_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
