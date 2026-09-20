#!/usr/bin/env python3
"""Render custom GitHub contribution cards from the public profile calendar."""

from __future__ import annotations

import argparse
import re
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from xml.sax.saxutils import escape

PROFILE = "pkmdev-sec"
CONTRIBUTIONS_URL = "https://github.com/users/{username}/contributions"


@dataclass(frozen=True)
class Contribution:
    day: date
    count: int
    level: int


@dataclass(frozen=True)
class Summary:
    total: int
    active_days: int
    longest_run: int
    first_day: date
    last_day: date


@dataclass(frozen=True)
class Layout:
    width: int
    height: int
    grid_x: int
    grid_y: int
    cell: int
    gap: int
    title_size: int
    subtitle_size: int
    summary_y: int
    grid_label_size: int
    mobile: bool = False


DESKTOP = Layout(
    width=1200,
    height=360,
    grid_x=96,
    grid_y=184,
    cell=14,
    gap=5,
    title_size=29,
    subtitle_size=12,
    summary_y=105,
    grid_label_size=10,
)

MOBILE = Layout(
    width=720,
    height=500,
    grid_x=72,
    grid_y=276,
    cell=8,
    gap=3,
    title_size=31,
    subtitle_size=11,
    summary_y=164,
    grid_label_size=9,
    mobile=True,
)

LEVEL_COLORS = ("#10281D", "#14532D", "#15803D", "#22C55E", "#86EFAC")


class ContributionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._days: dict[str, dict[str, object]] = {}
        self._tooltip_for: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "td" and values.get("data-date") and values.get("id"):
            self._days[values["id"]] = {
                "day": date.fromisoformat(values["data-date"]),
                "level": int(values.get("data-level") or 0),
                "count": 0,
            }
        elif tag == "tool-tip":
            self._tooltip_for = values.get("for")

    def handle_endtag(self, tag: str) -> None:
        if tag == "tool-tip":
            self._tooltip_for = None

    def handle_data(self, data: str) -> None:
        if not self._tooltip_for or self._tooltip_for not in self._days:
            return
        match = re.search(r"([\d,]+) contribution", data)
        if match:
            self._days[self._tooltip_for]["count"] = int(match.group(1).replace(",", ""))

    def contributions(self) -> list[Contribution]:
        return sorted(
            (
                Contribution(
                    day=value["day"],
                    count=int(value["count"]),
                    level=int(value["level"]),
                )
                for value in self._days.values()
            ),
            key=lambda item: item.day,
        )


