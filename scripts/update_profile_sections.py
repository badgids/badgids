#!/usr/bin/env python3
"""Refresh dynamic sections in the Badgids GitHub profile README.

The two activity sections are generated from public GitHub activity:
- Currently Working On: the five most recently pushed, non-fork repositories owned by the user.
- Recently Contributed to: the ten most recent unique external repositories found in the user's public contribution-like events.

Selected Work remains curated, but this script renders the list consistently and refreshes
GitHub repository descriptions when available. Hugging Face entries are kept alongside GitHub work.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

API_ROOT = "https://api.github.com"
PROFILE_REPO_NAME = "badgids"
CURRENT_LIMIT = 5
CONTRIBUTION_LIMIT = 10

CURRENT_MARKER = "AUTO-CURRENTLY-WORKING-ON"
CONTRIB_MARKER = "AUTO-RECENT-CONTRIBUTIONS"
SELECTED_MARKER = "AUTO-SELECTED-WORK"

CONTRIBUTION_EVENT_TYPES = {
    "PushEvent",
    "PullRequestEvent",
    "PullRequestReviewEvent",
    "IssuesEvent",
}


@dataclass(frozen=True)
class SelectedWork:
    platform: str
    title: str
    url: str
    summary: str
    github_repo: str | None = None


# Curated portfolio: maximum 20 entries, including every public Badgids Hugging Face model.
SELECTED_WORK: tuple[SelectedWork, ...] = (
    SelectedWork("GitHub", "ComfyUI Setup Manager", "https://github.com/badgids/comfyui-setup-manager", "Portable, repairable, multi-install ComfyUI management through a full TUI and CLI.", "badgids/comfyui-setup-manager"),
    SelectedWork("GitHub", "Story Film Skills", "https://github.com/badgids/Story-Film-Skills", "Agent skills and production tooling for structured AI-assisted story and film workflows.", "badgids/Story-Film-Skills"),
    SelectedWork("GitHub", "ComfyUI Pi Agent", "https://github.com/badgids/ComfyUI-Pi-Agent", "Pi-agent integration and automation for working with ComfyUI.", "badgids/ComfyUI-Pi-Agent"),
    SelectedWork("GitHub", "ComfyUI Scene Camera Action", "https://github.com/badgids/ComfyUI-scene-camera-action", "Scene, camera, and action tooling for controllable ComfyUI media production.", "badgids/ComfyUI-scene-camera-action"),
    SelectedWork("GitHub", "ComfyUI OrbitSheets", "https://github.com/badgids/ComfyUI-OrbitSheets", "Multi-view and orbit-sheet generation tools for consistent visual references.", "badgids/ComfyUI-OrbitSheets"),
    SelectedWork("GitHub", "ComfyUI H3 ExactAudioLock", "https://github.com/badgids/ComfyUI-H3-ExactAudioLock", "Audio-locking utilities for MiniMax H3 video workflows in ComfyUI.", "badgids/ComfyUI-H3-ExactAudioLock"),
    SelectedWork("GitHub", "ComfyUI MiniMax H3 Latent Upscaler", "https://github.com/badgids/Comfyui_Minimax_h3_latent_Upscaler", "Latent upscaling experiments and workflows for MiniMax H3 generation.", "badgids/Comfyui_Minimax_h3_latent_Upscaler"),
    SelectedWork("GitHub", "ComfyUI ClipProj", "https://github.com/badgids/ComfyUI-ClipProj", "ComfyUI tooling around CLIP projection and reference-processing workflows.", "badgids/ComfyUI-ClipProj"),
    SelectedWork("GitHub", "ACE-Step DAW", "https://github.com/badgids/ACE-Step-DAW", "DAW-oriented experimentation and tooling around ACE-Step music generation.", "badgids/ACE-Step-DAW"),
    SelectedWork("GitHub", "ACE-Step Data Tool", "https://github.com/badgids/Ace-Step_Data-Tool", "Dataset preparation and supporting utilities for ACE-Step workflows.", "badgids/Ace-Step_Data-Tool"),
    SelectedWork("GitHub", "Audacity MCP", "https://github.com/badgids/Audacity-MCP", "Model Context Protocol integration experiments for controlling Audacity.", "badgids/Audacity-MCP"),
    SelectedWork("GitHub", "ComfyScript", "https://github.com/badgids/ComfyScript", "Programmatic and scriptable approaches to building and operating ComfyUI workflows.", "badgids/ComfyScript"),
    SelectedWork("GitHub", "Godot AI", "https://github.com/badgids/godot-ai", "AI-assisted experimentation and tooling around the Godot game engine.", "badgids/godot-ai"),
    SelectedWork("GitHub", "OpenKlyde", "https://github.com/badgids/OpenKlyde", "An open-source Discord bot project built for experimentation and collaboration.", "badgids/OpenKlyde"),
    SelectedWork("GitHub", "Transcription App", "https://github.com/badgids/transcription-app", "Real-time transcription experiments powered by OpenAI Whisper.", "badgids/transcription-app"),
    SelectedWork("GitHub", "stitchmd", "https://github.com/badgids/stitchmd", "Utilities for assembling and working with Markdown content.", "badgids/stitchmd"),
    SelectedWork("Hugging Face", "Gonzo-Chat-7B", "https://huggingface.co/Badgids/Gonzo-Chat-7B", "A merged 7B conversational model for chat, roleplay, agents, and general local inference."),
    SelectedWork("Hugging Face", "Gonzo-Chat-7B-GGUF", "https://huggingface.co/Badgids/Gonzo-Chat-7B-GGUF", "GGUF quantizations of Gonzo-Chat-7B for efficient local inference with llama.cpp-compatible runtimes."),
    SelectedWork("Hugging Face", "Gonzo-Code-7B", "https://huggingface.co/Badgids/Gonzo-Code-7B", "A merged 7B model focused on coding and agent-oriented work."),
    SelectedWork("Hugging Face", "Gonzo-Code-7B-GGUF", "https://huggingface.co/Badgids/Gonzo-Code-7B-GGUF", "GGUF quantizations of Gonzo-Code-7B for locally runnable coding and agent workflows."),
)


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "badgids-profile-readme-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def api_get(url: str) -> Any:
    request = urllib.request.Request(url, headers=github_headers())
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"GitHub API request failed ({exc.code}) for {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API request failed for {url}: {exc.reason}") from exc


def api_get_optional(url: str) -> Any | None:
    try:
        return api_get(url)
    except RuntimeError as exc:
        print(f"warning: {exc}", file=sys.stderr)
        return None


def date_only(value: str | None) -> str:
    if not value:
        return "—"
    return value[:10]


def md_escape(value: str | None) -> str:
    if not value:
        return "—"
    return " ".join(value.replace("|", r"\|").split())


def github_repo_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


def fetch_current_repositories(username: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(username)
    url = f"{API_ROOT}/users/{encoded}/repos?type=owner&sort=pushed&direction=desc&per_page=100&page=1"
    repos = api_get(url)
    if not isinstance(repos, list):
        raise RuntimeError("Unexpected GitHub response while listing owned repositories")

    username_lower = username.lower()
    eligible = [
        repo
        for repo in repos
        if str(repo.get("owner", {}).get("login", "")).lower() == username_lower
        and not repo.get("fork", False)
        and not repo.get("archived", False)
        and str(repo.get("name", "")).lower() != PROFILE_REPO_NAME.lower()
    ]
    eligible.sort(key=lambda repo: repo.get("pushed_at") or "", reverse=True)
    return eligible[:CURRENT_LIMIT]


def fetch_external_contributions(username: str) -> list[dict[str, Any]]:
    username_lower = username.lower()
    seen: set[str] = set()
    contributions: list[dict[str, Any]] = []

    # GitHub's public events feed exposes up to the most recent 300 events.
    for page in range(1, 4):
        encoded = urllib.parse.quote(username)
        url = f"{API_ROOT}/users/{encoded}/events/public?per_page=100&page={page}"
        events = api_get(url)
        if not isinstance(events, list):
            raise RuntimeError("Unexpected GitHub response while listing public events")
        if not events:
            break

        for event in events:
            if event.get("type") not in CONTRIBUTION_EVENT_TYPES:
                continue
            repo_name = str(event.get("repo", {}).get("name", "")).strip()
            if "/" not in repo_name:
                continue
            owner, _ = repo_name.split("/", 1)
            if owner.lower() == username_lower:
                continue
            key = repo_name.lower()
            if key in seen:
                continue

            seen.add(key)
            contributions.append(
                {
                    "full_name": repo_name,
                    "html_url": github_repo_url(repo_name),
                    "description": None,
                    "contributed_at": event.get("created_at"),
                }
            )
            if len(contributions) >= CONTRIBUTION_LIMIT:
                break

        if len(contributions) >= CONTRIBUTION_LIMIT:
            break

    for contribution in contributions:
        repo_name = contribution["full_name"]
        metadata = api_get_optional(f"{API_ROOT}/repos/{repo_name}")
        if isinstance(metadata, dict):
            contribution["full_name"] = metadata.get("full_name") or repo_name
            contribution["name"] = metadata.get("name") or repo_name.split("/", 1)[-1]
            contribution["html_url"] = metadata.get("html_url") or github_repo_url(repo_name)
            contribution["description"] = metadata.get("description")
            contribution["default_branch"] = metadata.get("default_branch") or "main"
            contribution["language"] = metadata.get("language")
            contribution["topics"] = metadata.get("topics") or []

    return contributions


def repo_topics_line(repo: dict[str, Any]) -> str:
    tags: list[str] = []
    language = str(repo.get("language") or "").strip()
    if language:
        tags.append(language)
    for topic in repo.get("topics") or []:
        topic_text = str(topic).strip()
        if topic_text and topic_text.lower() not in {tag.lower() for tag in tags}:
            tags.append(topic_text)
        if len(tags) >= 8:
            break
    if not tags:
        return ""
    return " · ".join(f"`{tag.replace('`', '')}`" for tag in tags)


def render_repo_block(repo: dict[str, Any], *, external: bool = False) -> str:
    full_name = str(repo.get("full_name") or "").strip()
    short_name = str(repo.get("name") or "").strip()
    if not short_name and "/" in full_name:
        short_name = full_name.split("/", 1)[1]
    display_name = full_name if external and full_name else (short_name or full_name or "Repository")
    url = str(repo.get("html_url") or github_repo_url(full_name))
    description = md_escape(
        repo.get("description")
        or ("External open-source project." if external else "Active repository with recent development work.")
    )
    default_branch = str(repo.get("default_branch") or "main")

    lines = [
        f"### [{md_escape(display_name)}]({url})",
        "",
        f"> {description}",
        "",
        f"[![Repository](https://img.shields.io/badge/VIEW_THE_REPOSITORY-F9A620?style=for-the-badge&logo=github&logoColor=0D1117)]({url})",
    ]

    if full_name:
        lines.extend(
            [
                f"[![License](https://img.shields.io/github/license/{full_name}?style=for-the-badge&labelColor=161B22&color=22D3EE)]({url})",
                f"[![Last commit](https://img.shields.io/github/last-commit/{full_name}?style=for-the-badge&labelColor=161B22&color=F9A620)]({url}/commits/{default_branch})",
            ]
        )

    tags = repo_topics_line(repo)
    if tags:
        lines.extend(["", tags])

    return "\n".join(lines)


def render_project_blocks(repos: Iterable[dict[str, Any]], *, external: bool = False) -> str:
    blocks = [render_repo_block(repo, external=external) for repo in repos]
    if not blocks:
        if external:
            return "_No recent public external contribution activity found._"
        return "_No qualifying public repositories found._"
    return "\n\n<br>\n\n".join(blocks)


def render_current(repos: Iterable[dict[str, Any]]) -> str:
    return render_project_blocks(repos, external=False)


def render_contributions(contributions: Iterable[dict[str, Any]]) -> str:
    return render_project_blocks(contributions, external=True)

def refresh_selected_descriptions(items: Iterable[SelectedWork]) -> list[SelectedWork]:
    refreshed: list[SelectedWork] = []
    for item in items:
        if not item.github_repo:
            refreshed.append(item)
            continue
        metadata = api_get_optional(f"{API_ROOT}/repos/{item.github_repo}")
        description = item.summary
        if isinstance(metadata, dict) and metadata.get("description"):
            description = str(metadata["description"])
        refreshed.append(
            SelectedWork(
                platform=item.platform,
                title=item.title,
                url=item.url,
                summary=description,
                github_repo=item.github_repo,
            )
        )
    return refreshed


def render_selected(items: Iterable[SelectedWork]) -> str:
    # Preserve the profile's original Selected work presentation: two columns only.
    rows = [
        "| Project | What it explores |",
        "| --- | --- |",
    ]
    for item in list(items)[:20]:
        title = md_escape(item.title)
        summary = md_escape(item.summary)
        rows.append(f"| **[{title}]({item.url})** | {summary} |")
    return "\n".join(rows)


def marker_block(marker: str, body: str) -> str:
    return f"<!-- {marker}:START -->\n{body.rstrip()}\n<!-- {marker}:END -->"


def replace_marker(text: str, marker: str, body: str) -> tuple[str, bool]:
    pattern = re.compile(
        rf"<!-- {re.escape(marker)}:START -->.*?<!-- {re.escape(marker)}:END -->",
        re.DOTALL,
    )
    replacement = marker_block(marker, body)
    if not pattern.search(text):
        return text, False
    return pattern.sub(lambda _: replacement, text, count=1), True


def update_readme(text: str, current_body: str, contrib_body: str, selected_body: str) -> str:
    current_block = marker_block(CURRENT_MARKER, current_body)
    contrib_block = marker_block(CONTRIB_MARKER, contrib_body)
    selected_block = marker_block(SELECTED_MARKER, selected_body)

    text, current_found = replace_marker(text, CURRENT_MARKER, current_body)
    text, contrib_found = replace_marker(text, CONTRIB_MARKER, contrib_body)

    if not current_found or not contrib_found:
        legacy_pattern = re.compile(
            r"## 🚀 Currently building:.*?\n---\n\n(?=## About me)",
            re.DOTALL | re.IGNORECASE,
        )
        activity_sections = (
            "## 🚀 Currently Working On\n\n"
            f"{current_block}\n\n"
            "## 🤝 Recently Contributed to\n\n"
            f"{contrib_block}\n\n"
            "---\n\n"
        )
        if legacy_pattern.search(text):
            text = legacy_pattern.sub(lambda _: activity_sections, text, count=1)
        elif not current_found and "## About me" in text:
            text = text.replace("## About me", activity_sections + "## About me", 1)
        else:
            if not current_found:
                raise RuntimeError("Could not locate the legacy Currently building section in README.md")

    text, selected_found = replace_marker(text, SELECTED_MARKER, selected_body)
    if not selected_found:
        selected_pattern = re.compile(
            r"## Selected work\n\n.*?(?=\nI am especially interested in collaborating on)",
            re.DOTALL,
        )
        replacement = "## Selected work\n\n" + selected_block + "\n"
        if selected_pattern.search(text):
            text = selected_pattern.sub(lambda _: replacement, text, count=1)
        else:
            raise RuntimeError("Could not locate the Selected work section in README.md")

    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", default="README.md", help="Path to the profile README")
    parser.add_argument(
        "--username",
        default=os.environ.get("GITHUB_USERNAME", "badgids"),
        help="GitHub username whose activity should populate the profile",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    readme_path = Path(args.readme)
    original = readme_path.read_text(encoding="utf-8")

    current = fetch_current_repositories(args.username)
    contributions = fetch_external_contributions(args.username)
    selected = refresh_selected_descriptions(SELECTED_WORK)

    updated = update_readme(
        original,
        render_current(current),
        render_contributions(contributions),
        render_selected(selected),
    )

    if updated != original:
        readme_path.write_text(updated, encoding="utf-8")
        print(
            f"Updated {readme_path}: {len(current)} current projects, "
            f"{len(contributions)} external contribution projects, {len(selected)} selected work entries."
        )
    else:
        print(f"{readme_path} is already current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
