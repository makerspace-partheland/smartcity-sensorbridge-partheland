#!/usr/bin/env python3
"""
Checks for new Home Assistant Core releases and creates an issue in this repository
if a new release is found. Also updates a state file with the last processed release.

Environment variables:
- GITHUB_TOKEN: GitHub token provided by Actions
- GITHUB_REPOSITORY: owner/repo string

This script intentionally avoids third-party dependencies and uses stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


GITHUB_API = "https://api.github.com"
HA_REPO = "home-assistant/core"
STATE_FILE = ".github/ha_release_state.json"


def github_api_request(path: str) -> Dict[str, Any]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not provided")

    url = f"{GITHUB_API}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data


def get_latest_stable_release() -> Optional[Dict[str, Any]]:
    releases = github_api_request(f"/repos/{HA_REPO}/releases?per_page=10")
    for rel in releases:
        if not rel.get("prerelease") and not rel.get("draft"):
            return rel
    return None


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def body_indicates_breaking_changes(text: str) -> bool:
    lowered = (text or "").lower()
    keywords = [
        "breaking change",
        "breaking changes",
        "deprecated",
        "remov",
        "migration",
        "incompatible",
    ]
    return any(k in lowered for k in keywords)


def create_issue_if_needed(tag: str, html_url: str, body: str, breaking: bool) -> None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY not provided")

    # Check if issue already exists
    query = f"repo:{repo} is:issue in:title \"{tag}\""
    search = github_api_request(f"/search/issues?q={urllib.parse.quote(query)}")
    if search.get("total_count", 0) > 0:
        print(f"Issue for {tag} already exists")
        return

    title = f"New Home Assistant Release: {tag}"
    labels = ["dependencies", "home-assistant"]
    if breaking:
        labels.append("breaking-changes")

    issue_body = (
        f"📦 New Home Assistant Release Available: {tag}\n\n"
        f"Release Notes: {html_url}\n\n"
        f"Summary (first 500 chars):\n\n{(body or '')[:500]}\n\n"
        "Required Actions:\n"
        "- [ ] Test with new Home Assistant version\n"
        "- [ ] Review breaking changes (if any)\n"
        "- [ ] Update integration/manifest if necessary\n"
    )

    payload = json.dumps(
        {
            "title": title,
            "body": issue_body,
            "labels": labels,
        }
    ).encode("utf-8")

    token = os.environ.get("GITHUB_TOKEN")
    req = urllib.request.Request(
        f"{GITHUB_API}/repos/{repo}/issues",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        created = json.loads(resp.read().decode("utf-8"))
        print(f"Created issue #{created.get('number')}: {created.get('title')}")


def main() -> int:
    try:
        latest = get_latest_stable_release()
        if not latest:
            print("No stable release found", file=sys.stderr)
            return 0

        tag = latest.get("tag_name") or latest.get("name") or "unknown"
        html_url = latest.get("html_url", "")
        body = latest.get("body", "")
        breaking = body_indicates_breaking_changes(body)

        state = load_state()
        last_tag = state.get("last_processed_tag")

        if tag == last_tag:
            print(f"No new release since {last_tag}")
            return 0

        # Create issue and update state
        create_issue_if_needed(tag, html_url, body, breaking)
        state["last_processed_tag"] = tag
        save_state(state)
        print(f"Updated state to {tag}")
        return 0
    except urllib.error.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())