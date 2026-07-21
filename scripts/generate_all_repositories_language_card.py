#!/usr/bin/env python3
"""Generate an SVG language pie chart from all public GitHub repositories.

The chart:
- Includes every public repository owned by the user, including forks.
- Fetches each repository's complete GitHub Linguist language-byte totals.
- Aggregates those byte totals across the entire account.
- Renders a clean SVG donut/pie chart suitable for a GitHub profile README.

Only Python's standard library is required.
"""

from __future__ import annotations

import colorsys
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

USERNAME = os.environ.get("GITHUB_USERNAME", "badgids")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUTPUT = Path(
    os.environ.get(
        "LANGUAGE_CARD_OUTPUT",
        "assets/all-repositories-languages.svg",
    )
)

# Keep the chart readable. Every repository and every language byte is still
# included; smaller languages are combined into one "Other" slice.
MAX_SLICES = max(2, int(os.environ.get("LANGUAGE_PIE_MAX_SLICES", "12")))

API_ROOT = "https://api.github.com"

# GitHub Linguist colors for common languages used across the account.
KNOWN_COLORS = {
    "Assembly": "#6E4C13",
    "Batchfile": "#C1F12E",
    "C": "#555555",
    "C#": "#178600",
    "C++": "#F34B7D",
    "CMake": "#DA3434",
    "CSS": "#663399",
    "Cuda": "#3A4E3A",
    "Dart": "#00B4AB",
    "Dockerfile": "#384D54",
    "GDScript": "#355570",
    "Go": "#00ADD8",
    "HTML": "#E34C26",
    "Java": "#B07219",
    "JavaScript": "#F1E05A",
    "Jupyter Notebook": "#DA5B0B",
    "Kotlin": "#A97BFF",
    "Lua": "#000080",
    "Makefile": "#427819",
    "Objective-C": "#438EFF",
    "PHP": "#4F5D95",
    "PowerShell": "#012456",
    "Python": "#3572A5",
    "R": "#198CE7",
    "Ruby": "#701516",
    "Rust": "#DEA584",
    "SCSS": "#C6538C",
    "Shell": "#89E051",
    "Svelte": "#FF3E00",
    "Swift": "#F05138",
    "TypeScript": "#3178C6",
    "Vue": "#41B883",
    "Other": "#8B949E",
}


