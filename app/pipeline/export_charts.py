"""Bar charts for report chapters (matplotlib PNG)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.pipeline.features import CAT_LABELS

# 与「点位评分分项」图一致的柱状图配色
BAR_COLOR_SCORE = "#33415C"
BAR_COLOR_MAX = "#E2E5E9"


def render_report_charts(features: dict, score: dict, out_dir: Path) -> Dict[str, List[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts: Dict[str, List[str]] = {}

    p = _chart_subscores(score, out_dir / "chart_scores.png")
    if p:
        charts.setdefault("summary", []).append(p.name)

    p = _chart_poi_500(features, out_dir / "chart_poi_500.png")
    if p:
        charts.setdefault("district", []).append(p.name)

    p = _chart_competition_compare(features, out_dir / "chart_competition.png")
    if p:
        charts.setdefault("competition", []).append(p.name)

    p = _chart_distance_bands(features, out_dir / "chart_distance_bands.png")
    if p:
        charts.setdefault("competition", []).append(p.name)

    return charts


def _font(size=9):
    from matplotlib.font_manager import FontProperties
    for name in ("Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"):
        try:
            return FontProperties(family=name, size=size)
        except Exception:
            continue
    from matplotlib.font_manager import FontProperties
    return FontProperties(size=size)


def _prep_ax(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="both", labelsize=8)


def _legend_below(ax, ncol: int = 2) -> None:
    """Place legend below the x-axis so it never covers bars."""
    ax.legend(
        prop=_font(7),
        fontsize=7,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=ncol,
        framealpha=0.9,
        borderaxespad=0,
    )


def _save(fig, path: Path) -> Path:
    fig.savefig(path, bbox_inches="tight", pad_inches=0.12, dpi=110)
    plt.close(fig)
    return path


def _chart_subscores(score: dict, path: Path) -> Optional[Path]:
    subs = score.get("subscores") or {}
    labels, vals, maxs = [], [], []
    zh = {"demand": "需求匹配", "competition": "竞争环境", "consumer_scene": "消费场景", "cost": "财务评估"}
    for key, sub in subs.items():
        if sub.get("score") is None:
            continue
        labels.append(zh.get(key, key))
        vals.append(sub["score"])
        maxs.append(sub.get("max", 0))
    if not labels:
        return None

    n = len(labels)
    fig, ax = plt.subplots(figsize=(max(4.2, n * 1.05), 2.6))
    _prep_ax(ax)
    x = np.arange(n)
    w = 0.28
    ax.bar(x - w / 2, vals, w, color=BAR_COLOR_SCORE, alpha=0.95, label="得分", zorder=3)
    ax.bar(x + w / 2, maxs, w, color=BAR_COLOR_MAX, alpha=0.95, label="满分", zorder=2)
    ymax = max(max(maxs), max(vals), 1) * 1.18
    ax.set_ylim(0, ymax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontproperties=_font(8))
    ax.set_ylabel("分", fontproperties=_font(8))
    title = "点位评分分项"
    ax.set_title(title, fontproperties=_font(10), pad=8)
    for i, (v, m) in enumerate(zip(vals, maxs)):
        ax.text(i - w / 2, v + ymax * 0.02, f"{v}", ha="center", va="bottom", fontsize=7)
        ax.text(i + w / 2, m + ymax * 0.02, f"{m}", ha="center", va="bottom", fontsize=7, color="#666")
    _legend_below(ax, ncol=2)
    fig.subplots_adjust(left=0.12, right=0.97, top=0.82, bottom=0.26)
    return _save(fig, path)


def _chart_poi_500(features: dict, path: Path) -> Optional[Path]:
    cats = features.get("categories_500m") or {}
    items = [(CAT_LABELS.get(k, k), v) for k, v in cats.items() if v > 0]
    if not items:
        return None
    items.sort(key=lambda x: -x[1])
    labels, vals = zip(*items)
    n = len(labels)
    fig_h = max(2.4, n * 0.38)
    fig, ax = plt.subplots(figsize=(4.2, fig_h))
    _prep_ax(ax)
    y = np.arange(n)
    ax.barh(y, vals, height=0.55, color=BAR_COLOR_SCORE, alpha=0.95)
    xmax = max(vals) * 1.15 if vals else 1
    ax.set_xlim(0, xmax)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontproperties=_font(8))
    ax.set_xlabel("POI 数量", fontproperties=_font(8))
    ax.set_title("500m POI 结构", fontproperties=_font(10), pad=8)
    for i, v in enumerate(vals):
        ax.text(v + xmax * 0.02, i, str(v), va="center", fontsize=7)
    ax.invert_yaxis()
    fig.subplots_adjust(left=0.32, right=0.92, top=0.90, bottom=0.12)
    return _save(fig, path)


def _chart_competition_compare(features: dict, path: Path) -> Optional[Path]:
    labels = ["300m", "500m"]
    direct = [features.get("tea_count_300m", 0), features.get("tea_count_500m", 0)]
    indirect = [features.get("indirect_count_300m", 0), features.get("indirect_count_500m", 0)]
    if sum(direct) + sum(indirect) == 0:
        return None

    fig, ax = plt.subplots(figsize=(3.8, 2.5))
    _prep_ax(ax)
    x = np.arange(len(labels))
    w = 0.22
    ax.bar(x - w / 2, direct, w, label="直接茶饮", color=BAR_COLOR_SCORE, zorder=3)
    ax.bar(x + w / 2, indirect, w, label="间接饮品", color=BAR_COLOR_MAX, zorder=3)
    ymax = max(direct + indirect + [1]) * 1.25
    ax.set_ylim(0, ymax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontproperties=_font(8))
    ax.set_ylabel("家数", fontproperties=_font(8))
    ax.set_title("直接茶饮 vs 间接饮品", fontproperties=_font(9), pad=8)
    for i, v in enumerate(direct):
        if v:
            ax.text(i - w / 2, v + ymax * 0.03, str(v), ha="center", va="bottom", fontsize=7)
    for i, v in enumerate(indirect):
        if v:
            ax.text(i + w / 2, v + ymax * 0.03, str(v), ha="center", va="bottom", fontsize=7)
    _legend_below(ax, ncol=2)
    fig.subplots_adjust(left=0.14, right=0.96, top=0.80, bottom=0.28)
    return _save(fig, path)


def _chart_distance_bands(features: dict, path: Path) -> Optional[Path]:
    an = features.get("analytics") or {}
    bands = an.get("distance_bands_300") or {}
    if not bands or sum(bands.values()) == 0:
        return None
    labels = list(bands.keys())
    vals = [bands[k] for k in labels]
    fig, ax = plt.subplots(figsize=(3.8, 2.5))
    _prep_ax(ax)
    x = np.arange(len(labels))
    ax.bar(x, vals, width=0.45, color=BAR_COLOR_SCORE, alpha=0.95)
    ymax = max(vals + [1]) * 1.22
    ax.set_ylim(0, ymax)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontproperties=_font(7))
    ax.set_ylabel("家数", fontproperties=_font(8))
    ax.set_title("300m 竞品距离分布", fontproperties=_font(9), pad=8)
    for i, v in enumerate(vals):
        ax.text(i, v + ymax * 0.03, str(v), ha="center", va="bottom", fontsize=7)
    fig.subplots_adjust(left=0.14, right=0.96, top=0.80, bottom=0.22)
    return _save(fig, path)
