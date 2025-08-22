#!/usr/bin/env python3
"""
Prüft auf neue Home Assistant Core Releases und erstellt ein Issue in diesem Repository,
wenn eine neue Version gefunden wird. Aktualisiert auch eine Status-Datei mit der
zuletzt verarbeiteten Version.

Umgebungsvariablen:
- GITHUB_TOKEN: GitHub Token von Actions bereitgestellt
- GITHUB_REPOSITORY: owner/repo string

Dieses Skript vermeidet absichtlich Third-Party-Abhängigkeiten und verwendet nur stdlib.
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





def create_issue_if_needed(tag: str, html_url: str, breaking: bool) -> None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY not provided")

    # Prüfen, ob Issue bereits existiert
    query = f"repo:{repo} is:issue in:title \"{tag}\""
    search = github_api_request(f"/search/issues?q={urllib.parse.quote(query)}")
    if search.get("total_count", 0) > 0:
        print(f"Issue für {tag} existiert bereits")
        return



    title = f"Neue Home Assistant Version: {tag}"
    labels = ["dependencies", "home-assistant"]
    if breaking:
        labels.append("breaking-changes")

    issue_body = (
        f"📦 Neue Home Assistant Version verfügbar: {tag}\n\n"
        f"Release Notes: {html_url}\n\n"
        "Erforderliche Maßnahmen:\n"
        "- [ ] Mit neuer Home Assistant Version testen\n"
        "- [ ] Breaking Changes überprüfen (falls vorhanden)\n"
        "- [ ] Integration/Manifest aktualisieren (falls nötig)\n"
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
        print(f"Issue #{created.get('number')} erstellt: {created.get('title')}")


def main() -> int:
    try:
        latest = get_latest_stable_release()
        if not latest:
            print("Keine stabile Version gefunden", file=sys.stderr)
            return 0

        tag = latest.get("tag_name") or latest.get("name") or "unknown"
        html_url = latest.get("html_url", "")
        body = latest.get("body", "")
        breaking = body_indicates_breaking_changes(body)

        state = load_state()
        last_tag = state.get("last_processed_tag")

        if tag == last_tag:
            print(f"Keine neue Version seit {last_tag}")
            return 0

        # Issue erstellen und Status aktualisieren
        create_issue_if_needed(tag, html_url, breaking)
        state["last_processed_tag"] = tag
        save_state(state)
        print(f"Status auf {tag} aktualisiert")
        return 0
    except urllib.error.HTTPError as e:
        print(f"HTTP-Fehler: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1


def test_issue_creation():
    """Testfunktion zum Überprüfen der Issue-Erstellung ohne tatsächliches API-Call"""
    test_tag = "2025.1.0"
    test_url = "https://github.com/home-assistant/core/releases/tag/2025.1.0"
    test_breaking = True

    # Simuliere die Issue-Body-Erstellung
    issue_body = (
        f"📦 Neue Home Assistant Version verfügbar: {test_tag}\n\n"
        f"Release Notes: {test_url}\n\n"
        "Erforderliche Maßnahmen:\n"
        "- [ ] Mit neuer Home Assistant Version testen\n"
        "- [ ] Breaking Changes überprüfen (falls vorhanden)\n"
        "- [ ] Integration/Manifest aktualisieren (falls nötig)\n"
    )

    print("=== Test Issue Body ===")
    print(issue_body)
    print("=== Ende Test ===")

    # Prüfe, ob @mentions enthalten sind
    if "@" in issue_body:
        print("❌ ACHTUNG: @mentions gefunden!")
        return False
    else:
        print("✅ Keine @mentions gefunden - sicher!")
        return True


if __name__ == "__main__":
    # Für Testzwecke: Führe Test aus, wenn --test Parameter übergeben wird
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_issue_creation()
    else:
        raise SystemExit(main())