def api_get(path: str) -> Any:
    """Fetch and decode one GitHub REST API response."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "badgids-language-pie-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = urllib.request.Request(f"{API_ROOT}{path}", headers=headers)

    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {403, 429, 500, 502, 503, 504}
            if retryable and attempt < 4:
                retry_after = exc.headers.get("Retry-After")
                delay = int(retry_after) if retry_after else 2**attempt
                time.sleep(delay)
                continue

            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API request failed ({exc.code}): {path}\n{body}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < 4:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(
                f"GitHub API request failed: {path}: {exc}"
            ) from exc

    raise RuntimeError(f"GitHub API request failed after retries: {path}")


def list_public_repositories() -> list[dict[str, Any]]:
    """List every public repository owned by USERNAME, including forks."""
    repositories: list[dict[str, Any]] = []
    page = 1

    while True:
        query = urllib.parse.urlencode(
            {
                "type": "owner",
                "sort": "full_name",
                "direction": "asc",
                "per_page": 100,
                "page": page,
            }
        )
        batch = api_get(
            f"/users/{urllib.parse.quote(USERNAME)}/repos?{query}"
        )

        if not isinstance(batch, list):
            raise RuntimeError(
                "GitHub returned an unexpected repository-list response"
            )

        repositories.extend(
            repo for repo in batch if not repo.get("private", False)
        )

        if len(batch) < 100:
            break

        page += 1

    return repositories


def aggregate_languages(
    repositories: list[dict[str, Any]],
) -> tuple[dict[str, int], int]:
    """Sum complete Linguist byte totals across all repositories."""
    totals: dict[str, int] = defaultdict(int)
    repositories_with_languages = 0

    for index, repository in enumerate(repositories, start=1):
        full_name = repository.get("full_name")
        if not full_name:
            continue

        print(
            f"[{index}/{len(repositories)}] Fetching languages for {full_name}",
            flush=True,
        )

        languages = api_get(f"/repos/{full_name}/languages")
        if not isinstance(languages, dict):
            raise RuntimeError(
                f"GitHub returned invalid language data for {full_name}"
            )

        if languages:
            repositories_with_languages += 1

        for language, byte_count in languages.items():
            if isinstance(byte_count, int) and byte_count > 0:
                totals[language] += byte_count

    return dict(totals), repositories_with_languages


def deterministic_color(name: str) -> str:
    """Create a stable readable color for languages not in KNOWN_COLORS."""
    if name in KNOWN_COLORS:
        return KNOWN_COLORS[name]

    seed = sum((index + 1) * ord(char) for index, char in enumerate(name))
    hue = (seed % 360) / 360.0
    saturation = 0.62
    lightness = 0.58
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def format_bytes(value: int) -> str:
    """Format a byte count for display."""
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)

    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount):,} {unit}"
            if amount < 10:
                return f"{amount:.1f} {unit}"
            return f"{amount:.0f} {unit}"
        amount /= 1024

    return f"{value:,} B"


def compact_languages(
    totals: dict[str, int],
) -> list[tuple[str, int, int]]:
    """Return readable chart slices while preserving every byte in the total.

    Each tuple is: (display_name, byte_count, grouped_language_count).
    grouped_language_count is 1 for normal slices and greater than 1 for Other.
    """
    ordered = sorted(
        totals.items(),
        key=lambda item: (-item[1], item[0].casefold()),
    )

    if len(ordered) <= MAX_SLICES:
        return [(name, count, 1) for name, count in ordered]

    visible = ordered[: MAX_SLICES - 1]
    remainder = ordered[MAX_SLICES - 1 :]
    other_bytes = sum(count for _, count in remainder)

    return [
        *[(name, count, 1) for name, count in visible],
        ("Other", other_bytes, len(remainder)),
    ]


def polar_point(
    center_x: float,
    center_y: float,
    radius: float,
    angle_degrees: float,
) -> tuple[float, float]:
    """Convert a clockwise SVG angle into an x/y point."""
    angle = math.radians(angle_degrees - 90)
    return (
        center_x + radius * math.cos(angle),
        center_y + radius * math.sin(angle),
    )


def donut_segment_path(
    center_x: float,
    center_y: float,
    outer_radius: float,
    inner_radius: float,
    start_angle: float,
    end_angle: float,
) -> str:
    """Build an SVG path for one donut segment."""
    outer_start = polar_point(
        center_x, center_y, outer_radius, start_angle
    )
    outer_end = polar_point(
        center_x, center_y, outer_radius, end_angle
    )
    inner_end = polar_point(
        center_x, center_y, inner_radius, end_angle
    )
    inner_start = polar_point(
        center_x, center_y, inner_radius, start_angle
    )

    large_arc = 1 if end_angle - start_angle > 180 else 0

    return (
        f"M {outer_start[0]:.3f} {outer_start[1]:.3f} "
        f"A {outer_radius} {outer_radius} 0 {large_arc} 1 "
        f"{outer_end[0]:.3f} {outer_end[1]:.3f} "
        f"L {inner_end[0]:.3f} {inner_end[1]:.3f} "
        f"A {inner_radius} {inner_radius} 0 {large_arc} 0 "
        f"{inner_start[0]:.3f} {inner_start[1]:.3f} Z"
    )


def render_svg(
    totals: dict[str, int],
    repository_count: int,
    repositories_with_languages: int,
) -> str:
    """Render the aggregated language data as a GitHub-friendly SVG pie chart."""
    if not totals:
        raise RuntimeError("No GitHub Linguist language bytes were found")

    slices = compact_languages(totals)
    total_bytes = sum(byte_count for _, byte_count, _ in slices)
    distinct_languages = len(totals)

    width = 900
    legend_top = 127
    legend_row_height = 27
    height = max(455, legend_top + len(slices) * legend_row_height + 58)
    center_x = 225
    center_y = height / 2 + 18
    outer_radius = 142
    inner_radius = 79

    legend_x = 425
    legend_value_x = 858

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" '
            'role="img" aria-labelledby="title description">'
        ),
        '<title id="title">Languages Used</title>',
        (
            '<desc id="description">'
            f'Language usage across {repository_count} repositories and '
            f'{distinct_languages} languages.'
            '</desc>'
        ),
        (
            f'<rect x="0.5" y="0.5" width="899" height="{height - 1}" rx="10" '
            'fill="#0D1117" stroke="#30363D"/>'
        ),
        (
            '<style>'
            'text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",'
            'Helvetica,Arial,sans-serif}'
            '.heading{font-size:23px;font-weight:700;fill:#F0F6FC}'
            '.subheading{font-size:13px;fill:#8B949E}'
            '.legend-name{font-size:14px;font-weight:600;fill:#C9D1D9}'
            '.legend-value{font-size:13px;fill:#8B949E}'
            '.center-total{font-size:21px;font-weight:700;fill:#F0F6FC}'
            '.center-label{font-size:12px;fill:#8B949E}'
            '</style>'
        ),
        (
            '<text class="heading" x="34" y="43">'
            'Languages Used</text>'
        ),
        (
            '<text class="subheading" x="34" y="68">'
            f'{repository_count} repositories · '
            f'{distinct_languages} languages</text>'
        ),
    ]

    # Draw the donut slices clockwise, beginning at 12 o'clock.
    current_angle = 0.0

    if len(slices) == 1:
        name, byte_count, _ = slices[0]
        color = deterministic_color(name)
        parts.append(
            f'<circle cx="{center_x}" cy="{center_y}" r="{outer_radius}" '
            f'fill="{color}" stroke="#0D1117" stroke-width="3"/>'
        )
        parts.append(
            f'<circle cx="{center_x}" cy="{center_y}" r="{inner_radius}" '
            'fill="#0D1117"/>'
        )
    else:
        for name, byte_count, grouped_count in slices:
            fraction = byte_count / total_bytes
            sweep = fraction * 360.0

            # Leave a tiny visual gap between slices without losing the actual
            # percentage calculation.
            gap = min(0.65, sweep * 0.08)
            start = current_angle + gap / 2
            end = current_angle + sweep - gap / 2

            if end > start:
                color = deterministic_color(name)
                path = donut_segment_path(
                    center_x,
                    center_y,
                    outer_radius,
                    inner_radius,
                    start,
                    end,
                )
                tooltip_name = (
                    f"Other ({grouped_count} languages)"
                    if name == "Other" and grouped_count > 1
                    else name
                )
                percentage = byte_count * 100 / total_bytes

                parts.append(
                    f'<path d="{path}" fill="{color}" '
                    'stroke="#0D1117" stroke-width="1">'
                    f'<title>{escape(tooltip_name)}: '
                    f'{percentage:.2f}% ({format_bytes(byte_count)})</title>'
                    '</path>'
                )

            current_angle += sweep

    parts.extend(
        [
            (
                f'<text class="center-total" x="{center_x}" y="{center_y - 5}" '
                f'text-anchor="middle">{format_bytes(total_bytes)}</text>'
            ),
            (
                f'<text class="center-label" x="{center_x}" y="{center_y + 18}" '
                'text-anchor="middle">GitHub Linguist bytes</text>'
            ),
        ]
    )

    for index, (name, byte_count, grouped_count) in enumerate(slices):
        y = legend_top + index * legend_row_height
        percentage = byte_count * 100 / total_bytes
        display_name = (
            f"Other ({grouped_count} languages)"
            if name == "Other" and grouped_count > 1
            else name
        )
        color = deterministic_color(name)

        parts.extend(
            [
                (
                    f'<rect x="{legend_x}" y="{y - 12}" width="14" height="14" '
                    f'rx="3" fill="{color}"/>'
                ),
                (
                    f'<text class="legend-name" x="{legend_x + 23}" y="{y}">'
                    f'{escape(display_name)}</text>'
                ),
                (
                    f'<text class="legend-value" x="{legend_value_x}" y="{y}" '
                    f'text-anchor="end">{percentage:.2f}% · '
                    f'{format_bytes(byte_count)}</text>'
                ),
            ]
        )

    parts.append("</svg>")

    return "\n".join(parts) + "\n"


def main() -> int:
    repositories = list_public_repositories()
    totals, repositories_with_languages = aggregate_languages(repositories)

    svg = render_svg(
        totals,
        repository_count=len(repositories),
        repositories_with_languages=repositories_with_languages,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8")

    print(
        f"Generated {OUTPUT} from {len(repositories)} public repositories, "
        f"{repositories_with_languages} repositories with languages, and "
        f"{len(totals)} distinct languages.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
