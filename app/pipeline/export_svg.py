"""Layered SVG export for Illustrator editing."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Optional

from app.pipeline.map_common import (
    COLOR_TEA_FAR,
    COLOR_TEA_NEAR,
    MapLayerContext,
    RADIUS_STYLES,
    build_map_context,
    geo_to_pixel,
    image_to_data_uri,
    meters_to_pixel,
)

MAP_W = 1000
MAP_H = 1000
PAD_TOP = 56
PAD_RIGHT = 210
SVG_W = MAP_W + PAD_RIGHT
SVG_H = MAP_H + PAD_TOP + 36

SVG_ROOT_ATTRS = (
    'xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)


def render_analysis_svg(
    features: dict,
    output_path: Path,
    amap_key: Optional[str] = None,
    ctx: Optional[MapLayerContext] = None,
    basemap_override: Optional[tuple[Any, str]] = None,
) -> Path:
    if ctx is None:
        ctx = build_map_context(features, amap_key, basemap_override=basemap_override)
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg {SVG_ROOT_ATTRS} width="{SVG_W}" height="{SVG_H}" '
        f'viewBox="0 0 {SVG_W} {SVG_H}">',
        f'<title>{html.escape(ctx.title)}</title>',
        _group_basemap(ctx),
        _group_radius(ctx, 1000, "radius_1000"),
        _group_radius(ctx, 500, "radius_500"),
        _group_radius(ctx, 300, "radius_300"),
        _group_points(ctx.tea_near, ctx, "tea_direct_near", COLOR_TEA_NEAR, 7),
        _group_points(ctx.tea_other, ctx, "tea_direct_other", COLOR_TEA_FAR, 5),
        _group_markers(ctx.indirect, ctx, "tea_indirect", "#F08C00", "triangle", 5.5),
        _group_markers(ctx.transit, ctx, "transit", "#20C997", "square", 5.5),
        _group_site(ctx),
        _group_legend(),
        _defs_arrow(),
        _group_annotations(ctx),
        "</svg>",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(parts), encoding="utf-8")
    return output_path


def _map_offset() -> tuple[float, float]:
    return 0.0, float(PAD_TOP)


def _to_px(lng: float, lat: float, ctx: MapLayerContext) -> tuple[float, float]:
    ox, oy = _map_offset()
    x, y = geo_to_pixel(lng, lat, ctx.extent, MAP_W, MAP_H)
    return ox + x, oy + y


def _group_basemap(ctx: MapLayerContext) -> str:
    ox, oy = _map_offset()
    if ctx.basemap_data_uri:
        href = ctx.basemap_data_uri.replace('"', "%22")
        return (
            f'<g id="basemap">'
            f'<image xlink:href="{href}" href="{href}" '
            f'x="{ox:.2f}" y="{oy:.2f}" width="{MAP_W}" height="{MAP_H}" '
            f'preserveAspectRatio="xMidYMid meet"/>'
            f"</g>"
        )
    if ctx.basemap_image is not None:
        from PIL import Image

        from app.pipeline.map_common import image_to_data_uri

        thumb = ctx.basemap_image.resize((MAP_W, MAP_H), Image.LANCZOS)
        href = image_to_data_uri(thumb, fmt="JPEG")
        return (
            f'<g id="basemap">'
            f'<image xlink:href="{href}" href="{href}" '
            f'x="{ox:.2f}" y="{oy:.2f}" width="{MAP_W}" height="{MAP_H}" '
            f'preserveAspectRatio="xMidYMid meet"/>'
            f"</g>"
        )
    return (
        f'<g id="basemap">'
        f'<rect x="{ox:.2f}" y="{oy:.2f}" width="{MAP_W}" height="{MAP_H}" fill="#f1f3f5"/>'
        f"</g>"
    )


def _group_radius(ctx: MapLayerContext, radius_m: int, gid: str) -> str:
    style = next(s for s in RADIUS_STYLES if s[0] == radius_m)
    _, fill, stroke, lw = style
    cx, cy = _to_px(ctx.lng, ctx.lat, ctx)
    r_px = meters_to_pixel(radius_m, ctx.extent, ctx.cos_lat, MAP_W)
    return (
        f'<g id="{gid}">'
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_px:.2f}" '
        f'fill="{fill}" fill-opacity="0.35" stroke="{stroke}" stroke-width="{lw}"/>'
        f"</g>"
    )


def _group_points(
    pts: list[tuple[float, float]], ctx: MapLayerContext, gid: str, color: str, r: float
) -> str:
    circles = []
    for lng, lat in pts:
        x, y = _to_px(lng, lat, ctx)
        circles.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r}" fill="{color}" '
            f'stroke="#212529" stroke-width="0.8"/>'
        )
    inner = "\n".join(circles) if circles else "<!-- empty -->"
    return f'<g id="{gid}">\n{inner}\n</g>'


def _group_markers(
    pts: list[tuple[float, float]],
    ctx: MapLayerContext,
    gid: str,
    color: str,
    shape: str,
    size: float,
) -> str:
    items = []
    for lng, lat in pts:
        x, y = _to_px(lng, lat, ctx)
        if shape == "triangle":
            h = size * 1.2
            items.append(
                f'<polygon points="{x:.2f},{y - h:.2f} {x - size:.2f},{y + h * 0.6:.2f} '
                f'{x + size:.2f},{y + h * 0.6:.2f}" fill="{color}" stroke="#212529" stroke-width="0.7"/>'
            )
        else:
            items.append(
                f'<rect x="{x - size:.2f}" y="{y - size:.2f}" width="{size * 2:.2f}" height="{size * 2:.2f}" '
                f'fill="{color}" stroke="#212529" stroke-width="0.8"/>'
            )
    inner = "\n".join(items) if items else "<!-- empty -->"
    return f'<g id="{gid}">\n{inner}\n</g>'


def _star_points(cx: float, cy: float, outer: float, inner: float) -> str:
    pts = []
    for i in range(16):
        ang = math.pi / 2 + i * math.pi / 8
        r = outer if i % 2 == 0 else inner
        pts.append(f"{cx + r * math.cos(ang):.2f},{cy - r * math.sin(ang):.2f}")
    return " ".join(pts)


def _group_site(ctx: MapLayerContext) -> str:
    x, y = _to_px(ctx.lng, ctx.lat, ctx)
    return (
        f'<g id="site_point">'
        f'<polygon points="{_star_points(x, y, 14, 6)}" fill="{COLOR_TEA_NEAR}" '
        f'stroke="#212529" stroke-width="1"/>'
        f"</g>"
    )


def _legend_icon(x: float, y: float, kind: str, fill: str, stroke: str) -> str:
    cy = y - 3
    if kind == "ring":
        return (
            f'<circle cx="{x + 7:.2f}" cy="{cy:.2f}" r="6.5" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.2"/>'
        )
    if kind == "circle":
        return (
            f'<circle cx="{x + 7:.2f}" cy="{cy:.2f}" r="5" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.9"/>'
        )
    if kind == "circle_sm":
        return (
            f'<circle cx="{x + 7:.2f}" cy="{cy:.2f}" r="4" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.8"/>'
        )
    if kind == "triangle":
        return (
            f'<polygon points="{x + 7:.2f},{cy - 6:.2f} {x + 1:.2f},{cy + 5:.2f} '
            f'{x + 12.8:.2f},{cy + 5:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>'
        )
    if kind == "square":
        return (
            f'<rect x="{x + 1:.2f}" y="{cy - 6:.2f}" width="11.6" height="11.6" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="0.8"/>'
        )
    if kind == "star":
        return (
            f'<polygon points="{_star_points(x + 7, cy, 6.5, 3)}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.8"/>'
        )
    return ""


def _group_legend() -> str:
    x0, y0 = MAP_W + 12, PAD_TOP + 8
    rows = [
        ("ring", "#FFE3E3", "#FA5252", "300m 核心竞争圈"),
        ("ring", "#FFE8CC", "#FFA94D", "500m 日常消费圈"),
        ("ring", "#FFF3BF", "#FFD43B", "1000m 扩展圈"),
        ("circle", COLOR_TEA_NEAR, "#212529", "直接茶饮（近场）"),
        ("circle_sm", COLOR_TEA_FAR, "#212529", "直接茶饮（其他）"),
        ("triangle", "#F08C00", "#212529", "间接饮品"),
        ("square", "#20C997", "#212529", "交通站点"),
        ("star", COLOR_TEA_NEAR, "#212529", "候选点"),
    ]
    lines = [
        '<g id="legend">',
        f'<text x="{x0}" y="{y0}" font-size="11" font-family="Microsoft YaHei,sans-serif" font-weight="bold">图例</text>',
    ]
    y = y0 + 18
    for kind, fill, stroke, label in rows:
        lines.append(_legend_icon(x0, y, kind, fill, stroke))
        lines.append(
            f'<text x="{x0 + 20}" y="{y}" font-size="9" '
            f'font-family="Microsoft YaHei,sans-serif">{html.escape(label)}</text>'
        )
        y += 20
    lines.append("</g>")
    return "\n".join(lines)


def _defs_arrow() -> str:
    return """<defs>
  <marker id="arrowN" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
    <path d="M0,0 L6,3 L0,6 Z" fill="#212529"/>
  </marker>
