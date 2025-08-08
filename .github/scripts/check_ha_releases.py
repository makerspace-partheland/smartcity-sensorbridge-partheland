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
import urllib.request
import urllib.parse
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
    # Fetch releases (non-prerelease, non-draft). We fetch a few and filter.
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

    payload = json.dumps({
        "title": title,
        "body": issue_body,
        "labels": labels,
    }).encode("utf-8")

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

#!/usr/bin/env python3
"""
Home Assistant Release Monitor für SmartCity SensorBridge Partheland

Überwacht Home Assistant Releases und erkennt Breaking Changes.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import yaml
from bs4 import BeautifulSoup


class HAReleaseMonitor:
    """Monitor für Home Assistant Releases"""

    def __init__(self):
        self.ha_releases_url = "https://api.github.com/repos/home-assistant/core/releases"
        self.breaking_changes_url = "https://www.home-assistant.io/blog/category/release-notes/"
        self.state_file = Path(".github/ha_release_state.json")
        self.current_ha_version = self._get_current_ha_version()
        
    def _get_current_ha_version(self) -> str:
        """Ermittelt die aktuell verwendete Home Assistant Version"""
        try:
            # Versuche aus pyproject.toml zu lesen
            with open("pyproject.toml", "r") as f:
                content = f.read()
                match = re.search(r'homeassistant==([0-9]+\.[0-9]+\.[0-9]+)', content)
                if match:
                    return match.group(1)
        except FileNotFoundError:
            pass
            
        # Fallback: Aktuelle Version aus CI-Konfiguration
        try:
            with open(".github/workflows/ci.yml", "r") as f:
                content = f.read()
                match = re.search(r'homeassistant-version: \[([^\]]+)\]', content)
                if match:
                    versions = match.group(1).split(", ")
                    # Nehme die neueste Version
                    return versions[-1].strip('"')
        except FileNotFoundError:
            pass
            
        return "2024.12"  # Fallback
        
    def _load_state(self) -> Dict:
        """Lädt den gespeicherten Zustand"""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {"last_checked": None, "last_release": None}
        
    def _save_state(self, state: Dict):
        """Speichert den aktuellen Zustand"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)
            
    def _get_latest_ha_release(self) -> Optional[Dict]:
        """Holt die neueste Home Assistant Release-Information"""
        try:
            headers = {
                "User-Agent": "SmartCity-SensorBridge-HA-Monitor/1.0",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.get(self.ha_releases_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            releases = response.json()
            if releases:
                latest = releases[0]
                return {
                    "version": latest["tag_name"].lstrip("v"),
                    "published_at": latest["published_at"],
                    "body": latest["body"],
                    "html_url": latest["html_url"]
                }
        except Exception as e:
            print(f"Fehler beim Abrufen der HA-Releases: {e}", file=sys.stderr)
            
        return None
        
    def _check_breaking_changes(self, release_body: str) -> Tuple[bool, List[str]]:
        """Prüft auf Breaking Changes in den Release Notes"""
        breaking_changes = []
        has_breaking = False
        
        # Keywords für Breaking Changes
        breaking_keywords = [
            "breaking change",
            "breaking changes",
            "deprecated",
            "removed",
            "changed",
            "breaking",
            "incompatible"
        ]
        
        # Prüfe auf Breaking Change Sektionen
        lines = release_body.lower().split("\n")
        in_breaking_section = False
        
        for line in lines:
            if any(keyword in line for keyword in ["breaking change", "breaking changes"]):
                in_breaking_section = True
                has_breaking = True
                continue
                
            if in_breaking_section:
                if line.strip().startswith("#") and "breaking" not in line:
                    in_breaking_section = False
                elif line.strip():
                    breaking_changes.append(line.strip())
                    
        # Zusätzliche Prüfung auf Keywords im gesamten Text
        if not has_breaking:
            for keyword in breaking_keywords:
                if keyword in release_body.lower():
                    has_breaking = True
                    break
                    
        return has_breaking, breaking_changes
        
    def _extract_release_summary(self, release_body: str, max_length: int = 500) -> str:
        """Extrahiert eine Zusammenfassung der Release Notes"""
        # Entferne Markdown-Formatierung
        summary = re.sub(r'#{1,6}\s+', '', release_body)
        summary = re.sub(r'\*\*(.*?)\*\*', r'\1', summary)
        summary = re.sub(r'\*(.*?)\*', r'\1', summary)
        
        # Entferne Links
        summary = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', summary)
        
        # Entferne Code-Blöcke
        summary = re.sub(r'```.*?```', '', summary, flags=re.DOTALL)
        
        # Entferne Inline-Code
        summary = re.sub(r'`([^`]+)`', r'\1', summary)
        
        # Bereinige Whitespace
        summary = re.sub(r'\n\s*\n', '\n\n', summary)
        summary = summary.strip()
        
        # Kürze auf maximale Länge
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."
            
        return summary
        
    def check_for_updates(self) -> Dict:
        """Hauptfunktion: Prüft auf neue Home Assistant Releases"""
        state = self._load_state()
        latest_release = self._get_latest_ha_release()
        
        if not latest_release:
            print("Konnte keine HA-Release-Informationen abrufen", file=sys.stderr)
            return {
                "new-release": "false",
                "breaking-changes": "false",
                "release-notes": "Fehler beim Abrufen der Release-Informationen"
            }
            
        # Prüfe ob es eine neue Release gibt
        last_checked_release = state.get("last_release")
        is_new_release = (
            last_checked_release is None or 
            latest_release["version"] != last_checked_release
        )
        
        # Prüfe auf Breaking Changes
        has_breaking, breaking_details = self._check_breaking_changes(latest_release["body"])
        
        # Erstelle Release-Zusammenfassung
        release_summary = self._extract_release_summary(latest_release["body"])
        
        # Aktualisiere State
        if is_new_release:
            state["last_release"] = latest_release["version"]
            state["last_checked"] = datetime.now().isoformat()
            self._save_state(state)
            
        # GitHub Actions Output
        result = {
            "new-release": str(is_new_release).lower(),
            "breaking-changes": str(has_breaking).lower(),
            "release-notes": release_summary
        }
        
        # Debug-Ausgabe
        print(f"Current HA version: {self.current_ha_version}")
        print(f"Latest HA release: {latest_release['version']}")
        print(f"Is new release: {is_new_release}")
        print(f"Has breaking changes: {has_breaking}")
        
        # GitHub Actions Output setzen
        for key, value in result.items():
            print(f"::set-output name={key}::{value}")
            
        return result


def main():
    """Hauptfunktion"""
    monitor = HAReleaseMonitor()
    result = monitor.check_for_updates()
    
    # Exit-Code basierend auf Breaking Changes
    if result["breaking-changes"] == "true":
        sys.exit(1)  # Breaking Changes erfordern Aufmerksamkeit
    else:
        sys.exit(0)


if __name__ == "__main__":
    main() 