def fetch_calendar(username: str) -> str:
    request = urllib.request.Request(
        CONTRIBUTIONS_URL.format(username=username),
        headers={"User-Agent": "pkmdev-profile-activity-renderer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_calendar(html: str) -> list[Contribution]:
    parser = ContributionParser()
    parser.feed(html)
    days = parser.contributions()
    if len(days) < 350:
        raise ValueError(f"Expected at least 350 contribution days, received {len(days)}")
    return days


def summarize(days: list[Contribution]) -> Summary:
    longest_run = 0
    current_run = 0
    for contribution in days:
        if contribution.count:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    return Summary(
        total=sum(item.count for item in days),
        active_days=sum(item.count > 0 for item in days),
        longest_run=longest_run,
        first_day=days[0].day,
        last_day=days[-1].day,
    )


def month_labels(days: list[Contribution]) -> list[tuple[int, str]]:
    start = days[0].day
    labels: list[tuple[int, str]] = []
    seen: set[tuple[int, int]] = set()
    for item in days:
        month = (item.day.year, item.day.month)
        if item.day.day > 7 or month in seen:
            continue
        seen.add(month)
        week = (item.day - start).days // 7
        labels.append((week, item.day.strftime("%b").upper()))
    return labels


def summary_cards(summary: Summary, layout: Layout) -> str:
    cards = (
        (f"{summary.total:,}", "CONTRIBUTIONS"),
        (str(summary.active_days), "ACTIVE DAYS"),
        (str(summary.longest_run), "LONGEST RUN"),
    )
    card_width = 178 if layout.mobile else 190
    card_gap = 14 if layout.mobile else 16
    total_width = len(cards) * card_width + (len(cards) - 1) * card_gap
    start_x = (layout.width - total_width) / 2 if layout.mobile else layout.width - total_width - 48
    value_size = 23 if layout.mobile else 22
    label_size = 9 if layout.mobile else 9
    pieces: list[str] = []
    for index, (value, label) in enumerate(cards):
        x = start_x + index * (card_width + card_gap)
        pieces.extend(
            [
                f'<g transform="translate({x:g} {layout.summary_y})">',
                f'<rect width="{card_width}" height="62" rx="14" fill="#0B2118" stroke="#1B5E43"/>',
                f'<text x="18" y="28" fill="#ECFDF5" font-size="{value_size}" font-weight="750">{value}</text>',
                f'<text x="18" y="47" fill="#6EE7B7" font-size="{label_size}" font-weight="700" letter-spacing="1.4">{label}</text>',
                "</g>",
            ]
        )
    return "".join(pieces)


def contribution_grid(days: list[Contribution], layout: Layout) -> str:
    start = days[0].day
    pitch = layout.cell + layout.gap
    pieces: list[str] = []
    for week, label in month_labels(days):
        x = layout.grid_x + week * pitch
        pieces.append(
            f'<text x="{x}" y="{layout.grid_y - 19}" fill="#6EE7B7" '
            f'font-size="{layout.grid_label_size}" font-weight="650" letter-spacing="1">{label}</text>'
        )
    for row, label in ((1, "MON"), (3, "WED"), (5, "FRI")):
        y = layout.grid_y + row * pitch + layout.cell - 2
        pieces.append(
            f'<text x="{layout.grid_x - 14}" y="{y}" text-anchor="end" fill="#4F8C72" '
            f'font-size="{layout.grid_label_size - 1}" font-weight="650">{label}</text>'
        )
    for item in days:
        week = (item.day - start).days // 7
        weekday = (item.day.weekday() + 1) % 7
        x = layout.grid_x + week * pitch
        y = layout.grid_y + weekday * pitch
        color = LEVEL_COLORS[max(0, min(item.level, 4))]
        label = "contribution" if item.count == 1 else "contributions"
        pieces.append(
            f'<rect x="{x}" y="{y}" width="{layout.cell}" height="{layout.cell}" rx="3" fill="{color}">'
            f'<title>{item.day.isoformat()}: {item.count} {label}</title></rect>'
        )
    return "".join(pieces)


def render_svg(days: list[Contribution], layout: Layout) -> str:
    summary = summarize(days)
    tagline = "A YEAR OF SHIPPING IN PUBLIC"
    if layout.mobile:
        heading = (
            f'<text x="40" y="84" fill="#F0FDF4" font-size="{layout.title_size}" font-weight="780">BUILD HISTORY</text>'
            f'<text x="40" y="112" fill="#6EE7B7" font-size="{layout.subtitle_size}" font-weight="700" letter-spacing="1.9">{tagline}</text>'
        )
    else:
        heading = (
            f'<text x="48" y="80" fill="#F0FDF4" font-size="{layout.title_size}" font-weight="780">BUILD HISTORY</text>'
            f'<text x="48" y="106" fill="#6EE7B7" font-size="{layout.subtitle_size}" font-weight="700" letter-spacing="1.9">{tagline}</text>'
        )
    updated = summary.last_day.strftime("%d %b %Y").upper()
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" height="{layout.height}" viewBox="0 0 {layout.width} {layout.height}" role="img" aria-labelledby="title desc">
<title id="title">GitHub build history for {PROFILE}</title>
<desc id="desc">{summary.total:,} contributions across {summary.active_days} active days in the displayed year.</desc>
<defs>
  <linearGradient id="history-bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#06140D"/><stop offset="1" stop-color="#0A1F16"/></linearGradient>
  <linearGradient id="history-line" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#14532D"/><stop offset=".5" stop-color="#22C55E"/><stop offset="1" stop-color="#86EFAC"/></linearGradient>
  <radialGradient id="history-glow"><stop stop-color="#22C55E" stop-opacity=".2"/><stop offset="1" stop-color="#22C55E" stop-opacity="0"/></radialGradient>
  <pattern id="history-grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="#86EFAC" stroke-opacity=".035"/></pattern>
</defs>
<rect x="1" y="1" width="{layout.width - 2}" height="{layout.height - 2}" rx="24" fill="url(#history-bg)" stroke="#1B5E43" stroke-width="2"/>
<rect x="1" y="1" width="{layout.width - 2}" height="{layout.height - 2}" rx="24" fill="url(#history-grid)"/>
<ellipse cx="{layout.width - 80}" cy="20" rx="260" ry="170" fill="url(#history-glow)"/>
<rect x="1" y="1" width="{layout.width - 2}" height="4" rx="2" fill="url(#history-line)"/>
<g font-family="Inter,Segoe UI,Arial,sans-serif">
  <circle cx="{40 if layout.mobile else 48}" cy="37" r="5" fill="#22C55E"/><circle cx="{40 if layout.mobile else 48}" cy="37" r="12" fill="none" stroke="#22C55E" stroke-opacity=".22"/>
  <text x="{60 if layout.mobile else 68}" y="41" fill="#86EFAC" font-size="10" font-weight="750" letter-spacing="2">PKM / PUBLIC LOG</text>
  {heading}
  {summary_cards(summary, layout)}
  {contribution_grid(days, layout)}
  <g transform="translate({layout.grid_x} {layout.height - 27})" font-size="9" font-weight="650" letter-spacing="1">
    <text fill="#4F8C72">LESS</text>
    {''.join(f'<rect x="{39 + index * 17}" y="-10" width="11" height="11" rx="2.5" fill="{color}"/>' for index, color in enumerate(LEVEL_COLORS))}
    <text x="132" fill="#4F8C72">MORE</text>
  </g>
  <text x="{layout.width - 42}" y="{layout.height - 25}" text-anchor="end" fill="#4F8C72" font-size="9" font-weight="650" letter-spacing="1.1">SNAPSHOT · {updated}</text>
</g>
</svg>
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=PROFILE)
    parser.add_argument("--input", type=Path, help="Use saved GitHub contribution HTML")
    parser.add_argument("--output-dir", type=Path, default=Path("assets"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    html = args.input.read_text() if args.input else fetch_calendar(args.username)
    days = parse_calendar(html)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "build-history.svg").write_text(render_svg(days, DESKTOP))
    (args.output_dir / "build-history-mobile.svg").write_text(render_svg(days, MOBILE))
    summary = summarize(days)
    print(
        f"Rendered {summary.total:,} contributions across {summary.active_days} active days "
        f"through {summary.last_day.isoformat()}."
    )


if __name__ == "__main__":
    main()
