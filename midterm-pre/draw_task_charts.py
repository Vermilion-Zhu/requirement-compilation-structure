"""Charts for per-task correctness against runtime/tokens.

The saved detail files contain the per-task run results, so the old score-only sample can now
be replaced with the requested charts.  All observed points are drawn; unknown-version
submissions use a grey marker and the submission name as their label.

Usage:
  python midterm-pre/draw_task_charts.py
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import analyze_submissions
import parse_details

SCALE = 2
INK = "#0f172a"
MUTED = "#64748b"
GRID = "#e2e8f0"
STAGED = "#d97706"
LITE = "#0f766e"
UNKNOWN = "#6b7280"
PANEL = "#ffffff"
PANEL_LINE = "#e2e8f0"

SHORT = {
    "Lite Bounded 20261115 dzs": "Bounded",
    "Lite 05b Log Preview 20261116 dzs": "05b",
    "Lite Workflow Groups 20261118 dzs": "Workflow",
    "Lite History Search 20261119 dzs": "History",
    "Lite 05c Log Labels 20261119 dzs": "05c",
    "Lite 07a Input Hints 20261120 dzs": "07a",
    "Lite 07b Input Hints and Obligations 20261120 dzs": "07b",
    "First Deployable Agent": "First",
    "Full-hooked and E2E Enhanced": "Hooks+E2E",
    "Nowicthelight": "Nowic",
    "Baseline Test": "Baseline",
    "Semantics Enhanced": "Semantics",
    "UI Naming 20261107": "UI Naming",
    "GYP No.1": "GYP",
    "Full-hooked 20261107 dzs": "Hooks",
    "IR amended 20261109 zmr": "IR",
    "Breadcrumb-fixed 20261111 zmr": "Breadcrumb",
    "Entry Route and Probes 20261113 zmr": "M8-M10",
    "Light 20261115 dzs": "Light",
    "Lite Log Preview 20261116 dzs": "05b",
}
TASKS = {
    "bookstack": "BookStack knowledge base",
    "keep": "Keep personal note management",
    "stackoverflow": "Stack Overflow developer knowledge sharing",
    "12306": "12306 railway travel",
    "ctrip": "Ctrip travel services",
    "prestashop": "PrestaShop B2C storefront",
}


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
    length = 11 * SCALE
    for delta in (math.radians(24), -math.radians(24)):
        point = (end[0] - length * math.cos(angle + delta),
                 end[1] - length * math.sin(angle + delta))
        draw.line([end, point], fill=color, width=width * SCALE)


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y/%m/%d %H:%M:%S")


def points_for(rows, task_key):
    task = TASKS[task_key]
    points = []
    for row in rows:
        item = next((entry for entry in row["tasks"] if entry["task"] == task and entry["run"]), None)
        if item and item.get("runtime_s") and item.get("tokens"):
            points.append({**row, "task_result": item})
    return sorted(points, key=lambda item: parse_date(item["date"]))


def phase_color(row):
    if row["release_version"].startswith("0.1.0") or row["version"].startswith(("Lite", "Light")):
        return LITE
    if row["version"]:
        return STAGED
    return UNKNOWN


def label(row):
    if row["version"] in SHORT:
        return SHORT[row["version"]]
    return SHORT.get(row["name"], (row["version"] or row["name"])[:14])


def format_minutes(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 60:.0f}m"


def format_tokens(tokens: float) -> str:
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    if tokens >= 1_000:
        return f"{tokens / 1_000:.0f}K"
    return f"{tokens:.0f}"


def log_ticks(values, formatter):
    values = [value for value in values if value and value > 0]
    if not values:
        return []
    low, high = min(values), max(values)
    ticks = []
    for power in range(-2, 10):
        base = 10 ** power
        for factor in (1, 2, 5):
            value = factor * base
            if low * 0.85 <= value <= high * 1.2:
                ticks.append(value)
    return sorted(set(ticks))


KEY_LABELS = {
    "BookStack · Web": {"07a", "Bounded", "05c", "07b", "05b", "History", "Workflow"},
    "BookStack · Lite": {"Light", "05b", "Breadcrumb", "Semantics", "IR", "Hooks+E2E", "Baseline", "First"},
    "Keep · Web": {"Bounded"},
    "Keep · Lite": {"UI Naming", "GYP", "IR", "Breadcrumb", "M8-M10", "Hooks", "05b"},
}


def place_label(draw, x, y, value, plot, occupied):
    plot_left, plot_top, plot_right, plot_bottom = plot
    attempts = [(0, -28, "ma"), (0, 20, "ma"), (-34, -28, "la"), (34, -28, "ra"),
        (-34, 20, "la"), (34, 20, "ra"), (0, -46, "ma"), (0, 38, "ma")]
    for dx, dy, anchor in attempts:
        lx, ly = x + dx * SCALE, y + dy * SCALE
        box = draw.textbbox((lx, ly), value, font=font(13), anchor=anchor)
        if box[0] < plot_left + 2 or box[2] > plot_right - 2 or box[1] < plot_top + 2 or box[3] > plot_bottom - 2:
            continue
        if any(not (box[2] < other[0] or box[0] > other[2] or box[3] < other[1] or box[1] > other[3])
                for other in occupied):
            continue
        draw.text((lx, ly), value, font=font(13), fill=INK, anchor=anchor)
        occupied.append(box)
        return


def draw_panel(draw, box, title, points, x_key, x_label, x_range, tick_formatter, y_label="Tests%"):
    left, top, right, bottom = [value * SCALE for value in box]
    rounded(draw, (left, top, right, bottom), 16 * SCALE, PANEL, PANEL_LINE, 1 * SCALE)
    text(draw, ((left + right) / 2, top + 22 * SCALE), title, 22, True, INK, "ma")

    plot = (left + 70 * SCALE, top + 82 * SCALE, right - 26 * SCALE, bottom - 88 * SCALE)
    plot_left, plot_top, plot_right, plot_bottom = plot
    for index in range(5):
        value = index * 25
        y = plot_bottom - (plot_bottom - plot_top) * index / 4
        draw.line([(plot_left, y), (plot_right, y)], fill=GRID, width=1 * SCALE)
        text(draw, (plot_left - 14 * SCALE, y), f"{value}%", 15, False, MUTED, "rm")
    draw.line([(plot_left, plot_top), (plot_left, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
    draw.line([(plot_left, plot_bottom), (plot_right, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
    text(draw, ((plot_left + plot_right) / 2, plot_bottom + 32 * SCALE), x_label, 15, False, MUTED, "ma")

    if not points:
        text(draw, ((plot_left + plot_right) / 2, (plot_top + plot_bottom) / 2), "该任务无运行记录", 18, False, MUTED, "mm")
        return

    low, high = x_range
    log_low, log_high = math.log10(low), math.log10(high)
    occupied = []
    for value in log_ticks([point["task_result"][x_key] for point in points], tick_formatter):
        x = plot_left + (math.log10(value) - log_low) / (log_high - log_low) * (plot_right - plot_left)
        if plot_left <= x <= plot_right:
            draw.line([(x, plot_top), (x, plot_bottom)], fill=GRID, width=1 * SCALE)
            text(draw, (x, plot_bottom + 12 * SCALE), tick_formatter(value), 13, False, MUTED, "ma")

    anchors = []
    for point in points:
        value = point["task_result"][x_key]
        x = plot_left + (math.log10(value) - log_low) / (log_high - log_low) * (plot_right - plot_left)
        y = plot_bottom - (plot_bottom - plot_top) * min(point["task_result"]["tests_pct"], 100) / 100
        anchors.append((x, y, point))

    for previous, current in zip(anchors, anchors[1:]):
        arrow(draw, previous[:2], current[:2])

    for index, (x, y, point) in enumerate(anchors):
        radius = 9 * SCALE
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=phase_color(point),
            outline="white", width=2 * SCALE)
        value = label(point)
        if value in KEY_LABELS.get(title, set()) or len(anchors) == 1:
            place_label(draw, x, y, value, plot, occupied)

    # 100% reference
    hundred = plot_bottom - (plot_bottom - plot_top)
    draw.line([(plot_left, hundred), (plot_right, hundred)], fill="#94a3b8", width=1 * SCALE)


def draw_grid(panels, x_key, x_label, title, output, tick_formatter):
    width, height = 1800, 1100
    image = Image.new("RGB", (width * SCALE, height * SCALE), "#f8fafc")
    draw = ImageDraw.Draw(image)
    text(draw, (55 * SCALE, 38 * SCALE), title, 32, True)
    text(draw, (55 * SCALE, 86 * SCALE),
         "Y = 外部测试通过率（Tests%）；X 取对数；箭头连接同一任务的相邻版本；灰色 = 版本未知", 17, False, MUTED)
    text(draw, (55 * SCALE, 115 * SCALE),
         "分任务、分竞赛比较；跨竞赛的任务需求/测试数不同，不能直接横比", 15, False, MUTED)

    all_values = [point["task_result"][x_key] for _, points in panels for point in points if point["task_result"][x_key]]
    ticks = log_ticks(all_values, tick_formatter)
    if all_values:
        low, high = min(all_values) * 0.8, max(all_values) * 1.25
    else:
        low, high = 1, 10
    for index, (panel_title, points) in enumerate(panels):
        column, row = index % 2, index // 2
        box = (45 + column * 880, 165 + row * 455, 875 + column * 880, 585 + row * 455)
        draw_panel(draw, box, panel_title, points, x_key, x_label, (low, high), tick_formatter)

    text(draw, (55 * SCALE, 1055 * SCALE),
         "数据：web_score_details.txt / lite_score_detail.txt；同一任务只画实际运行过的提交。", 14, False, MUTED)

    image.resize((width, height), Image.LANCZOS).save(output)
    print(output)


def draw_trend(rows):
    """Tests% over version order, per task, for the two tasks with enough history."""
    width, height = 1800, 1000
    image = Image.new("RGB", (width * SCALE, height * SCALE), "#f8fafc")
    draw = ImageDraw.Draw(image)
    text(draw, (55 * SCALE, 38 * SCALE), "逐任务改进历史：Tests% 随版本变化", 32, True)
    text(draw, (55 * SCALE, 86 * SCALE),
         "X = 该任务实际运行过的提交（按时间）；箭头连接相邻提交；只用于看趋势，不比较不同任务", 16, False, MUTED)

    panels = [
        ("BookStack · Web", points_for([r for r in rows if r["competition"] == "web"], "bookstack")),
        ("BookStack · Lite", points_for([r for r in rows if r["competition"] == "lite"], "bookstack")),
        ("Keep · Web", points_for([r for r in rows if r["competition"] == "web"], "keep")),
        ("Keep · Lite", points_for([r for r in rows if r["competition"] == "lite"], "keep")),
    ]
    for index, (title, points) in enumerate(panels):
        column, row = index % 2, index // 2
        left, top = 45 + column * 880, 160 + row * 405
        right, bottom = 875 + column * 880, 535 + row * 405
        rounded(draw, (left * SCALE, top * SCALE, right * SCALE, bottom * SCALE), 16 * SCALE, PANEL, PANEL_LINE, 1 * SCALE)
        text(draw, ((left + right) / 2 * SCALE, (top + 24) * SCALE), title, 22, True, INK, "ma")
        plot = (left + 65, top + 75, right - 30, bottom - 65)
        plot_left, plot_top, plot_right, plot_bottom = [value * SCALE for value in plot]
        for index_y in range(5):
            value = index_y * 25
            y = plot_bottom - (plot_bottom - plot_top) * index_y / 4
            draw.line([(plot_left, y), (plot_right, y)], fill=GRID, width=1 * SCALE)
            text(draw, (plot_left - 12 * SCALE, y), f"{value}%", 14, False, MUTED, "rm")
        draw.line([(plot_left, plot_top), (plot_left, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
        draw.line([(plot_left, plot_bottom), (plot_right, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
        if not points:
            text(draw, ((plot_left + plot_right) / 2, (plot_top + plot_bottom) / 2), "无运行记录", 18, False, MUTED, "mm")
            continue
        step = (plot_right - plot_left) / max(len(points), 2)
        anchors = []
        for index_x, point in enumerate(points):
            x = plot_left + step * (index_x + 0.5)
            y = plot_bottom - (plot_bottom - plot_top) * point["task_result"]["tests_pct"] / 100
            anchors.append((x, y, point))
        for previous, current in zip(anchors, anchors[1:]):
            arrow(draw, previous[:2], current[:2])
        for index_x, (x, y, point) in enumerate(anchors):
            radius = 9 * SCALE
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=phase_color(point),
                outline="white", width=2 * SCALE)
            offset = -26 * SCALE if index_x % 2 == 0 else 18 * SCALE
            text(draw, (x, y + offset), label(point), 12, False, INK, "ma")

    output = Path(__file__).with_name("charts") / "task_tests_trend.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.resize((width, height), Image.LANCZOS).save(output)
    print(output)


def draw_coverage(rows):
    width, height = 1200, 760
    image = Image.new("RGB", (width * SCALE, height * SCALE), "#f8fafc")
    draw = ImageDraw.Draw(image)
    text(draw, (50 * SCALE, 40 * SCALE), "总分的“任务覆盖”陷阱", 30, True)
    text(draw, (50 * SCALE, 86 * SCALE),
         "只跑 1 个任务时，总分被 515/182 的总测试数稀释；逐任务比较才有意义", 16, False, MUTED)
    plot = (90 * SCALE, 160 * SCALE, 1130 * SCALE, 640 * SCALE)
    plot_left, plot_top, plot_right, plot_bottom = plot
    for index in range(6):
        value = index * 20
        y = plot_bottom - (plot_bottom - plot_top) * index / 5
        draw.line([(plot_left, y), (plot_right, y)], fill=GRID, width=1 * SCALE)
        text(draw, (plot_left - 14 * SCALE, y), f"{value}", 15, False, MUTED, "rm")
    draw.line([(plot_left, plot_top), (plot_left, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
    draw.line([(plot_left, plot_bottom), (plot_right, plot_bottom)], fill="#cbd5e1", width=1 * SCALE)
    for count in range(1, 7):
        x = plot_left + (count - 0.5) / 6 * (plot_right - plot_left)
        text(draw, (x, plot_bottom + 8 * SCALE), str(count), 14, False, MUTED, "ma")
    text(draw, ((plot_left + plot_right) / 2, plot_bottom + 40 * SCALE), "本次提交实际运行的任务数（共 6 个）", 16, False, MUTED, "ma")
    text(draw, (plot_left - 46 * SCALE, (plot_top + plot_bottom) / 2), "总分", 16, False, MUTED, "mm")
    buckets = {}
    for row in rows:
        run_count = sum(1 for task in row["tasks"] if task["run"])
        buckets.setdefault(run_count, []).append(row)
    for run_count, bucket in buckets.items():
        for position, row in enumerate(bucket):
            offset = (position - (len(bucket) - 1) / 2) * 0.12 if len(bucket) > 1 else 0
            x = plot_left + (run_count - 0.5 + offset) / 6 * (plot_right - plot_left)
            y = plot_bottom - (plot_bottom - plot_top) * min(row["score"], 100) / 100
            color = LITE if row["competition"] == "web" else STAGED
            draw.ellipse((x - 8 * SCALE, y - 8 * SCALE, x + 8 * SCALE, y + 8 * SCALE), fill=color, outline="white", width=2 * SCALE)
            if row["name"] in ("Lite Bounded 20261115 dzs", "Lite Log Preview 20261116 dzs", "Breadcrumb-fixed 20261111 zmr", "Lite 07a Input Hints 20261120 dzs"):
                label = {"Lite Bounded 20261115 dzs": "Bounded", "Lite Log Preview 20261116 dzs": "05b", "Breadcrumb-fixed 20261111 zmr": "Breadcrumb", "Lite 07a Input Hints 20261120 dzs": "07a"}[row["name"]]
                text(draw, (x, y - 18 * SCALE), f"{label} {row['score']:.1f}", 13, False, INK, "ma")
    legend_y = 690 * SCALE
    draw.ellipse((70 * SCALE, legend_y - 8 * SCALE, 86 * SCALE, legend_y + 8 * SCALE), fill=LITE)
    text(draw, (96 * SCALE, legend_y), "Web", 14, False, MUTED, "lm")
    draw.ellipse((150 * SCALE, legend_y - 8 * SCALE, 166 * SCALE, legend_y + 8 * SCALE), fill=STAGED)
    text(draw, (176 * SCALE, legend_y), "Lite", 14, False, MUTED, "lm")
    output = Path(__file__).with_name("charts") / "overall_score_vs_coverage.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.resize((width, height), Image.LANCZOS).save(output)
    print(output)


def main():
    details = parse_details.build_details()
    charts = Path(__file__).with_name("charts")
    charts.mkdir(parents=True, exist_ok=True)

    panels = [
        ("BookStack · Web", points_for([r for r in details if r["competition"] == "web"], "bookstack")),
        ("BookStack · Lite", points_for([r for r in details if r["competition"] == "lite"], "bookstack")),
        ("Keep · Web", points_for([r for r in details if r["competition"] == "web"], "keep")),
        ("Keep · Lite", points_for([r for r in details if r["competition"] == "lite"], "keep")),
    ]
    draw_grid(panels, "runtime_s", "Runtime（对数轴）", "正确率 vs 运行时间：BookStack / Keep", charts / "tests_vs_runtime.png",
        format_minutes)
    draw_grid(panels, "tokens", "Tokens（对数轴）", "正确率 vs Token 消耗：BookStack / Keep", charts / "tests_vs_tokens.png",
        format_tokens)
    draw_trend(details)
    draw_coverage(details)


if __name__ == "__main__":
    main()
