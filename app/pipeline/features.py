"""Extract structured features and evidence table from POI bundle."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.pipeline.report_state import (
    CATEGORY_DISPLAY_CAP,
    resolve_transit_features,
    sanitize_transit_walk_distances,
    score_summary_line,
)
from typing import Any, Dict, List, Optional


CAT_LABELS = {
    "mall": "商场/购物",
    "dining": "餐饮",
    "leisure": "休闲娱乐",
    "school": "学校",
    "office": "写字楼/商务",
    "community": "居住小区",
    "transit": "交通",
    "hotel": "酒店",
}

SCENE_LABELS = {
    "mall": "商场型",
    "office": "办公型",
    "community": "社区型",
    "school": "学校型",
    "transit": "交通型",
    "mixed": "混合型",
}

NO_MAIN_RISK_LINE = (
    "未发现重大显性点位风险；仍建议现场核对门头可见性、楼层/动线、租约条款等。"
)


def format_count_display(count: int, capped: bool = False) -> str:
    """Only show trailing + when count reached the API fetch cap (typically 100)."""
    if capped and count >= CATEGORY_DISPLAY_CAP:
        return f"{count}+"
    return str(count)


def format_report_address(
    address: str,
    city: str,
    place_name: Optional[str] = None,
    location: Optional[dict] = None,
) -> str:
    """Readable address for map-pick / city-only cases; always include coords when known."""
    place = (place_name or "").strip()
    addr = (address or "").strip()
    city = (city or "").strip()

    coord_suffix = ""
    if location and location.get("lng") is not None and location.get("lat") is not None:
        coord_suffix = f"（经度 {location['lng']:.6f}，纬度 {location['lat']:.6f}）"

    addr_is_city_only = bool(
        addr and city and addr in (city, f"{city}市", city.rstrip("市") + "市", city.rstrip("市"))
    )
    addr_is_candidate = "候选点" in addr or not addr

    if place:
        base = f"{city} · {place}" if city else place
    elif addr and not addr_is_city_only and not addr_is_candidate:
        base = addr
    elif city:
        base = f"{city} · 地图选点"
    else:
        base = "地图选点"

    return f"{base}{coord_suffix}" if coord_suffix else base


def build_features(bundle: Dict[str, Any], user_inputs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_inputs = user_inputs or {}
    poi = bundle.get("poi_by_radius", {})
    r300 = poi.get("300", {})
    r500 = poi.get("500", {})
    r1000 = poi.get("1000", {})

    tea_300 = r300.get("tea_shops", [])
    tea_500 = r500.get("tea_shops", [])
    tea_1000 = r1000.get("tea_shops", [])
    indirect_300 = r300.get("indirect_beverages", [])
    indirect_500 = r500.get("indirect_beverages", [])
    indirect_1000 = r1000.get("indirect_beverages", [])
    categories_500 = r500.get("categories", {})
    categories_1000 = r1000.get("categories", {})
    categories_300 = r300.get("categories", {})

    transit_list = sanitize_transit_walk_distances(bundle.get("transit", []))
    transit_fields = resolve_transit_features(transit_list)

    category_capped = bundle.get("poi_meta", {}).get("category_capped", {})
    indirect_capped = bundle.get("poi_meta", {}).get("indirect_capped", False)

    ratings = [s.get("rating") for s in tea_500 if s.get("rating") is not None]
    rating_avg = round(sum(ratings) / len(ratings), 2) if ratings else None

    scene_type = infer_scene_type(categories_500, bundle.get("scene_type"))
    display_address = format_report_address(
        bundle.get("address", ""),
        bundle.get("city", ""),
        user_inputs.get("place_name"),
        bundle.get("location", {}),
    )
    analytics = _build_analytics(
        tea_300, tea_500, indirect_300, indirect_500,
        categories_300, categories_500, categories_1000, scene_type,
        category_capped,
    )

    rent = _parse_float(user_inputs.get("rent"))
    price = _parse_float(user_inputs.get("price"))
    revenue = _parse_float(user_inputs.get("revenue"))
    daily_cups = _parse_float(user_inputs.get("daily_cups"))
    finance = _finance_metrics(rent, price, revenue, daily_cups)

    return {
        "address": display_address,
        "city": bundle.get("city", ""),
        "location": bundle.get("location", {}),
        "category_capped": category_capped,
        "indirect_capped": indirect_capped,
        "scene_type": scene_type,
        "scene_label": SCENE_LABELS.get(scene_type, scene_type),
        "query_time": bundle.get("query_time", _now_iso()),
        "data_source": bundle.get("data_source", "unknown"),
        "tea_count_300m": len(tea_300),
        "tea_count_500m": len(tea_500),
        "indirect_count_300m": len(indirect_300),
        "indirect_count_500m": len(indirect_500),
        "indirect_coffee_300m": sum(1 for s in indirect_300 if s.get("beverage_subtype") == "coffee"),
        "categories_300m": categories_300,
        "categories_500m": categories_500,
        "categories_1000m": categories_1000,
        "tea_shops_300m": tea_300,
        "tea_shops_500m": tea_500,
        "tea_shops_1000m": tea_1000,
        "indirect_beverages_300m": indirect_300,
        "indirect_beverages_500m": indirect_500,
        "indirect_beverages_1000m": indirect_1000,
        "transit": transit_list,
        **transit_fields,
        "rating_avg_500m": rating_avg,
        "rating_sample_count": len(ratings),
        "transit_data_status": bundle.get("transit_data_status"),
        "validation_user_notes": bundle.get("validation_user_notes", []),
        "buildings": bundle.get("buildings", []),
        "brand_positioning": user_inputs.get("brand_positioning") or "即时饮品、年轻向",
        "area_sqm": user_inputs.get("area"),
        "rent": rent,
        "price": price,
        "revenue": revenue,
        "daily_cups": daily_cups,
        "analytics": analytics,
        "finance": finance,
    }


def infer_scene_type(categories_500: dict, hint: Optional[str] = None) -> str:
    if hint:
        return hint

    mall = categories_500.get("mall", 0)
    dining = categories_500.get("dining", 0)
    leisure = categories_500.get("leisure", 0)
    hotel = categories_500.get("hotel", 0)
    office = categories_500.get("office", 0)
    community = categories_500.get("community", 0)
    school = categories_500.get("school", 0)
    transit = categories_500.get("transit", 0)

    # 商场型须有足够商场锚点，且商场密度相对办公/交通突出（小型社区配套不算大型 Mall）
    mall_qualified = mall >= 5 and mall >= max(office * 0.18, transit * 0.15, 4)

    scores = {
        "mall": (mall * 5 + dining * 0.25 + leisure * 0.2 + hotel * 0.15) if mall_qualified else 0.0,
        "office": office * 2.8 + dining * 0.35 + transit * 0.25,
        "community": community * 2.5 + dining * 0.2,
        "school": school * 3.2,
        "transit": transit * 2.6 + office * 0.35,
    }
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_key, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    if top_score == 0:
        return "mixed"
    if top_key == "office" and mall >= 3 and not mall_qualified:
        return "mixed"
    if second_score > 0 and top_score <= second_score * 1.35:
        return "mixed"
    return top_key


def format_categories(cats: dict, capped: Optional[dict] = None) -> str:
    if not cats:
        return "无"
    capped = capped or {}
    parts = []
    for k, v in sorted(cats.items(), key=lambda x: -x[1]):
        if v:
            disp = format_count_display(v, capped.get(k, False))
            parts.append(f"{CAT_LABELS.get(k, k)} {disp}")
    return "、".join(parts) if parts else "无"


def format_categories_lines(cats: dict, capped: Optional[dict] = None, show_zero: bool = True) -> str:
    """500m 结构等：每类 POI 单独一行，中文标签。"""
    capped = capped or {}
    if not cats and not show_zero:
        return "- 无 POI 分类数据"
    lines = []
    for key, label in CAT_LABELS.items():
        count = cats.get(key, 0)
        if count > 0 or show_zero:
            disp = format_count_display(count, capped.get(key, False))
            lines.append(f"- {label}：{disp}")
    return "\n".join(lines) if lines else "- 无 POI 分类数据"


def _build_analytics(
    tea_300: list,
    tea_500: list,
    indirect_300: list,
    indirect_500: list,
    cat300: dict,
    cat500: dict,
    cat1000: dict,
    scene_type: str,
    category_capped: Optional[dict] = None,
) -> dict:
    chain_300 = sum(1 for s in tea_300 if s.get("chain"))
    indep_300 = len(tea_300) - chain_300
    nearest = None
    if tea_300:
        nearest = min(tea_300, key=lambda s: s.get("distance_m") or 99999)

    # band: within 100 / 100-200 / 200-300
    bands = {"0-100m": 0, "100-200m": 0, "200-300m": 0}
    for s in tea_300:
        d = s.get("distance_m") or 0
        if d <= 100:
            bands["0-100m"] += 1
        elif d <= 200:
            bands["100-200m"] += 1
        else:
            bands["200-300m"] += 1

    # top drivers of scene
    ranked = sorted(cat500.items(), key=lambda x: -x[1])
    top_cats = [(CAT_LABELS.get(k, k), v) for k, v in ranked if v > 0][:5]

    density_note = ""
    n = len(tea_300)
    if n >= 9:
        density_note = "贴身茶饮供给较多，存在分流风险，需结合价格带与差异化判断，不宜单凭地图点位数量断言红海"
    elif n >= 6:
        density_note = "竞争中等偏强，需错开价格带或场景，不宜同质化进场"
    elif n >= 3:
        density_note = "存在一定竞品，可验证是否同档扎堆"
    elif n >= 1:
        density_note = (
            "贴身存在茶饮竞品，近场分流与同质化风险需结合价格带判断；"
            "竞争环境不宜视为「零风险」"
        )
    else:
        dining_300 = cat300.get("dining", 0)
        dining_disp = format_count_display(dining_300, category_capped.get("dining", False))
        if dining_300 < 10:
            density_note = "无茶饮竞品且餐饮配套较弱，需警惕是否为需求空白而非蓝海。"
        elif dining_300 >= 30:
            density_note = (
                f"虽无贴身茶饮竞品，但周边餐饮配套成熟（{dining_disp}家），"
                f"需现场验证餐饮客流是否转化为饮品购买习惯。"
            )
        else:
            density_note = "竞品较少，但购买场景需现场蹲点验证。"

    return {
        "chain_300": chain_300,
        "independent_300": indep_300,
        "chain_ratio_300": round(chain_300 / len(tea_300), 2) if tea_300 else None,
        "nearest_competitor": nearest,
        "distance_bands_300": bands,
        "top_categories_500": top_cats,
        "density_note": density_note,
        "categories_zh_300": format_categories(cat300, category_capped),
        "categories_zh_500": format_categories(cat500, category_capped),
        "categories_zh_1000": format_categories(cat1000, category_capped),
        "poi_total_500": sum(cat500.values()) if not any((category_capped or {}).values()) else None,
        "scene_why": _scene_why(scene_type, cat500, category_capped),
        "indirect_300": len(indirect_300),
        "indirect_500": len(indirect_500),
        "indirect_coffee_300": sum(1 for s in indirect_300 if s.get("beverage_subtype") == "coffee"),
    }


def _scene_why(scene_type: str, cat500: dict, category_capped: Optional[dict] = None) -> str:
    label = SCENE_LABELS.get(scene_type, scene_type)
    capped = category_capped or {}
    dining = cat500.get("dining", 0)
    leisure = cat500.get("leisure", 0)
    mall = cat500.get("mall", 0)
    office = cat500.get("office", 0)
    community = cat500.get("community", 0)
    school = cat500.get("school", 0)
    transit = cat500.get("transit", 0)
    commercial = dining + leisure + mall

    def disp(cat: str, n: int) -> str:
        return format_count_display(n, capped.get(cat, False))

    if scene_type == "mall":
        return (
            f"判定为{label}：500m 内商场/购物 {disp('mall', mall)}、"
            f"餐饮 {disp('dining', dining)}、休闲娱乐 {disp('leisure', leisure)}，"
            f"商业配套集中，更接近逛街瞬时消费场景"
        )
    if scene_type == "community":
        return f"判定为{label}：居住小区 {disp('community', community)} 相对突出，更依赖复购与出入口动线"
    if scene_type == "office":
        return (
            f"判定为{label}：写字楼/商务 {disp('office', office)} 相对突出"
            f"（同期餐饮 {disp('dining', dining)}、休闲 {disp('leisure', leisure)}），"
            f"工作日午晚高峰更关键"
        )
    if scene_type == "school":
        return f"判定为{label}：学校 {disp('school', school)} 突出，客群年轻但受寒暑假波动"
    if scene_type == "transit":
        return f"判定为{label}：交通 POI {disp('transit', transit)} 突出，人流大但停留短，外带更重要"
    drivers = []
    if commercial >= 10:
        drivers.append(
            f"商业配套（餐饮 {disp('dining', dining)}+休闲 {disp('leisure', leisure)}+商场 {disp('mall', mall)}）"
        )
    if office >= 5:
        drivers.append(f"办公 {disp('office', office)}")
    if community >= 3:
        drivers.append(f"居住 {disp('community', community)}")
    if school >= 2:
        drivers.append(f"学校 {disp('school', school)}")
    if transit >= 2:
        drivers.append(f"交通 {disp('transit', transit)}")
    if drivers:
        return f"判定为{label}：{'、'.join(drivers)} 等并存，无单一场景绝对主导"
    return f"判定为{label}：多种配套并存，无明显单一主导场景"


def _finance_metrics(rent, price, revenue, daily_cups) -> dict:
    out = {
        "has_rent": rent is not None and rent > 0,
        "est_monthly_revenue": None,
        "rent_ratio": None,
        "breakeven_cups_day": None,
        "cups_gap": None,
        "notes": [],
    }
    if rent is None or rent <= 0:
        out["notes"].append("未提供月租")
        return out

    est_rev = None
    if revenue and revenue > 0:
        est_rev = revenue
        out["notes"].append("营收采用用户填写的预估月营收")
    elif price and price > 0 and daily_cups and daily_cups > 0:
        est_rev = price * daily_cups * 30
        out["notes"].append("营收按「客单价×日杯量×30」估算")
    else:
        out["notes"].append("有月租但缺少客单价或营收/杯量，无法算租金占比")
        return out

    out["est_monthly_revenue"] = round(est_rev, 2)
    out["rent_ratio"] = round(rent / est_rev, 4) if est_rev else None

    if price and price > 0:
        # 粗口径：仅用租金覆盖所需日杯量（未含人工水电），作压力示意
        cups = rent / (price * 30)
        out["breakeven_cups_day"] = round(cups, 1)
        out["notes"].append("保本日杯量为「仅覆盖租金」粗算，未含人工/水电/原料，需实地补全")
        if daily_cups and daily_cups > 0:
            out["cups_gap"] = round(daily_cups - cups, 1)

    return out


def build_evidence_table(features: Dict[str, Any], score_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = []
    idx = 1
    an = features.get("analytics") or {}

    def add(claim: str, source: str, detail: str, data: Any = None):
        nonlocal idx
        eid = f"E{idx:03d}"
        evidence.append({"claim_id": eid, "claim": claim, "source": source, "detail": detail, "data": data})
        idx += 1
        return eid

    add(
        f"候选点位于 {features.get('address')}",
        features.get("data_source", "unknown"),
        f"坐标 {features.get('location')}，查询时间 {features.get('query_time')}",
        features.get("location"),
    )
    add(
        f"推断场景：{features.get('scene_label')}（{features.get('scene_type')}）",
        f"{features.get('data_source')} POI 500m 结构",
        an.get("scene_why", ""),
    )
    add(
        f"300m 茶饮 {features['tea_count_300m']} 家（连锁 {an.get('chain_300', 0)} / 非连锁 {an.get('independent_300', 0)}）",
        f"{features.get('data_source')} POI 300m",
        an.get("density_note", "竞争计分主指标"),
        features.get("tea_shops_300m"),
    )
    add(
        f"300m 间接饮品 {features.get('indirect_count_300m', 0)} 家（咖啡约 {features.get('indirect_coffee_300m', 0)}）",
        f"{features.get('data_source')} POI 300m",
        "间接饮品（咖啡/果汁等），不计入茶饮竞争家数",
        features.get("indirect_beverages_300m"),
    )
    add(
        f"500m 茶饮 {features['tea_count_500m']} 家；500m POI 结构：{an.get('categories_zh_500')}",
        f"{features.get('data_source')} POI 500m",
        (
            "多类 POI 触顶，总量不可靠"
            if (features.get("category_capped") or {})
            else f"POI 总量 {an.get('poi_total_500')}"
        ),
    )
    add(
        f"1000m 配套结构：{an.get('categories_zh_1000')}",
        f"{features.get('data_source')} POI 1000m",
        "更大范围配套对照",
    )

    nearest = an.get("nearest_competitor")
    if nearest:
        add(
            f"最近茶饮竞品 {nearest.get('name')}，约 {nearest.get('distance_m')}m",
            "竞品名单",
            "chain=" + str(nearest.get("chain")),
        )

    if features.get("rating_avg_500m") is not None:
        add(
            f"500m 茶饮官方 rating 均值 {features['rating_avg_500m']}（n={features['rating_sample_count']}）",
            "高德 extensions=all rating 字段",
            "有则使用，无则不编造",
        )
    else:
        add("500m 茶饮 rating 未返回", "接口字段", "不得编造评分")

    nearest_d = features.get("nearest_transit_distance")
    if nearest_d is not None:
        transit_text = features.get("transit_summary_text") or f"最近交通直线约 {int(nearest_d)}m"
        add(
            transit_text,
            "POI 直线/步行距离",
            f"nearest_transit_distance={nearest_d}m; " + str(features.get("transit")),
        )

    fin = features.get("finance") or {}
    if fin.get("rent_ratio") is not None:
        add(
            f"租金/营收约 {fin['rent_ratio']:.1%}",
            "用户经营输入 + 公式",
            "；".join(fin.get("notes") or []),
        )
    if fin.get("breakeven_cups_day") is not None:
        add(
            f"仅覆盖租金约需日售 {fin['breakeven_cups_day']} 杯（粗算）",
            "用户客单价 + 月租",
            "未含人工水电原料",
        )

    add(
        score_summary_line(score_result),
        "程序计分 scoring.yaml",
        f"分项 {score_result['subscores']}",
    )
    for vr in score_result.get("veto_reasons", []):
        add(vr, "否决规则", "优先于分数")

    if not score_result.get("financial_checked"):
        add(score_result.get("financial_unchecked_notice", "财务未核"), "用户输入", "未提供租金等")

    return evidence


def _parse_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat()
