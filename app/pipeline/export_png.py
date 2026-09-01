"""PNG analysis map export — Amap basemap + analysis layers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import matplotlib.patches as mpatches

from app.pipeline.map_common import (
    COLOR_TEA_FAR,
    COLOR_TEA_NEAR,
    MapLayerContext,
    RADIUS_STYLES,
    build_map_context,
    radius_deg,
)


def render_analysis_png(
    features: dict,
    output_path: Path,
    amap_key: Optional[str] = None,
    ctx: Optional[MapLayerContext] = None,
) -> Tuple[Path, str, bool]:
    if ctx is None:
        ctx = build_map_context(features, amap_key)

    fig, ax = plt.subplots(figsize=(10, 10), dpi=120)
    ax.set_aspect("equal")

    if ctx.basemap_image is not None:
        ax.imshow(ctx.basemap_image, extent=ctx.extent, aspect="equal", zorder=0, alpha=0.95)

    for radius, fill, edge, lw in RADIUS_STYLES:
        deg = radius_deg(radius, ctx.cos_lat)
        ax.add_patch(
            Circle(
                (ctx.lng, ctx.lat), deg, fill=True, facecolor=fill, edgecolor=edge,
                linewidth=lw, alpha=0.35, zorder=radius // 200,
            )
        )
        ax.add_patch(
            Circle(
                (ctx.lng, ctx.lat), deg, fill=False, edgecolor=edge, linewidth=lw,
                zorder=radius // 200 + 0.1,
            )
        )

    for slng, slat in ctx.tea_near:
        ax.plot(
            slng, slat, "o", color=COLOR_TEA_NEAR, markersize=9,
            markeredgecolor="#212529", markeredgewidth=1.2, zorder=6,
        )
    for slng, slat in ctx.tea_other:
        ax.plot(
            slng, slat, "o", color=COLOR_TEA_FAR, markersize=6,
            markeredgecolor="white", markeredgewidth=0.6, zorder=6,
        )
    for ilng, ilat in ctx.indirect:
        ax.plot(
            ilng, ilat, "^", color="#F08C00", markersize=7,
            markeredgecolor="#212529", markeredgewidth=0.7, zorder=6,
        )
    for tlng, tlat in ctx.transit:
        ax.plot(
            tlng, tlat, "s", color="#20C997", markersize=6.5,
            markeredgecolor="#212529", markeredgewidth=0.8, zorder=6,
        )

    ax.plot(
        ctx.lng, ctx.lat, "*", color="#E03131", markersize=22,
        markeredgecolor="#212529", markeredgewidth=1.0, zorder=7,
    )

    ax.set_xlim(ctx.extent[0], ctx.extent[1])
    ax.set_ylim(ctx.extent[2], ctx.extent[3])

    ax.set_title(ctx.title, fontsize=13, fontweight="bold", fontproperties=_font(), pad=12)

    legend_handles = [
        mpatches.Patch(facecolor="#FFE3E3", edgecolor="#FA5252", label="300m 核心竞争圈"),
        mpatches.Patch(facecolor="#FFE8CC", edgecolor="#FFA94D", label="500m 日常消费圈"),
        mpatches.Patch(facecolor="#FFF3BF", edgecolor="#FFD43B", label="1000m 扩展圈"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=COLOR_TEA_NEAR, markersize=8,
                   label="直接茶饮（近场高亮）"),
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=COLOR_TEA_FAR, markersize=7,
                   label="直接茶饮（其他）"),
        plt.Line2D([0], [0], marker="^", color="w", markerfacecolor="#F08C00", markersize=7,
                   label="间接饮品（咖啡/果汁）"),
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor="#20C997", markersize=6.5, label="交通站点"),
        plt.Line2D([0], [0], marker="*", color="w", markerfacecolor="#E03131", markersize=14, label="候选点"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=7.5, prop=_font(), framealpha=0.92)

    _draw_north_arrow(ax)
    _draw_scale_bar(ax, ctx)

    note = ctx.basemap_note + " · 半径圆为查询半径，非步行等时圈"
    ax.annotate(
        note, xy=(0.02, 0.02), xycoords="axes fraction", fontsize=7, color="#495057",
        fontproperties=_font(),
    )
    ax.set_xlabel("经度", fontproperties=_font(), fontsize=9)
    ax.set_ylabel("纬度", fontproperties=_font(), fontsize=9)
    ax.tick_params(labelsize=8)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight", dpi=120)
    plt.close(fig)
    return output_path, ctx.basemap_note, ctx.basemap_ok


def _draw_north_arrow(ax) -> None:
    ax.annotate(
        "N", xy=(0.96, 0.22), xytext=(0.96, 0.12), xycoords="axes fraction",
        fontsize=11, fontweight="bold", ha="center", va="center",
        arrowprops=dict(arrowstyle="-|>", color="#212529", lw=1.5),
    )


def _draw_scale_bar(ax, ctx) -> None:
    from app.pipeline.map_common import METERS_PER_DEG_LAT

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    bar_m = 200
    ddeg = bar_m / (METERS_PER_DEG_LAT * ctx.cos_lat)
    x0 = xlim[0] + (xlim[1] - xlim[0]) * 0.05
    y0 = ylim[0] + (ylim[1] - ylim[0]) * 0.06
    ax.plot([x0, x0 + ddeg], [y0, y0], color="#212529", linewidth=3, solid_capstyle="butt", zorder=8)
    ax.text(x0 + ddeg / 2, y0 + (ylim[1] - ylim[0]) * 0.012, "200m", ha="center", fontsize=7, color="#212529")


def _font():
    from matplotlib.font_manager import FontProperties
    for name in ("Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"):
        try:
            return FontProperties(family=name)
        except Exception:
            continue
    from matplotlib.font_manager import FontProperties
    return FontProperties()
