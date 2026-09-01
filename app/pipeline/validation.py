"""POI bundle validation and consistency fixes before scoring."""

from __future__ import annotations

from app.pipeline.report_state import sanitize_transit_walk_distances

CATEGORY_KEYS = (
    "mall",
    "dining",
    "leisure",
    "school",
    "office",
    "community",
    "transit",
    "hotel",
)

# Internal debug / eval panel only — never shown verbatim in customer report
INTERNAL_DEBUG_PREFIXES = (
    "QC：",
    "m ",
    "茶饮嵌套",
)


def normalize_poi_bundle(bundle: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Fix tea/indirect nesting; validate category monotonicity; record internal flags."""
    internal: List[str] = []
    user_notes: List[str] = []
    raw_transit = bundle.get("transit") or []
    cleaned = sanitize_transit_walk_distances(raw_transit)
    if cleaned != raw_transit:
        for before, after in zip(raw_transit, cleaned):
            if before.get("walk_distance_m") and not after.get("walk_distance_m"):
                internal.append(
                    f"TRANSIT_WALK_INVALID: {before.get('name')} walk<{before.get('distance_m')}m"
                )
        bundle["transit"] = cleaned
    poi = bundle.get("poi_by_radius") or {}
    if not poi:
        return bundle, internal, user_notes

    _fix_tea_nested_counts(poi, internal)
    _fix_indirect_nested_counts(poi, internal)
    _validate_category_monotonicity(poi, internal, user_notes)
    _check_transit_consistency(bundle, internal, user_notes)

    bundle["poi_by_radius"] = poi
    bundle["validation_internal"] = internal
    bundle["validation_user_notes"] = user_notes
    return bundle, internal, user_notes


def _fix_tea_nested_counts(poi: dict, internal: List[str]) -> None:
    all_shops = poi.get("1000", {}).get("tea_shops") or []
    if not all_shops:
        for r in ("500", "300"):
            cand = poi.get(r, {}).get("tea_shops") or []
            if len(cand) > len(all_shops):
                all_shops = cand
    for radius in ("300", "500", "1000"):
        limit = int(radius)
        poi.setdefault(radius, {})
        poi[radius]["tea_shops"] = [s for s in all_shops if (s.get("distance_m") or 9999) <= limit]

    c300 = len(poi["300"]["tea_shops"])
    c500 = len(poi["500"]["tea_shops"])
    c1000 = len(poi["1000"]["tea_shops"])
    if not (c300 <= c500 <= c1000):
        internal.append(
            f"DATA_INCONSISTENCY: tea nested counts 300m={c300}, 500m={c500}, 1000m={c1000}"
        )


def _fix_indirect_nested_counts(poi: dict, internal: List[str]) -> None:
    all_items = poi.get("1000", {}).get("indirect_beverages") or []
    if not all_items:
        for r in ("500", "300"):
            cand = poi.get(r, {}).get("indirect_beverages") or []
            if len(cand) > len(all_items):
                all_items = cand
    for radius in ("300", "500", "1000"):
        limit = int(radius)
        poi.setdefault(radius, {})
        poi[radius]["indirect_beverages"] = [
            s for s in all_items if (s.get("distance_m") or 9999) <= limit
        ]


def _validate_category_monotonicity(poi: dict, internal: List[str], user_notes: List[str]) -> None:
    """Verify 300m <= 500m <= 1000m per category; do NOT copy inner-circle values outward."""
    prev: Dict[str, int] = {k: 0 for k in CATEGORY_KEYS}
    had_inconsistency = False
    for radius in ("300", "500", "1000"):
        cats = poi.setdefault(radius, {}).setdefault("categories", {})
        for key in CATEGORY_KEYS:
            raw = int(cats.get(key, 0) or 0)
            if raw < prev[key]:
                had_inconsistency = True
                internal.append(
                    f"DATA_INCONSISTENCY: {radius}m {key} count {raw} < inner {prev[key]}"
                )
            prev[key] = max(prev[key], raw)
            cats[key] = raw

    if had_inconsistency:
        _add_user_note(
            user_notes,
            "部分半径 POI 分类数据存在接口异常，相关指标已降级标注，请以实地调研为准。",
        )


def _check_transit_consistency(bundle: dict, internal: List[str], user_notes: List[str]) -> None:
    address = (bundle.get("address") or "") + (bundle.get("city") or "")
    transit = bundle.get("transit") or []
    hints = ("地铁", "轨道交通", "站", "Metro", "Subway")
    has_address_hint = any(h in address for h in hints)

    if has_address_hint and not transit:
        bundle["transit_data_status"] = "DATA_INCONSISTENCY"
        internal.append("DATA_INCONSISTENCY: address transit hint but POI query empty")
        _add_user_note(
            user_notes,
            "候选地址信息含交通站点线索，但周边交通 POI 查询未返回对应站点；"
            "本报告不将交通 POI 作为可靠证据，可达性判断已降级标注。",
        )
    elif transit:
        bundle["transit_data_status"] = "OK"
        nearest = min(t.get("distance_m") or 99999 for t in transit)
        if nearest > 800 and any(h in address for h in ("地铁", "轨道交通")):
            internal.append(f"DATA_UNCERTAIN: subway hint in address but nearest transit {nearest}m")
            _add_user_note(
                user_notes,
                "地址含地铁线索，但最近交通 POI 距离较远，建议核对落点或现场步行距离。",
            )
    else:
        bundle["transit_data_status"] = "MISSING"


def _add_user_note(notes: List[str], text: str) -> None:
    if text not in notes:
        notes.append(text)


def is_internal_debug_message(text: str) -> bool:
    """True if message should only appear in eval/debug panel, not customer report."""
    if not text:
        return True
    if text.startswith("DATA_INCONSISTENCY") or text.startswith("DATA_UNCERTAIN"):
        return True
    if "已修正为" in text:
        return True
    if "小于内圈" in text and "计数" in text:
        return True
    for prefix in INTERNAL_DEBUG_PREFIXES:
        if text.startswith(prefix):
            return True
    if text.startswith("QC：") or text.startswith("QC:"):
        return True
    return False


def run_report_qc(features: dict, score: dict, evidence: list) -> Tuple[List[str], List[str]]:
    from app.pipeline.report_insights import run_report_qc as _qc
    return _qc(features, score, evidence)
