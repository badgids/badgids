#!/usr/bin/env python3
"""Refresh dynamic project sections in the Badgids GitHub profile README.

Behavior:
- Currently Working On: latest 5 qualifying GitHub projects actually worked on by badgids.
- Recently Contributed to: latest 10 unique external GitHub projects from public contribution events.
- Selected work / GitHub: curated candidates, up to 20. Original repos qualify automatically.
  Forks qualify only when the fork is ahead of upstream AND at least one unique commit is
  attributable to badgids.
- Selected work / Hugging Face: curated Badgids/* work, up to 20.

The activity project blocks intentionally preserve the presentation established by the
pre-automation README: linked project heading, summary quote, repository/license/last-commit
badges, overview text, feature bullets, and technology/topic tags.

Safety:
- Authenticated GitHub API access is required by default.
- All network collection finishes before README.md is written.
- Rate-limit/network failures abort without partially rewriting README.md.
"""

from __future__ import annotations

import argparse
import base64
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
SELECTED_GITHUB_LIMIT = 20
SELECTED_HF_LIMIT = 20

CURRENT_MARKER = "AUTO-CURRENTLY-WORKING-ON"
CONTRIB_MARKER = "AUTO-RECENT-CONTRIBUTIONS"
SELECTED_GITHUB_MARKER = "AUTO-SELECTED-GITHUB"
SELECTED_HF_MARKER = "AUTO-SELECTED-HUGGINGFACE"

CONTRIBUTION_EVENT_TYPES = {
    "PushEvent",
    "PullRequestEvent",
    "PullRequestReviewEvent",
    "IssuesEvent",
}

# Curated candidate pool. It is NOT an unconditional output list.
# Every candidate is checked against the current repository metadata each run.
SELECTED_GITHUB_CANDIDATES: tuple[str, ...] = (
    "badgids/comfyui-setup-manager",
    "badgids/Story-Film-Skills",
    "badgids/ComfyUI-Pi-Agent",
    "badgids/ComfyUI-scene-camera-action",
    "badgids/ComfyUI-OrbitSheets",
    "badgids/ComfyUI-H3-ExactAudioLock",
    "badgids/ComfyUI-ClipProj",
    "badgids/ACE-Step-DAW",
    "badgids/Ace-Step_Data-Tool",
    "badgids/Audacity-MCP",
    "badgids/Badgids-pi-statusline",
    "badgids/OpenKlyde",
    "badgids/transcription-app",
    "badgids/stitchmd",
    "badgids/instrument-tab-converter",
    "badgids/CondaLauncher",
    "badgids/ComfyUI-InstructorOllama",
    "badgids/ComfyUI-MediaMixer",
    "badgids/WatermarkRemover-AI",
    "badgids/AutoStoryGen",
    "badgids/Diffusion-101",
    "badgids/pic-to-story",
    "badgids/StoryCrafter",
    # Fork candidates may remain here: validation determines whether they qualify.
    "badgids/Comfyui_Minimax_h3_latent_Upscaler",
    "badgids/ComfyScript",
    "badgids/godot-ai",
)


@dataclass(frozen=True)
class HuggingFaceWork:
    title: str
    url: str
    summary: str


# Curated work owned by the Badgids Hugging Face namespace.
# Add more entries freely; rendering is independently capped at 20.
SELECTED_HUGGINGFACE: tuple[HuggingFaceWork, ...] = (
    HuggingFaceWork(
        "Gonzo-Chat-7B",
        "https://huggingface.co/Badgids/Gonzo-Chat-7B",
        "A merged 7B conversational model for chat, roleplay, agents, and general local inference.",
    ),
    HuggingFaceWork(
        "Gonzo-Chat-7B-GGUF",
        "https://huggingface.co/Badgids/Gonzo-Chat-7B-GGUF",
        "GGUF quantizations of Gonzo-Chat-7B for efficient local inference with llama.cpp-compatible runtimes.",
    ),
    HuggingFaceWork(
        "Gonzo-Code-7B",
        "https://huggingface.co/Badgids/Gonzo-Code-7B",
        "A merged 7B model focused on coding and agent-oriented work.",
    ),
    HuggingFaceWork(
        "Gonzo-Code-7B-GGUF",
        "https://huggingface.co/Badgids/Gonzo-Code-7B-GGUF",
        "GGUF quantizations of Gonzo-Code-7B for locally runnable coding and agent workflows.",
    ),
)