</defs>"""


def _group_annotations(ctx: MapLayerContext) -> str:
    note = ctx.basemap_note + " · 半径圆为查询半径，非步行等时圈"
    ox, oy = _map_offset()
    bar_px = meters_to_pixel(200, ctx.extent, ctx.cos_lat, MAP_W)
    x0 = ox + MAP_W * 0.05
    y0 = oy + MAP_H * 0.94
    return f'''<g id="annotations">
  <text x="{SVG_W / 2}" y="28" text-anchor="middle" font-size="16" font-weight="bold" font-family="Microsoft YaHei,sans-serif">{html.escape(ctx.title)}</text>
  <text x="{ox + 8}" y="{oy + MAP_H - 8}" font-size="8" font-family="Microsoft YaHei,sans-serif" fill="#495057">{html.escape(note)}</text>
  <line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x0 + bar_px:.2f}" y2="{y0:.2f}" stroke="#212529" stroke-width="3"/>
  <text x="{x0 + bar_px / 2:.2f}" y="{y0 + 14:.2f}" text-anchor="middle" font-size="8" font-family="Microsoft YaHei,sans-serif">200m</text>
  <text x="{ox + MAP_W * 0.96:.2f}" y="{oy + MAP_H * 0.78:.2f}" font-size="12" font-weight="bold" font-family="Microsoft YaHei,sans-serif">N</text>
  <line x1="{ox + MAP_W * 0.96:.2f}" y1="{oy + MAP_H * 0.82:.2f}" x2="{ox + MAP_W * 0.96:.2f}" y2="{oy + MAP_H * 0.88:.2f}" stroke="#212529" stroke-width="1.5" marker-end="url(#arrowN)"/>
</g>'''
