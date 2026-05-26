"""Scrape https://raider.io/weekly-routes and write raiderio_weekly.json.

The post HTML is the source of truth for what routes exist; see the
CUSTOMIZE block below for the selectors / parsing logic you need to
maintain when raider.io ships a redesign.

Exit code 0 = wrote JSON, 1 = aborted (zero routes extracted -- preserve
the previous good file rather than overwriting with empty).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://raider.io/weekly-routes"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "raiderio_weekly.json"

# Maintained by hand to mirror MAPPING_REGISTRY in the plugin's main.lua.
# Add an entry here when a new dungeon appears in MAPPING_REGISTRY.
DUNGEON_NAME_TO_INSTANCE_ID = {
    "Algeth'ar Academy":       2526,
    "Magister's Terrace":      2811,
    "Maisara Caverns":         2874,
    "Nexus Point Xenas":       2915,
    "Pit of Saron":            658,
    "Seat of the Triumvirate": 1753,
    "Skyreach":                1209,
    "Windrunner Spire":        2805,
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def fetch_html(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.text


def parse_post(html: str) -> dict[str, Any]:
    """Pick the latest weekly-routes post out of the listing page and
    return its parsed payload.

    CUSTOMIZE: inspect https://raider.io/weekly-routes manually, then
    update the selectors below to match the real DOM. The fields the
    rest of this script expects:
        post_url: str
        post_title: str
        week_label: str   (e.g. "Week of May 25")
        routes: dict[str, list[dict]]   keyed by dungeon display name,
            each entry: {"name": str, "mdt_string": str,
                         "author": str|None, "score": float|None}
    """
    soup = BeautifulSoup(html, "html.parser")

    # CUSTOMIZE START -----------------------------------------------------
    # Example skeleton; replace selectors with whatever raider.io ships.
    post_link = soup.select_one("a.weekly-routes-post-link")
    if post_link is None:
        raise RuntimeError("No weekly-routes post link found on the index page.")
    post_url = post_link.get("href", "")
    if post_url.startswith("/"):
        post_url = "https://raider.io" + post_url

    post_html = fetch_html(post_url)
    post_soup = BeautifulSoup(post_html, "html.parser")

    post_title = (post_soup.title.string or "").strip() if post_soup.title else ""

    # Try to pull a week label from the title; fall back to today.
    m = re.search(r"Week of ([A-Za-z]+ \d+)", post_title)
    week_label = m.group(1) if m else datetime.now(timezone.utc).strftime("Week of %B %d")

    # Each dungeon section: expect a heading with the dungeon name and a
    # `<code>` block (or similar) containing the MDT string starting with `!`.
    routes_by_dungeon: dict[str, list[dict[str, Any]]] = {}
    for section in post_soup.select("section.dungeon-route"):
        name_el = section.select_one(".dungeon-name")
        code_el = section.select_one("code.mdt-string, pre.mdt-string")
        if name_el is None or code_el is None:
            continue
        dungeon_name = name_el.get_text(strip=True)
        mdt_string = code_el.get_text(strip=True)
        if not mdt_string.startswith("!"):
            continue
        author_el = section.select_one(".route-author")
        score_el = section.select_one(".route-score")
        routes_by_dungeon.setdefault(dungeon_name, []).append({
            "name": dungeon_name + " - " + week_label,
            "mdt_string": mdt_string,
            "author": author_el.get_text(strip=True) if author_el else None,
            "score": float(score_el.get_text(strip=True)) if score_el else None,
        })
    # CUSTOMIZE END -------------------------------------------------------

    return {
        "post_url": post_url,
        "post_title": post_title,
        "week_label": week_label,
        "routes_by_dungeon_name": routes_by_dungeon,
    }


def remap_to_instance_ids(routes_by_name: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Convert dungeon-name keyed entries to instance-id-string keyed
    entries, dropping any dungeon name that isn't in the mapping table
    (logging a warning)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name, entries in routes_by_name.items():
        inst_id = DUNGEON_NAME_TO_INSTANCE_ID.get(name)
        if inst_id is None:
            print(f"WARN: dungeon name not in mapping table, skipping: {name!r}", file=sys.stderr)
            continue
        out[str(inst_id)] = entries
    return out


def main() -> int:
    html = fetch_html(SOURCE_URL)
    parsed = parse_post(html)
    routes = remap_to_instance_ids(parsed["routes_by_dungeon_name"])

    total = sum(len(v) for v in routes.values())
    if total == 0:
        print("ABORT: zero routes extracted; refusing to overwrite raiderio_weekly.json", file=sys.stderr)
        return 1

    payload = {
        "post_url": parsed["post_url"],
        "post_title": parsed["post_title"],
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": "",  # populate if you parse it from the post
        "week_label": parsed["week_label"],
        "routes": routes,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Wrote {OUTPUT_PATH} with {total} route(s) across {len(routes)} dungeon(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