class GitHubAPIError(RuntimeError):
    def __init__(self, url: str, status: int | None, detail: str):
        self.url = url
        self.status = status
        self.detail = detail
        label = f"HTTP {status}" if status is not None else "network error"
        super().__init__(f"GitHub API {label} for {url}: {detail}")


class GitHubClient:
    def __init__(self, token: str, *, allow_unauthenticated: bool = False):
        self.token = token.strip()
        self.allow_unauthenticated = allow_unauthenticated
        self.cache: dict[str, Any] = {}
        self.request_count = 0
        if not self.token and not allow_unauthenticated:
            raise RuntimeError(
                "Authenticated GitHub API access is required. Set GITHUB_TOKEN or run through "
                "the repository's GitHub Actions workflow."
            )

    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "badgids-profile-readme-updater",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get(self, url: str, *, optional_statuses: tuple[int, ...] = ()) -> Any | None:
        if url in self.cache:
            return self.cache[url]

        request = urllib.request.Request(url, headers=self.headers())
        try:
            self.request_count += 1
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            if exc.code in optional_statuses:
                self.cache[url] = None
                return None
            if exc.code in (403, 429) and "rate limit" in detail.lower():
                reset = exc.headers.get("X-RateLimit-Reset") if exc.headers else None
                if reset:
                    detail += f" (rate-limit reset epoch: {reset})"
            raise GitHubAPIError(url, exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise GitHubAPIError(url, None, str(exc.reason)) from exc

        self.cache[url] = result
        return result


def md_escape(value: str | None) -> str:
    if not value:
        return "—"
    return " ".join(str(value).replace("|", r"\|").split())


def github_repo_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


def actor_matches(commit: dict[str, Any], username: str) -> bool:
    target = username.lower()
    for key in ("author", "committer"):
        actor = commit.get(key)
        if isinstance(actor, dict) and str(actor.get("login", "")).lower() == target:
            return True

    nested = commit.get("commit")
    if isinstance(nested, dict):
        for key in ("author", "committer"):
            actor = nested.get(key)
            if not isinstance(actor, dict):
                continue
            name = str(actor.get("name", "")).strip().lower()
            email = str(actor.get("email", "")).strip().lower()
            if name == target or email.startswith(target + "@") or email.startswith(target + "+"):
                return True
    return False


def list_owned_repositories(client: GitHubClient, username: str) -> list[dict[str, Any]]:
    """Fetch the user's public repository inventory once and reuse it everywhere."""
    encoded = urllib.parse.quote(username)
    repos: list[dict[str, Any]] = []
    for page in range(1, 11):
        url = (
            f"{API_ROOT}/users/{encoded}/repos"
            f"?type=owner&sort=pushed&direction=desc&per_page=100&page={page}"
        )
        batch = client.get(url)
        if not isinstance(batch, list):
            raise RuntimeError("Unexpected GitHub response while listing owned repositories")
        repos.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            break
    return repos


def fetch_full_repo(client: GitHubClient, repo: dict[str, Any]) -> dict[str, Any]:
    full_name = str(repo.get("full_name") or "").strip()
    if not full_name:
        return repo
    data = client.get(f"{API_ROOT}/repos/{full_name}")
    return data if isinstance(data, dict) else repo


def fork_has_material_user_changes(
    client: GitHubClient, repo: dict[str, Any], username: str
) -> bool:
    """A fork qualifies only if it is ahead of upstream with a user-attributable commit."""
    if not repo.get("fork", False):
        return True

    full_repo = repo
    parent = full_repo.get("parent")
    if not isinstance(parent, dict):
        full_repo = fetch_full_repo(client, repo)
        parent = full_repo.get("parent")
    if not isinstance(parent, dict):
        return False

    parent_full_name = str(parent.get("full_name") or "").strip()
    parent_branch = str(parent.get("default_branch") or "main").strip()
    fork_branch = str(full_repo.get("default_branch") or "main").strip()
    if not parent_full_name:
        return False

    comparison = f"{parent_branch}...{username}:{fork_branch}"
    encoded_comparison = urllib.parse.quote(comparison, safe=":.")
    data = client.get(
        f"{API_ROOT}/repos/{parent_full_name}/compare/{encoded_comparison}",
        optional_statuses=(404, 409, 422),
    )
    if not isinstance(data, dict) or int(data.get("ahead_by") or 0) <= 0:
        return False

    commits = data.get("commits") or []
    return any(
        isinstance(commit, dict) and actor_matches(commit, username)
        for commit in commits
    )


def qualifies_as_user_work(
    client: GitHubClient, repo: dict[str, Any], username: str
) -> bool:
    owner = str(repo.get("owner", {}).get("login", "")).lower()
    if owner != username.lower():
        return False
    if repo.get("archived", False):
        return False
    if str(repo.get("name", "")).lower() == PROFILE_REPO_NAME.lower():
        return False
    return fork_has_material_user_changes(client, repo, username)


def select_current_repositories(
    client: GitHubClient, repos: Iterable[dict[str, Any]], username: str
) -> list[dict[str, Any]]:
    ordered = sorted(repos, key=lambda repo: repo.get("pushed_at") or "", reverse=True)
    selected: list[dict[str, Any]] = []
    for repo in ordered:
        if len(selected) >= CURRENT_LIMIT:
            break
        if qualifies_as_user_work(client, repo, username):
            selected.append(repo)
    return selected


def fetch_external_contributions(
    client: GitHubClient, username: str
) -> list[dict[str, Any]]:
    username_lower = username.lower()
    seen: set[str] = set()
    contributions: list[dict[str, Any]] = []

    for page in range(1, 4):
        encoded = urllib.parse.quote(username)
        events = client.get(
            f"{API_ROOT}/users/{encoded}/events/public?per_page=100&page={page}"
        )
        if not isinstance(events, list):
            raise RuntimeError("Unexpected GitHub response while listing public events")
        if not events:
            break

        for event in events:
            if not isinstance(event, dict) or event.get("type") not in CONTRIBUTION_EVENT_TYPES:
                continue
            repo_name = str(event.get("repo", {}).get("name", "")).strip()
            if "/" not in repo_name:
                continue
            owner, _ = repo_name.split("/", 1)
            if owner.lower() == username_lower or repo_name.lower() in seen:
                continue

            metadata = client.get(
                f"{API_ROOT}/repos/{repo_name}", optional_statuses=(404, 451)
            )
            if not isinstance(metadata, dict):
                continue
            item = dict(metadata)
            item["contributed_at"] = event.get("created_at")
            contributions.append(item)
            seen.add(repo_name.lower())
            if len(contributions) >= CONTRIBUTION_LIMIT:
                return contributions

    return contributions


def fetch_repo_readme(client: GitHubClient, full_name: str) -> str:
    data = client.get(
        f"{API_ROOT}/repos/{full_name}/readme", optional_statuses=(404, 409)
    )
    if not isinstance(data, dict) or not data.get("content"):
        return ""
    try:
        return base64.b64decode(str(data["content"])).decode("utf-8", errors="replace")
    except Exception:
        return ""


def clean_inline_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    return " ".join(text.split()).strip()


def extract_readme_details(readme: str, fallback: str) -> tuple[str, list[str]]:
    """Extract an overview paragraph and useful feature bullets from a README."""
    if not readme:
        return fallback, []

    text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", readme, flags=re.DOTALL)
    lines = text.splitlines()

    cleaned: list[str] = []
    in_fence = False
    for raw in lines:
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        if stripped.startswith(("![", "[![", "<img", "<picture", "<div align=", "<p align=")):
            continue
        cleaned.append(line)

    paragraphs: list[str] = []
    buf: list[str] = []
    for line in cleaned:
        stripped = line.strip()
        if not stripped:
            if buf:
                paragraph = clean_inline_markdown(" ".join(buf))
                if paragraph:
                    paragraphs.append(paragraph)
                buf = []
            continue
        if stripped.startswith("#"):
            if buf:
                paragraph = clean_inline_markdown(" ".join(buf))
                if paragraph:
                    paragraphs.append(paragraph)
                buf = []
            continue
        if stripped.startswith(("-", "* ", "+ ", "> ", "|")):
            if buf:
                paragraph = clean_inline_markdown(" ".join(buf))
                if paragraph:
                    paragraphs.append(paragraph)
                buf = []
            continue
        lowered = stripped.lower()
        if lowered.startswith(("table of contents", "contents", "installation", "requirements")):
            continue
        buf.append(stripped)
    if buf:
        paragraph = clean_inline_markdown(" ".join(buf))
        if paragraph:
            paragraphs.append(paragraph)

    overview = fallback
    for paragraph in paragraphs:
        low = paragraph.lower()
        if len(paragraph) >= 40 and not low.startswith(("license", "copyright", "build status")):
            overview = paragraph[:700].rstrip()
            break

    bullets: list[str] = []
    preferred = False
    seen_preferred_heading = False
    for raw in cleaned:
        stripped = raw.strip()
        if stripped.startswith("#"):
            heading = clean_inline_markdown(stripped.lstrip("#").strip()).lower()
            if any(
                key in heading
                for key in ("feature", "highlight", "capabilit", "what it does", "what this")
            ):
                preferred = True
                seen_preferred_heading = True
                continue
            if preferred:
                break
            continue
        if preferred and re.match(r"^[-*+]\s+", stripped):
            item = clean_inline_markdown(re.sub(r"^[-*+]\s+", "", stripped))
            if 8 <= len(item) <= 260:
                bullets.append(item)
                if len(bullets) >= 6:
                    break

    if not bullets and not seen_preferred_heading:
        for raw in cleaned:
            stripped = raw.strip()
            if re.match(r"^[-*+]\s+", stripped):
                item = clean_inline_markdown(re.sub(r"^[-*+]\s+", "", stripped))
                if 12 <= len(item) <= 220 and not item.lower().startswith(
                    ("license", "install", "pip ")
                ):
                    bullets.append(item)
                    if len(bullets) >= 6:
                        break

    return overview, bullets


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
    return " · ".join(f"`{tag.replace('`', '')}`" for tag in tags)


def render_repo_block(
    client: GitHubClient, repo: dict[str, Any], *, external: bool = False
) -> str:
    full_name = str(repo.get("full_name") or "").strip()
    short_name = str(repo.get("name") or full_name.split("/")[-1] or "Repository").strip()
    display_name = full_name if external else short_name
    url = str(repo.get("html_url") or github_repo_url(full_name))
    description = md_escape(
        repo.get("description")
        or ("External open-source project." if external else "Active repository with recent development work.")
    )
    default_branch = str(repo.get("default_branch") or "main")
    readme = fetch_repo_readme(client, full_name)
    overview, features = extract_readme_details(readme, description)

    lines = [
        f"### [{display_name}]({url})",
        "",
        f"> {description}",
        "",
        f"[![Repository](https://img.shields.io/badge/VIEW_THE_REPOSITORY-F9A620?style=for-the-badge&logo=github&logoColor=0D1117)]({url})",
        f"[![License](https://img.shields.io/github/license/{full_name}?style=for-the-badge&labelColor=161B22&color=22D3EE)]({url}/blob/{default_branch}/LICENSE)",
        f"[![Last commit](https://img.shields.io/github/last-commit/{full_name}?style=for-the-badge&labelColor=161B22&color=F9A620)]({url}/commits/{default_branch})",
        "",
        overview,
    ]
    if features:
        lines.append("")
        lines.extend(f"- {feature}" for feature in features)

    tags = repo_topics_line(repo)
    if tags:
        lines.extend(["", tags])
    return "\n".join(lines).rstrip()


def render_project_blocks(
    client: GitHubClient, repos: Iterable[dict[str, Any]], *, external: bool = False
) -> str:
    blocks = [render_repo_block(client, repo, external=external) for repo in repos]
    if not blocks:
        return "_No qualifying public projects found._"
    return "\n\n<br>\n\n".join(blocks)


def select_github_work(
    client: GitHubClient,
    repo_inventory: Iterable[dict[str, Any]],
    username: str,
) -> list[dict[str, Any]]:
    repo_map = {
        str(repo.get("full_name") or "").lower(): repo
        for repo in repo_inventory
        if repo.get("full_name")
    }
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for full_name in SELECTED_GITHUB_CANDIDATES:
        if len(selected) >= SELECTED_GITHUB_LIMIT:
            break
        key = full_name.lower()
        if key in seen:
            continue
        seen.add(key)
        repo = repo_map.get(key)
        if not isinstance(repo, dict):
            continue
        if qualifies_as_user_work(client, repo, username):
            selected.append(repo)

    return selected


def render_selected_github(repos: Iterable[dict[str, Any]]) -> str:
    rows = ["| Project | What it explores |", "| --- | --- |"]
    count = 0
    for repo in repos:
        if count >= SELECTED_GITHUB_LIMIT:
            break
        count += 1
        name = md_escape(repo.get("name") or repo.get("full_name") or "Repository")
        url = str(repo.get("html_url") or github_repo_url(str(repo.get("full_name") or "")))
        summary = md_escape(repo.get("description") or "Open-source project by Badgids.")
        rows.append(f"| **[{name}]({url})** | {summary} |")
    if count == 0:
        rows.append("| _No qualifying selected GitHub projects found._ | — |")
    return "\n".join(rows)


def hf_is_owned_by_badgids(item: HuggingFaceWork) -> bool:
    parsed = urllib.parse.urlparse(item.url)
    if parsed.netloc.lower() != "huggingface.co":
        return False
    path = parsed.path.strip("/")
    return path.lower().startswith("badgids/") and len(path.split("/")) >= 2


def render_selected_huggingface(items: Iterable[HuggingFaceWork]) -> str:
    rows = ["| Project | What it explores |", "| --- | --- |"]
    count = 0
    for item in items:
        if count >= SELECTED_HF_LIMIT:
            break
        if not hf_is_owned_by_badgids(item):
            continue
        count += 1
        rows.append(
            f"| **[{md_escape(item.title)}]({item.url})** | {md_escape(item.summary)} |"
        )
    if count == 0:
        rows.append("| _No selected Hugging Face projects found._ | — |")
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


def update_readme(
    text: str,
    current_body: str,
    contrib_body: str,
    selected_github_body: str,
    selected_hf_body: str,
) -> str:
    text, current_found = replace_marker(text, CURRENT_MARKER, current_body)
    text, contrib_found = replace_marker(text, CONTRIB_MARKER, contrib_body)

    if not current_found or not contrib_found:
        legacy_pattern = re.compile(
            r"## 🚀 Currently building:.*?\n---\n\n(?=## About me)",
            re.DOTALL | re.IGNORECASE,
        )
        replacement = (
            "## 🚀 Currently Working On\n\n"
            f"{marker_block(CURRENT_MARKER, current_body)}\n\n"
            "## 🤝 Recently Contributed to\n\n"
            f"{marker_block(CONTRIB_MARKER, contrib_body)}\n\n"
            "---\n\n"
        )
        if legacy_pattern.search(text):
            text = legacy_pattern.sub(lambda _: replacement, text, count=1)
        elif "## About me" in text and not current_found:
            text = text.replace("## About me", replacement + "## About me", 1)
        elif not current_found or not contrib_found:
            raise RuntimeError("Could not locate the activity sections in README.md")

    selected_section = (
        "## Selected work\n\n"
        "### GitHub\n\n"
        f"{marker_block(SELECTED_GITHUB_MARKER, selected_github_body)}\n\n"
        "### Hugging Face\n\n"
        f"{marker_block(SELECTED_HF_MARKER, selected_hf_body)}\n"
    )
    selected_pattern = re.compile(
        r"## Selected work\n\n.*?(?=\nI am especially interested in collaborating on)",
        re.DOTALL,
    )
    if not selected_pattern.search(text):
        raise RuntimeError("Could not locate the Selected work section in README.md")
    text = selected_pattern.sub(lambda _: selected_section, text, count=1)
    return text


def self_test() -> None:
    sample = """# Profile\n\n## 🚀 Currently building: [Old](https://example.com)\n\n> Old\n\n---\n\n## About me\n\nAbout.\n\n---\n\n## Selected work\n\n| Project | Platform | What it explores |\n| --- | --- | --- |\n| Old | GitHub | old |\n\nI am especially interested in collaborating on things.\n"""
    current = "### [A](https://github.com/badgids/A)\n\n> A"
    contrib = "### [x/y](https://github.com/x/y)\n\n> Y"
    gh = "| Project | What it explores |\n| --- | --- |\n| **[A](https://github.com/badgids/A)** | A |"
    hf = "| Project | What it explores |\n| --- | --- |\n| **[M](https://huggingface.co/Badgids/M)** | M |"
    result = update_readme(sample, current, contrib, gh, hf)
    assert "## 🚀 Currently Working On" in result
    assert "## 🤝 Recently Contributed to" in result
    assert "### GitHub" in result and "### Hugging Face" in result
    assert "| Platform |" not in result
    result2 = update_readme(result, current, contrib, gh, hf)
    assert result2 == result

    fork = {"fork": False, "owner": {"login": "badgids"}, "name": "A"}
    dummy = object.__new__(GitHubClient)
    assert qualifies_as_user_work(dummy, fork, "badgids")
    assert hf_is_owned_by_badgids(
        HuggingFaceWork("M", "https://huggingface.co/Badgids/M", "M")
    )
    assert not hf_is_owned_by_badgids(
        HuggingFaceWork("M", "https://huggingface.co/SomeoneElse/M", "M")
    )
    print("Self-test passed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", default="README.md", help="Path to the profile README")
    parser.add_argument(
        "--username",
        default=os.environ.get("GITHUB_USERNAME", "badgids"),
        help="GitHub username whose activity should populate the profile",
    )
    parser.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="Allow unauthenticated GitHub API requests (not recommended).",
    )
    parser.add_argument("--self-test", action="store_true", help="Run offline self-tests and exit.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        client = GitHubClient(token, allow_unauthenticated=args.allow_unauthenticated)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    readme_path = Path(args.readme)
    original = readme_path.read_text(encoding="utf-8")

    try:
        # Collect everything first. README.md is not written unless ALL required collection succeeds.
        inventory = list_owned_repositories(client, args.username)
        current = select_current_repositories(client, inventory, args.username)
        contributions = fetch_external_contributions(client, args.username)
        selected_github = select_github_work(client, inventory, args.username)

        current_body = render_project_blocks(client, current, external=False)
        contrib_body = render_project_blocks(client, contributions, external=True)
        selected_github_body = render_selected_github(selected_github)
        selected_hf_body = render_selected_huggingface(SELECTED_HUGGINGFACE)

        updated = update_readme(
            original,
            current_body,
            contrib_body,
            selected_github_body,
            selected_hf_body,
        )
    except (GitHubAPIError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("README.md was not changed.", file=sys.stderr)
        return 1

    if updated != original:
        readme_path.write_text(updated, encoding="utf-8")
        hf_count = min(
            sum(1 for item in SELECTED_HUGGINGFACE if hf_is_owned_by_badgids(item)),
            SELECTED_HF_LIMIT,
        )
        print(
            f"Updated {readme_path}: {len(current)} current projects, "
            f"{len(contributions)} external contribution projects, "
            f"{len(selected_github)} selected GitHub projects, "
            f"{hf_count} selected Hugging Face projects."
        )
    else:
        print(f"{readme_path} is already current.")

    print(f"GitHub API requests used this run: {client.request_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
