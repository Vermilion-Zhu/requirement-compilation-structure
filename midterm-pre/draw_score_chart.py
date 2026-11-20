"""Draw a sample score/version chart from the parsed ArcBench history.

The final report wants correctness against Runtime or Tokens.  The saved history HTML does
not include those fields, so this sample uses submission order as the x axis and total score
as y.  Replace the x values once the submission-details export is available.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import analyze_submissions

SCALE = 2
WIDTH, HEIGHT = 1800, 1050

INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"
STAGED = "#d97706"
LITE = "#0f766e"
UNKNOWN = "#6b7280"
PANEL = "#ffffff"

SHORT = {
    "First Deployable Agent": "First",
    "Full-hooked and E2E Enhanced": "Hooks+E2E",
    "Nowicthelight": "Nowic",
    "Baseline Test": "Baseline",
    "Semantics Enhanced": "Semantics 7.33",
    "UI Naming 20261107": "UI Naming",
    "GYP No.1": "GYP",
    "Full-hooked 20261107 dzs": "Hooks 0.34",
    "IR amended 20261109 zmr": "IR",
    "Breadcrumb-fixed 20261111 zmr": "Breadcrumb 13.35",
    "Entry Route and Probes 20261113 zmr": "EntryRoute 3.55",
    "Light 20261115 dzs": "Light 8.29",
    "Lite Log Preview 20261116 dzs": "05b 15.67",
    "Lite Bounded 20261115 dzs": "Bounded 89.59",
    "Lite 05b Log Preview 20261116 dzs": "05b 5.80",
    "Lite Workflow Groups 20261118 dzs": "Workflow 6.09",
    "Lite History Search 20261119 dzs": "History 5.83",
    "Lite 05c Log Labels 20261119 dzs": "05c 7.14",
    "Lite 07a Input Hints 20261120 dzs": "07a 8.84",
    "Lite 07b Input Hints and Obligations 20261120 dzs": "07b 7.20",
}

KEY_LITE = ("Semantics", "Breadcrumb", "EntryRoute", "Light", "05b")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size * SCALE)


def text(draw, xy, value, size=18, bold=False, fill=INK, anchor="la"):
    draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def arrow(draw, start, end, color="#94a3b8", width=2):
    draw.line([start, end], fill=color, width=width * SCALE)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    length = 12 * SCALE
    for delta in (math.radians(25), -math.radians(25)):
        point = (end[0] - length * math.cos(angle + delta),
                 end[1] - length * math.sin(angle + delta))
        draw.line([end, point], fill=color, width=width * SCALE)


def phase_color(row):
    if row["release_version"].startswith("0.1.0") or row["version"].startswith(("Lite", "Light")):
        return LITE
    if row["version"]:
        return STAGED
    return UNKNOWN


def label_for(row):
    return SHORT.get(row["name"], (row["version"] or row["name"])[:20])


def draw_panel(draw, rows, box, title, y_max, label_all=False, key_labels=()):
    left, top, right, bottom = [value * SCALE for value in box]
    rounded(draw, (left, top, right, bottom), 18 * SCALE, PANEL, "#e2e8f0", 1 * SCALE)
    text(draw, ((left + right) / 2, top + 24 * SCALE), title, 24, True, INK, "ma")

    plot = (left + 70 * SCALE, top + 90 * SCALE, right - 30 * SCALE, bottom - 110 * SCALE)
    plot_left, plot_top, plot_right, plot_bottom = plot
    ticks = 4 if y_max <= 16 else 5
    for index in range(ticks + 1):
        value = y_max * index / ticks
        y = plot_bottom - (plot_bottom - plot_top) * index / ticks
        draw.line([(plot_left, y), (plot_right, y)], fill=GRID, width=1 * SCALE)
        text(draw, (plot_left - 16 * SCALE, y), f"{value:g}", 16, False, MUTED, "rm")
    draw.line([(plot_left, plot_top), (plot_left, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
    draw.line([(plot_left, plot_bottom), (plot_right, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
    text(draw, ((plot_left + plot_right) / 2, plot_bottom + 34 * SCALE),
         "提交顺序（按时间；最终替换为 Runtime 或 Tokens）", 15, False, MUTED, "ma")

    if not rows:
        text(draw, ((plot_left + plot_right) / 2, (plot_top + plot_bottom) / 2), "无有效提交", 20, False, MUTED, "mm")
        return
    step = (plot_right - plot_left) / max(len(rows), 2)
    points = []
    for index, row in enumerate(rows):
        x = plot_left + step * (index + 0.5)
        y = plot_bottom - (plot_bottom - plot_top) * min(row["score"], y_max) / y_max
        points.append((x, y, row))

    for previous, current in zip(points, points[1:]):
        arrow(draw, previous[:2], current[:2])

    for index, (x, y, row) in enumerate(points):
        color = phase_color(row)
        radius = 10 * SCALE
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color,
            outline="white", width=2 * SCALE)
        label = label_for(row)
        should_label = label_all or index == 0 or any(key in label for key in key_labels)
        if should_label:
            offset = -34 * SCALE if y - 34 * SCALE > plot_top + 8 * SCALE else 22 * SCALE
            text(draw, (x, y + offset), label, 14, False, INK, "ma")


def main():
    rows = [row for row in analyze_submissions.build_rows() if not row["excluded"]]
    web = [row for row in rows if row["competition"] == "web"]
    lite = [row for row in rows if row["competition"] == "lite"]

    image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), "#f8fafc")
    draw = ImageDraw.Draw(image)
    text(draw, (60 * SCALE, 46 * SCALE), "ArcBench 提交记录：分数与版本迭代（样图）", 34, True)
    text(draw, (60 * SCALE, 98 * SCALE),
         "数据来自保存的历史页；零分提交已排除；X 轴为提交顺序，最终图将替换为 Runtime 或 Tokens", 18, False, MUTED)
    text(draw, (60 * SCALE, 130 * SCALE),
         "橙色 = 十三阶段（staged）  ·  青色 = Lite ReAct  ·  灰色 = 版本未知/待补  ·  箭头 = 相邻版本", 16, False, MUTED)

    draw_panel(draw, web, (50, 175, 875, 980), "Web 全量任务（分数 0–100）", 100, label_all=True)
    draw_panel(draw, lite, (925, 175, 1750, 980), "Lite 任务（分数 0–16）", 16, key_labels=KEY_LITE)

    text(draw, (300 * SCALE, 250 * SCALE), "Bounded 89.59 为异常高值，需核对当期任务集/评分口径", 15, False,
         "#b45309")
    text(draw, (60 * SCALE, 1000 * SCALE),
         "数据缺口：Runtime、Tokens、每任务 Tests% 不在保存的 HTML 中；详见 submission-data-analysis.md。", 15, False, MUTED)

    output = Path(__file__).with_name("charts") / "score_trend_sample.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.resize((WIDTH, HEIGHT), Image.LANCZOS).save(output)
    print(output)


if __name__ == "__main__":
    main()
