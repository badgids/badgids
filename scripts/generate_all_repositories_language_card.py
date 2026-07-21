#!/usr/bin/env python3
"""Generate a complete public-repository GitHub Linguist language card."""

from __future__ import annotations

import json
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
API_ROOT = "https://api.github.com"

KNOWN_COLORS = {
    "Python": "#3572A5",
    "C": "#555555",
    "C++": "#f34b7d",
    "C#": "#178600",
    "Java": "#b07219",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "HTML": "#e34c26",
    "CSS": "#663399",
    "Shell": "#89e051",
    "PowerShell": "#012456",
    "Batchfile": "#C1F12E",
    "Lua": "#000080",
    "Rust": "#dea584",
    "Go": "#00ADD8",
    "GDScript": "#355570",
    "Jupyter Notebook": "#DA5B0B",
    "Dockerfile": "#384d54",
    "Makefile": "#427819",
    "CMake": "#DA3434",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "Ruby": "#701516",
    "PHP": "#4F5D95",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
}

FALLBACK_COLORS = [
    "#F9A620",
    "#22D3EE",
    "#A78BFA",
    "#34D399",
    "#FB7185",
    "#60A5FA",
    "#F472B6",
    "#FACC15",
    "#2DD4BF",
    "#C084FC",
    "#FB923C",
    "#94A3B8",
]


def api_get(path: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "badgids-language-card-generator",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    request = urllib.request.Request(f"{API_ROOT}{path}", headers=headers)

    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 429, 500, 502, 503, 504} and attempt < 3:
                time.sleep(2**attempt)
                continue
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API request failed ({exc.code}): {path}\n{body}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < 3:
                time.sleep(2**attempt)
                continue
            raise RuntimeError(
                f"GitHub API request failed: {path}: {exc}"
            ) from exc

    raise RuntimeError(f"GitHub API request failed after retries: {path}")


def list_public_repositories() -> list[dict[str, Any]]:
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
                "GitHub returned an unexpected repository response"
            )

        repositories.extend(
            repository
            for repository in batch
            if not repository.get("private", False)
        )

        if len(batch) < 100:
            return repositories

        page += 1


def aggregate_languages(
    repositories: list[dict[str, Any]],
) -> tuple[dict[str, int], int]:
    totals: dict[str, int] = defaultdict(int)
    repositories_with_languages = 0

    for repository in repositories:
        full_name = repository["full_name"]
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


def language_color(name: str, index: int) -> str:
    return KNOWN_COLORS.get(
        name,
        FALLBACK_COLORS[index % len(FALLBACK_COLORS)],
    )


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(value)

    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if amount < 10 and unit != "B":
                return f"{amount:.1f} {unit}"
            return f"{amount:.0f} {unit}"
        amount /= 1024

    return f"{value} B"


def render_svg(
    totals: dict[str, int],
    repository_count: int,
    repositories_with_languages: int,
) -> str:
    ordered = sorted(
        totals.items(),
        key=lambda item: (-item[1], item[0].lower()),
    )
    total_bytes = sum(value for _, value in ordered)

    if total_bytes <= 0:
        raise RuntimeError("No Linguist language bytes were found")

    width = 880
    margin = 34
    bar_y = 91
    bar_height = 18
    legend_top = 132
    row_height = 29
    columns = 2
    rows = (len(ordered) + columns - 1) // columns
    height = legend_top + rows * row_height + 31
    column_width = (width - margin * 2) / columns
    bar_width = width - margin * 2

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" '
            'role="img" aria-labelledby="title desc">'
        ),
        '<title id="title">All Repositories by Language</title>',
        (
            f'<desc id="desc">Complete GitHub Linguist byte totals across '
            f'{repository_count} public repositories, including forks.</desc>'
        ),
        (
            '<rect x="0.5" y="0.5" width="879" height="99%" rx="8" '
            'fill="#0D1117" stroke="#30363D"/>'
        ),
        (
            '<style>'
            'text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",'
            'Helvetica,Arial,sans-serif}'
            '.title{font-size:22px;font-weight:600;fill:#F0F6FC}'
            '.sub{font-size:13px;fill:#8B949E}'
            '.name{font-size:14px;font-weight:600;fill:#C9D1D9}'
            '.value{font-size:13px;fill:#8B949E}'
            '</style>'
        ),
        (
            f'<text class="title" x="{margin}" y="42">'
            'All Repositories by Language</text>'
        ),
        (
            f'<text class="sub" x="{margin}" y="68">'
            f'{repository_count} public repositories · forks included · '
            f'{repositories_with_languages} with detected code · '
            'complete Linguist byte totals</text>'
        ),
        (
            f'<clipPath id="bar"><rect x="{margin}" y="{bar_y}" '
            f'width="{bar_width}" height="{bar_height}" rx="5"/></clipPath>'
        ),
        '<g clip-path="url(#bar)">',
    ]

    x = float(margin)
    for index, (name, byte_count) in enumerate(ordered):
        segment_width = bar_width * byte_count / total_bytes
        parts.append(
            f'<rect x="{x:.3f}" y="{bar_y}" '
            f'width="{segment_width + 0.05:.3f}" height="{bar_height}" '
            f'fill="{language_color(name, index)}"/>'
        )
        x += segment_width

    parts.append("</g>")

    for index, (name, byte_count) in enumerate(ordered):
        column = index // rows
        row = index % rows
        x = margin + column * column_width
        y = legend_top + row * row_height
        percentage = byte_count * 100 / total_bytes

        parts.extend(
            [
                (
                    f'<circle cx="{x + 6:.1f}" cy="{y - 4}" r="6" '
                    f'fill="{language_color(name, index)}"/>'
                ),
                (
                    f'<text class="name" x="{x + 20:.1f}" y="{y}">'
                    f'{escape(name)}</text>'
                ),
                (
                    f'<text class="value" '
                    f'x="{x + column_width - 8:.1f}" y="{y}" '
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
        len(repositories),
        repositories_with_languages,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8")

    print(
        f"Generated {OUTPUT} from {len(repositories)} public repositories "
        f"({repositories_with_languages} with detected languages, "
        f"{len(totals)} languages)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
